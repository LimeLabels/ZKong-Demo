## Workers

### Overview

The workers in `app/workers` are responsible for all long‑running background
processing in the system. They are intentionally separated from the HTTP API to:

- Process sync and pricing workloads asynchronously and reliably.
- Protect the Hipoink ESL API from being called directly from routers.
- Implement retries and backoff without blocking requests.

At runtime, `python -m app.workers` (see `__main__.py`) starts:

- The **ESL sync worker** (`SyncWorker`).
- The **price scheduler** (`PriceScheduler`).
- The **Square and Clover token refresh scheduler**.
- The **Clover polling sync worker**.
- A lightweight HTTP health server for Railway.
- Optionally (currently disabled): the **NCR product sync worker**.

All workers interact with Supabase via `SupabaseService` and respect the
multi‑tenant model based on `store_mappings`.

### Entry point and process model

`app/workers/__main__.py`:

- Defines the module entry point:
  - `python -m app.workers`
- On startup:
  - Configures logging.
  - Starts a small HTTP server on `PORT` (default `8080`) that serves `200 ok`
    on `GET /health` for Railway health checks.
  - Starts all workers concurrently via:
    - `asyncio.gather(run_worker(), run_price_scheduler(), run_token_refresh_scheduler(), run_clover_sync_worker())`
    - `run_ncr_sync_worker()` exists but is commented out (temporarily disabled).

The expectation is that this module runs in its own process (or container) next to
the FastAPI app, so API and worker lifecycles can be managed independently.

### SyncWorker – ESL sync pipeline

File: `sync_worker.py`  
Class: `SyncWorker`  
Entry function: `run_worker()`

**Responsibility**

The sync worker is the only component that talks to the Hipoink ESL API. It:

- Polls the Supabase `sync_queue` table for pending items.
- Fetches the associated `Product` and `StoreMapping`.
- Translates normalized product data into Hipoink product payloads.
- Sends create/update/delete requests to Hipoink.
- Updates `sync_queue` and `sync_log` with status, timing, and error details.

**Data flow**

1. Integrations (Shopify, Square, Clover, NCR) write products to Supabase using
   their respective adapters:
   - See:
     - `app/integrations/shopify/README.md`
     - `app/integrations/square/README.md`
     - `app/integrations/clover/README.md`
     - `app/integrations/ncr/README.md`
2. When a product is valid and needs to be synced, an entry is added to
   `sync_queue` via `SupabaseService.add_to_sync_queue(...)`, with:
   - `product_id`
   - `store_mapping_id`
   - `operation` (`create`, `update`, `delete`)
   - `status="pending"`.
3. `SyncWorker` periodically fetches a batch of pending items using
   `get_pending_sync_queue_items(limit=10)` and for each item:
   - Marks the entry as `"syncing"`.
   - Loads `Product` and `StoreMapping`.
   - Builds one or more `HipoinkProductItem` instances based on `normalized_data`.
   - Calls the appropriate `HipoinkClient` method for the operation.
   - Records success/failure and updates:
     - `sync_queue.status` (`succeeded` / `failed`).
     - `sync_queue.attempts`, timestamps, and error messages.
     - `sync_log` entries for observability and audit.
4. Retry logic distinguishes between transient and permanent errors using
   `TransientError` and `PermanentError` from `app/utils/retry.py`, and respects
   a maximum retry count with backoff.

In short, queue items follow the lifecycle:

`pending → syncing → succeeded | failed` (with retries up to the configured maximum).

**Notes**

- Routers and integrations must not call `HipoinkClient` directly; they are
  expected to enqueue work in `sync_queue` and let the worker process it.
- All Supabase access is via `SupabaseService`.

### PriceScheduler – time‑based pricing

File: `price_scheduler.py`  
Class: `PriceScheduler`  
Entry function: `run_price_scheduler()`

**Responsibility**

The price scheduler processes price adjustment schedules and applies price changes
to both the POS/BOS systems and the Hipoink ESL platform. It:

- Polls Supabase for `PriceAdjustmentSchedule` rows whose `next_trigger_at` is due.
- Determines store timezones and schedule behavior (one‑off vs recurring).
- Computes the next trigger time and updates the schedule.
- Applies price changes across:
  - Hipoink.
  - Shopify (via `ShopifyAPIClient`).
  - Square (via `SquareIntegrationAdapter`).
  - Clover (via `CloverIntegrationAdapter`).
  - NCR (via `NCRIntegrationAdapter`).

**Data flow**

1. Schedules are stored in Supabase with references to `store_mappings`, including
   metadata for repeat rules and time windows. See:
   - `docs/TIME_BASED_PRICING.md`
   - `external-tool/README.md` for the external UI.
2. `PriceScheduler`:
   - Calls `SupabaseService.get_schedules_due_for_trigger(current_time_utc)` to
     retrieve schedules whose `next_trigger_at` is in the past.
   - For each schedule:
     - Loads the associated `StoreMapping`.
     - Determines the store timezone via `get_store_timezone(store_mapping)`.
     - Logs contextual schedule details (name, repeat type, time slots).
3. Price application is then delegated according to `store_mapping.source_system`:
   - **Shopify**:
     - Uses `ShopifyAPIClient` and the schedule’s rules to adjust prices in Shopify,
       then typically enqueues updates for ESL.
   - **Square**:
     - Uses `SquareIntegrationAdapter` (e.g. `update_catalog_object_price`) to
       update catalog variation prices via the Square API, and updates Supabase
       products accordingly.
   - **Clover**:
     - Uses `CloverIntegrationAdapter.update_item_price(...)` to change BOS prices
       and mirror them in Supabase.
   - **NCR**:
     - Uses `NCRIntegrationAdapter.update_price(...)` or
       `NCRIntegrationAdapter.pre_schedule_prices(...)` depending on whether
       immediate or scheduled pricing is being used.
4. After applying changes, `PriceScheduler`:
   - Updates the schedule’s next trigger time (or marks it complete for one‑off
     schedules) using Supabase.
   - Logs any errors, but continues processing other schedules.

**Notes**

- The scheduler is timezone‑aware via per‑store metadata to avoid applying
  changes at the wrong local time.
- Price updates to ESL ultimately go through the `SyncWorker` after products
  are updated in Supabase.

### TokenRefreshScheduler – Square and Clover OAuth

File: `token_refresh_scheduler.py`  
Class: `SquareTokenRefreshScheduler`  
Entry function: `run_token_refresh_scheduler()`

**Responsibility**

The token refresh scheduler ensures that Square and Clover access tokens do not
expire silently. It:

- Periodically scans active store mappings for Square and Clover.
- Detects tokens that are expiring soon based on metadata.
- Uses the integration‑specific token refresh services to obtain fresh tokens.
- Writes updated tokens back to Supabase via `SupabaseService`.

**Data flow**

1. At a fixed interval (every 24 hours by default), `SquareTokenRefreshScheduler.start()`:
   - Calls `check_and_refresh_tokens()`, which in turn calls:
     - `_check_square_tokens()`
     - `_check_clover_tokens()`
2. For **Square**:
   - `_get_square_store_mappings()` fetches active Square `StoreMapping` rows that
     have a `square_refresh_token` in `metadata`.
   - `_should_refresh_square_token(...)` decides whether to refresh based on
     `square_expires_at` using `SquareTokenRefreshService.is_token_expiring_soon(...)`.
   - When a token needs refresh:
     - Calls `SquareTokenRefreshService.refresh_token_and_update(store_mapping)`,
       which performs the actual OAuth refresh and updates Supabase.
3. For **Clover**:
   - `_get_clover_store_mappings()` fetches active Clover `StoreMapping` rows that
     have a `clover_refresh_token` in `metadata`.
   - `_should_refresh_clover_token(...)` decides based on
     `clover_access_token_expiration` using
     `CloverTokenRefreshService.is_token_expiring_soon(...)`.
   - When a token needs refresh:
     - Calls `CloverTokenRefreshService.refresh_token_and_update(store_mapping)`.

**Notes**

- Day‑to‑day token usage in the adapters (`_ensure_valid_token` in both Square and
  Clover) relies on the tokens stored by this scheduler.
- The scheduler logs counts of refreshed, failed, and skipped mappings for
  observability.

### CloverSyncWorker – Clover polling sync

File: `clover_sync_worker.py`  
Class: `CloverSyncWorker`  
Entry function: `run_clover_sync_worker()`

**Responsibility**

The Clover sync worker runs a polling loop over all active Clover store mappings
and delegates sync work to `CloverIntegrationAdapter`. It:

- Periodically finds active Clover store mappings with tokens.
- Calls `CloverIntegrationAdapter.sync_products_via_polling(...)` per merchant.
- Logs items processed, deleted, and any per‑item errors.

**Data flow**

1. On each interval (default 300 seconds, configurable via
   `settings.clover_sync_interval_seconds`), `CloverSyncWorker`:
   - Uses `SupabaseService.get_store_mappings_by_source_system("clover")`.
   - Filters out inactive mappings or those without tokens.
2. For each merchant mapping:
   - Calls `adapter.sync_products_via_polling(store_mapping)`, which:
     - Reads last sync timestamps and poll counters from metadata.
     - Fetches items changed since the last sync via `CloverAPIClient`.
     - Upserts `Product` rows and queues `sync_queue` operations for create/update.
     - Performs ghost‑item cleanup and queues deletes.
3. Logs per‑merchant results for visibility.

**Notes**

- This worker is tightly coupled with the behavior described in
  `app/integrations/clover/README.md` and should be kept in sync with any
  changes made there.

### NCRSyncWorker – NCR product discovery (disabled)

File: `ncr_sync_worker.py`  
Class: `NCRSyncWorker`  
Entry function: `run_ncr_sync_worker()` (import commented out in `__main__.py`)

**Responsibility**

The NCR sync worker is designed to poll the NCR PRO Catalog API to discover
products created directly in NCR POS (e.g. via MART) and align them with the
Supabase `products` table. It is currently **disabled** in production by
commenting out its import and usage in `__main__.py`.

**Data flow (when enabled)**

1. At a fixed interval (default 60 seconds), it:
   - Fetches all NCR store mappings via `get_store_mappings_by_source_system("ncr")`.
   - For each store mapping:
     - Builds an `NCRAPIClient` using `ncr_base_url`, `ncr_shared_key`,
       `ncr_secret_key`, `ncr_organization`, `ncr_enterprise_unit` from metadata.
     - Calls `fetch_all_ncr_items(...)` to list items via the NCR API.
2. For each NCR item:
   - Transforms it into a `NormalizedProduct` via `NCRIntegrationAdapter.transform_product(...)`.
   - Fetches the current effective price via `NCRAPIClient.get_item_price(...)`
     (where available) and updates the normalized price.
   - Compares against existing `Product` rows in Supabase for that `source_store_id`.
   - Creates or updates `Product` rows with `source_system="ncr"`.
   - Enqueues `sync_queue` entries for new/changed products so ESL tags are created/updated.

**Notes**

- This worker is intentionally disabled to reduce load and complexity until NCR
  discovery is required. Any future enablement should:
  - Re‑enable `run_ncr_sync_worker()` in `__main__.py`.
  - Re‑validate HMAC configuration and rate limits for the NCR API.
  - Ensure Supabase and ESL capacity is sufficient for the resulting sync volume.

### Running workers locally

- To run all workers locally:

```bash
python -m app.workers
```

- Environment expectations:
  - Database and Supabase credentials configured in `app/config.py`.
  - Hipoink credentials configured for `HipoinkClient`.
  - Integration‑specific settings (Shopify, Square, Clover, NCR) present in
    environment variables and store mappings.

When developing or debugging:

- Use logs produced by `structlog` to trace per‑product and per‑schedule behavior.
- Inspect `sync_queue`, `sync_log`, `products`, `price_adjustments`, and
  `store_mappings` in Supabase to understand the state of the pipeline.

