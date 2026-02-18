## Workers

### What Is This?

The workers are the **background engine** of the system. While the FastAPI backend handles incoming HTTP requests, the workers run continuously in a separate process and handle everything that happens asynchronously — syncing products to shelf labels, applying scheduled price changes, refreshing OAuth tokens, and polling external systems for updates.

Think of the API as the front desk that accepts requests, and the workers as the back office that actually does the heavy lifting.

All workers live in `app/workers/` and are started together with a single command:

```bash
python -m app.workers
```

---

### What Does It Do?

| Worker | File | What It Does |
|---|---|---|
| **SyncWorker** | `sync_worker.py` | The only component that talks to Hipoink ESL. Processes the sync queue and pushes product changes to shelf labels |
| **PriceScheduler** | `price_scheduler.py` | Fires time-based pricing events — applies price changes to BOS systems (Shopify, Square, Clover, NCR) and ESL labels on schedule |
| **TokenRefreshScheduler** | `token_refresh_scheduler.py` | Proactively refreshes Square and Clover OAuth tokens before they expire |
| **CloverSyncWorker** | `clover_sync_worker.py` | Polls Clover for product changes on a regular interval as a safety net alongside webhooks |
| **NCRSyncWorker** | `ncr_sync_worker.py` | ⚠️ Currently **disabled**. Polls NCR for product discovery (see below) |
| **Health Server** | `__main__.py` | Lightweight HTTP server on `/health` so Railway knows the worker process is alive |

---

### Why Are Workers Separate?

The workers are intentionally separated from the HTTP API for three reasons:

1. **Reliability** — long-running sync tasks and retries don't block or slow down API responses
2. **Protection** — the Hipoink ESL API is only ever called from the sync worker, never directly from routers or adapters
3. **Scalability** — the worker process can be scaled or restarted independently of the API

---

### Entry Point — `__main__.py`

This is what runs when you do `python -m app.workers`. It:

1. Configures structured logging
2. Starts a minimal HTTP health server on `PORT` (default `8080`) that responds `200 ok` to any `GET /health` — this is required by Railway to confirm the worker is running
3. Runs all workers concurrently using `asyncio.gather()`

```python
await asyncio.gather(
    run_worker(),                  # ESL sync
    run_price_scheduler(),         # Price scheduling
    run_token_refresh_scheduler(), # OAuth token refresh
    run_clover_sync_worker(),      # Clover polling
    # run_ncr_sync_worker(),       # Disabled for now
)
```

The worker process is designed to run alongside the FastAPI app as a separate Railway service, so both can be managed and scaled independently.

---

### SyncWorker — ESL Sync Pipeline

**File:** `sync_worker.py` | **Class:** `SyncWorker` | **Entry:** `run_worker()`

#### What It Does

The SyncWorker is the **only component in the entire system that calls the Hipoink ESL API**. Everything else (adapters, routers, the price scheduler) writes to the `sync_queue` table in Supabase, and the SyncWorker picks up those entries and pushes them to Hipoink.

This design means:
- No part of the system accidentally bypasses the queue
- All ESL updates are logged and retried automatically
- The Hipoink API is never overloaded by direct calls from multiple places

#### How It Works

```text
Integration adapter receives product change
        ↓
Writes to Supabase: products table + sync_queue (status="pending")
        ↓
SyncWorker polls sync_queue for pending items (batch of 10)
        ↓
For each item:
  Marks status as "syncing"
  Loads Product and StoreMapping from Supabase
  Builds HipoinkProductItem from normalized_data
        ↓
  Calls HipoinkClient:
    operation="create" → create product on ESL label
    operation="update" → update product on ESL label
    operation="delete" → remove product from ESL label
        ↓
  On success: status="succeeded", logs timing
  On failure: status="failed", logs error, schedules retry
        ↓
Updates sync_log for full audit trail
```

#### Queue Item Lifecycle

```text
pending → syncing → succeeded
                 ↘ failed (retried up to max attempts)
```

Retries distinguish between:
- **Transient errors** (network timeout, temporary API failure) → retried with backoff
- **Permanent errors** (bad data, invalid product) → marked failed immediately, no retry

#### Important Rule

> Routers and integration adapters must **never** call `HipoinkClient` directly. They must write to `sync_queue` and let the SyncWorker handle it.

---

### PriceScheduler — Time-Based Pricing

**File:** `price_scheduler.py` | **Class:** `PriceScheduler` | **Entry:** `run_price_scheduler()`

#### What It Does

The PriceScheduler watches for price adjustment schedules that are due to fire and applies the price changes across all connected systems — both the BOS (Back Office System) and the ESL labels.

#### How It Works

```text
PriceScheduler runs every 60 seconds
        ↓
Queries Supabase for schedules where next_trigger_at <= now (UTC)
        ↓
For each due schedule:
  Loads the associated StoreMapping
  Determines store timezone from metadata
  Logs schedule context (name, repeat type, time slots)
        ↓
Delegates price update based on store_mapping.source_system:
        ↓
  Shopify  → ShopifyAPIClient (updates Shopify prices + queues ESL update)
  Square   → SquareIntegrationAdapter.update_catalog_object_price()
  Clover   → CloverIntegrationAdapter.update_item_price()
  NCR      → NCRIntegrationAdapter.update_price() or pre_schedule_prices()
        ↓
Updates schedule:
  - Recurring: recalculates next_trigger_at
  - One-off: marks as complete
        ↓
Logs errors per schedule but continues processing others
```

#### Timezone Awareness

Every schedule fires at the correct **local store time**, not UTC. The store's timezone is stored in `store_mappings.metadata` and used to determine when a schedule should fire. If no timezone is set, it defaults to UTC.

#### ESL Updates

Price updates to ESL labels don't happen directly from the scheduler. Instead:
1. The scheduler updates the product price in Supabase
2. That update triggers a `sync_queue` entry
3. The SyncWorker picks it up and pushes the new price to the ESL label

For more details on schedule structure and repeat types, see `docs/TIME_BASED_PRICING.md`.

---

### TokenRefreshScheduler — OAuth Token Management

**File:** `token_refresh_scheduler.py` | **Class:** `SquareTokenRefreshScheduler` | **Entry:** `run_token_refresh_scheduler()`

#### What It Does

Square and Clover OAuth access tokens expire. If they expire silently, product syncs and price updates will start failing with auth errors. The TokenRefreshScheduler proactively refreshes tokens before they expire so everything keeps working without intervention.

#### How It Works

```text
Runs every 24 hours
        ↓
Checks all active Square store mappings:
  Reads square_expires_at from metadata
  If expiring soon → calls SquareTokenRefreshService.refresh_token_and_update()
  Writes new tokens back to Supabase
        ↓
Checks all active Clover store mappings:
  Reads clover_access_token_expiration from metadata
  If expiring soon → calls CloverTokenRefreshService.refresh_token_and_update()
  Writes new tokens back to Supabase
        ↓
Logs: refreshed count, failed count, skipped count
```

The adapters themselves (`_ensure_valid_token()` in both Square and Clover) rely on the fresh tokens stored by this scheduler. The scheduler is the proactive layer; the adapter check is the last-minute safety net.

---

### CloverSyncWorker — Clover Polling

**File:** `clover_sync_worker.py` | **Class:** `CloverSyncWorker` | **Entry:** `run_clover_sync_worker()`

#### What It Does

Clover webhooks handle real-time events, but webhooks can occasionally be missed or delayed. The CloverSyncWorker polls Clover on a regular schedule to ensure eventual consistency — it catches anything the webhooks missed.

#### How It Works

```text
Runs every 300 seconds (5 minutes) by default
(configurable via settings.clover_sync_interval_seconds)
        ↓
Fetches all active Clover store mappings from Supabase
Filters out mappings with no tokens
        ↓
For each merchant:
  Calls CloverIntegrationAdapter.sync_products_via_polling(store_mapping)
  Which:
    - Reads last sync timestamp from metadata
    - Fetches items modified since then
    - Upserts products in Supabase
    - Queues sync_queue operations for ESL
    - Every 10 polls: runs ghost-item cleanup
        ↓
Logs: items processed, deleted, errors per merchant
```

For full details on what `sync_products_via_polling` does, see `app/integrations/clover/README.md`.

---

### NCRSyncWorker — NCR Product Discovery (Currently Disabled)

**File:** `ncr_sync_worker.py` | **Class:** `NCRSyncWorker` | **Entry:** `run_ncr_sync_worker()`

> ⚠️ **This worker is currently disabled.** Its import is commented out in `__main__.py`.

#### What It Does (When Enabled)

Discovers products that were created directly in NCR POS and syncs them into Supabase so they can be pushed to ESL labels.

#### How It Would Work

```text
Runs every 60 seconds
        ↓
Fetches all NCR store mappings from Supabase
        ↓
For each store:
  Builds NCRAPIClient using credentials from store metadata
  Calls fetch_all_ncr_items() to list all items via NCR API
        ↓
For each item:
  Transforms to NormalizedProduct via NCRIntegrationAdapter.transform_product() 
  Fetches current price via NCRAPIClient.get_item_price()
  Compares against existing Product rows in Supabase
  Creates or updates Product rows
  Enqueues sync_queue entries for new/changed products
```

#### How to Re-Enable

1. Uncomment `run_ncr_sync_worker()` in `__main__.py`
2. Re-validate HMAC configuration and NCR API rate limits
3. Confirm Supabase and ESL capacity can handle the resulting sync volume

---

### Running Workers Locally

```bash
python -m app.workers
```

#### Environment Requirements

| Category | What's Needed |
|---|---|
| Database | Supabase credentials (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) |
| ESL | Hipoink credentials for `HipoinkClient` |
| Shopify | Shopify settings + store mappings in Supabase |
| Square | Square OAuth tokens in store mappings |
| Clover | Clover OAuth tokens + `CLOVER_TOKEN_ENCRYPTION_KEY` |
| NCR | NCR credentials in store mapping metadata |

#### Debugging Tips

- Use `structlog` output to trace per-product and per-schedule behavior
- Inspect these Supabase tables to understand pipeline state:
  - `sync_queue` — pending/failed/succeeded sync items
  - `sync_log` — full audit trail of all sync operations
  - `products` — normalized product data and validation status
  - `price_adjustment_schedules` — schedule state and next trigger times
  - `store_mappings` — per-store credentials, metadata, and timezone
