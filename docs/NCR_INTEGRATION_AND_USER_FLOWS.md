# NCR Integration, User Onboarding, Time-Based Pricing & User Flows

This document is an in-depth reference for the **NCR integration**, **user onboarding**, **time-based pricing** with NCR, and **end-to-end user flows** in the Hipoink ESL middleware.

---

## Table of Contents

1. [NCR Integration](#1-ncr-integration)
2. [User Onboarding (NCR)](#2-user-onboarding-ncr)
3. [Time-Based Pricing with NCR](#3-time-based-pricing-with-ncr)
4. [User Flows](#4-user-flows)
5. [Data Models & APIs](#5-data-models--apis)
6. [Environment & Running](#6-environment--running)

---

# 1. NCR Integration

## 1.1 Overview

The NCR integration connects the middleware to the **NCR PRO Catalog API** — a retail catalog and pricing system used in enterprise point-of-sale (POS) environments. Unlike Shopify, **NCR does not send webhooks**. All communication is **API-driven**:

- The middleware **polls NCR** to discover products created or updated directly in NCR POS (product discovery).
- The middleware **pushes** data to NCR when creating/updating products or prices (create product, update price, logical delete).

The integration:

- **Polls NCR** to sync products from NCR POS into Supabase and then to ESL labels (primary sync mechanism when the NCR sync worker is enabled).
- **Creates, updates, and logically deletes** products in NCR via the NCR API.
- **Manages prices** including real-time updates and optional **future-dated scheduled prices** (effectiveDate) in NCR.
- Keeps **Supabase** and **ESL labels** in sync with NCR’s catalog.

All NCR flows use the same central pipeline for ESL: **products → sync_queue → sync_worker → Hipoink**. The NCR adapter never calls Hipoink directly.

---

## 1.2 Capabilities

| Capability | Description |
|------------|-------------|
| **Product discovery (polling)** | **Primary sync mechanism** — NCR sync worker polls NCR API to discover products created/updated in NCR POS and syncs them to Supabase and ESL labels |
| **Create products** | Creates new catalog items in NCR via API and saves them to Supabase; can enqueue for ESL sync |
| **Update prices** | Updates item prices in NCR via API; updates Supabase and enqueues ESL sync |
| **Delete products** | Logically deletes (marks INACTIVE) items in NCR; queues ESL removal |
| **Pre-schedule prices** | Optional: sends future-dated price changes to NCR using `effectiveDate` (NCR applies them at the right time) |
| **Multi-tenant support** | Each store has its own NCR credentials in its store mapping metadata |

> **No webhooks.** NCR does not send real-time notifications. Any `/webhooks/ncr/...` traffic is a misconfiguration; the adapter returns `501 Not Implemented` for webhooks.

---

## 1.3 Data Flows

### 1.3.1 Creating a Product

```
NormalizedProduct received (e.g. from another system or API)
        ↓
NCRIntegrationAdapter.create_product() called
        ↓
Item code determined: barcode → SKU → source_id (priority order)
        ↓
NCRAPIClient.create_product() → HMAC-signed PUT /items/{itemCode} to NCR
(optionally creates initial item-prices record if price provided)
        ↓
Validate and upsert Product in Supabase
(source_system="ncr", source_id=item_code, source_store_id=enterprise_unit_id)
        ↓
If product valid and changed → enqueue sync_queue (operation="create")
        ↓
SyncWorker picks up → creates ESL label via Hipoink
```

### 1.3.2 Updating a Price

```
Price update triggered (e.g. by time-based pricing scheduler)
        ↓
NCRIntegrationAdapter.update_price(item_code, price, store_mapping_config)
        ↓
NCRAPIClient.update_price() → HMAC-signed PUT /item-prices to NCR
        ↓
Look up Product in Supabase; update product.price and normalized_data["price"]
        ↓
Enqueue sync_queue (operation="update") → SyncWorker → ESL label updated
```

### 1.3.3 Deleting a Product

NCR uses **logical (soft) deletes** — items are marked `INACTIVE`, not physically removed.

```
Delete triggered
        ↓
NCRIntegrationAdapter.delete_product(item_code, store_mapping_config)
        ↓
HMAC-signed PUT /items/{itemCode} with status="INACTIVE" to NCR
        ↓
Find Product(s) in Supabase by source_id (and source_store_id)
        ↓
Enqueue sync_queue (operation="delete") for each
        ↓
SyncWorker removes or deactivates ESL label(s)
```

### 1.3.4 Product Discovery via Polling (NCR → ESL)

> **Note:** The NCR sync worker is **temporarily disabled** in `app/workers/__main__.py` (rate limits / production validation). Re-enabling it is the intended production state.

This is the **primary mechanism** for syncing products from NCR POS to ESL when products are created or updated directly in NCR.

```
NCRSyncWorker runs every 60 seconds
        ↓
Fetch all active NCR store mappings from Supabase
        ↓
For each store mapping:
  Build NCRAPIClient from store metadata (ncr_shared_key, ncr_secret_key, etc.)
  GET /items with pagination (e.g. 200 per page)
        ↓
Fetch ALL items from NCR catalog
        ↓
For each NCR item:
  Compare with existing Product rows in Supabase (by source_id, source_store_id)
  Fetch current effective price from NCR (respects scheduled prices)
        ↓
If new product:
  Transform to NormalizedProduct → create Product in Supabase → enqueue sync_queue (create)
If existing product changed (title, barcode, SKU, or price difference > $0.01):
  Update Product in Supabase → enqueue sync_queue (update)
        ↓
SyncWorker processes queue → ESL labels updated
```

**Behaviors:**

- **Price change detection:** Poller sees both manual price changes and scheduled prices that became active (by comparing NCR price with stored price).
- **Full catalog scan:** Every poll fetches the full catalog so nothing is missed.
- **Multi-tenant isolation:** All queries filter by `source_store_id`.
- **Pagination:** Uses NCR’s `pageNumber` / `pageSize` for large catalogs.

**Re-enabling the NCR sync worker:**

1. Uncomment `run_ncr_sync_worker()` in `app/workers/__main__.py`.
2. Confirm NCR API rate limits support polling every 60 seconds.
3. Verify Supabase and ESL capacity for the resulting sync volume.

---

## 1.4 Authentication — HMAC-SHA512

NCR uses **HMAC-SHA512** for all API authentication. There are no OAuth tokens; every request is signed.

**Signature flow** (in `NCRAPIClient._generate_signature`):

1. Build a **nonce** from the current date.
2. Concatenate: HTTP method, full URI (including query), `Content-Type`, `Content-MD5`, `nep-organization`.
3. Compute HMAC-SHA512 using `secret_key + nonce`.
4. Base64-encode the result.
5. Send header: `Authorization: AccessKey {shared_key}:{signature}`

**Per-store NCR configuration** is stored in `store_mappings.metadata`:

| Field | Description |
|-------|-------------|
| `ncr_base_url` | NCR API base URL (e.g. `https://api.ncr.com/catalog`) |
| `ncr_shared_key` | Public key for the Authorization header |
| `ncr_secret_key` | Private key for HMAC signing |
| `ncr_organization` | NCR organization identifier |
| `ncr_enterprise_unit` | Enterprise unit / store identifier |
| `department_id` | Default department for new items |
| `category_id` | Default merchandise category for new items |

All of these are resolved per `StoreMapping`; there is no global NCR credential.

---

## 1.5 Key Components

### NCRIntegrationAdapter (`adapter.py`)

- `get_name()` → `"ncr"`.
- `transform_product(raw_data)` — Converts NCR catalog records into `NormalizedProduct` (itemCode → source_id, descriptions, SKU, barcodes).
- `create_product(...)` — Builds item data, calls `NCRAPIClient.create_product(...)`, upserts Product in Supabase, enqueues sync when needed.
- `update_price(...)` — Calls `NCRAPIClient.update_price(...)`, updates `product.price` and `normalized_data["price"]`, enqueues sync.
- `delete_product(...)` — Soft-deletes in NCR (status=INACTIVE), queues ESL deletions from Supabase products.
- `pre_schedule_prices(...)` — Optional: computes all price events for a schedule and sends them to NCR with `effectiveDate` (see [Time-Based Pricing with NCR](#3-time-based-pricing-with-ncr)).
- **Webhooks:** `get_supported_events()` returns `[]`; `handle_webhook(...)` returns `501 Not Implemented`.

### NCRAPIClient (`api_client.py`)

- `_generate_signature(...)` — Builds HMAC-SHA512 signature.
- `_get_request_headers(method, url, body)` — Sets Content-Type, Accept, nep-organization, nep-enterprise-unit, Date, Content-MD5, Authorization.
- `create_product(...)` — PUT /items/{itemCode}.
- `update_price(...)` — PUT /item-prices.
- `delete_product(...)` — PUT /items/{itemCode} with status=INACTIVE.
- `list_items(...)` — GET /items with pagination.
- `get_item_price(...)` / `get_item_prices_batch(...)` — Read current prices (including effectiveDate).
- `pre_schedule_prices(price_events)` — Batches and sends PUT /item-prices for future-dated prices.

### NCRTransformer

- Maps NCR item payloads to `NormalizedProduct` (itemCode, descriptions, SKU, barcodes, etc.).

---

## 1.6 Product Data in Supabase

Each NCR-sourced row in `products` has:

| Field | Value |
|-------|--------|
| `source_system` | `"ncr"` |
| `source_id` | NCR item code |
| `source_store_id` | Enterprise unit / store identifier (multi-tenant) |
| `source_variant_id` | From transformer if applicable |
| Other fields | title, barcode, sku, price, currency, normalized_data, raw_data, status |

---

## 1.7 Multi-Tenant Safety

- Each store has its own NCR credentials in that store’s `store_mappings.metadata`.
- All Supabase product/sync queries filter by `source_system="ncr"` and `source_store_id`.
- No shared or global NCR keys beyond what NCR requires per request.

---

## 1.8 How NCR Store Mappings Are Created

Unlike Shopify, **NCR does not use OAuth**. Store mappings for NCR are **created separately** (e.g. by an admin or backend process) with:

- `source_system`: `"ncr"`
- `source_store_id`: e.g. NCR enterprise unit ID or a stable store identifier
- `hipoink_store_code`: Hipoink ESL store code
- `metadata`: NCR credentials (`ncr_base_url`, `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, `ncr_enterprise_unit`), optional `timezone`, `department_id`, `category_id`, etc.

Users do **not** create NCR store mappings during onboarding. They **connect** to an **existing** mapping by Hipoink store code and POS type (see [User Onboarding](#2-user-onboarding-ncr)).

---

# 2. User Onboarding (NCR)

## 2.1 Context: External Tool vs Shopify App

- **Shopify:** Onboarding happens inside the **Shopify embedded app**. OAuth creates (or updates) the store mapping; the merchant then completes onboarding by setting Hipoink store code and timezone in the same app.
- **NCR:** Onboarding happens in the **External Time-Based Pricing Tool** (React app). Store mappings for NCR are **pre-created** (no OAuth). Users **log in** with Supabase Auth and then **connect** to an existing NCR store mapping by entering their **Hipoink store code** and selecting **NCR** as the POS system.

---

## 2.2 Prerequisites

- NCR store mapping **already exists** in the database (created via API or admin), with:
  - `source_system`: `"ncr"`
  - `hipoink_store_code` set (e.g. `"001"`)
  - `metadata` containing NCR credentials and optionally `timezone`
- User has an account and is **logged in** via Supabase Auth (Bearer token).

---

## 2.3 Onboarding Flow (Step-by-Step)

```
1. User opens External Tool (e.g. external-tool)
       ↓
2. If not logged in → Login (Supabase Auth: email/password or provider)
       ↓
3. After login, app checks if user has a connected store (e.g. GET /api/auth/me or store check)
       ↓
4. If no store connected → show Onboarding component
       ↓
5. User enters:
   - Hipoink Store Code (e.g. "001")
   - POS System: select "NCR POS"
   - Timezone (e.g. America/Chicago) — used for time-based pricing
       ↓
6. User clicks "Connect Store"
       ↓
7. POST /api/auth/find-store-mapping
   Body: { source_system: "ncr", hipoink_store_code: "001" }
   (Requires: Authorization: Bearer <Supabase JWT>)
       ↓
8. Backend looks up store mapping by source_system + hipoink_store_code
   - If not found → 404: "Store mappings must be created separately before users can connect"
   - If found but metadata.user_id is another user → 409: "Already connected to another user"
       ↓
9. POST /api/auth/connect-store
   Body: { store_mapping_id: "<uuid>" }
       ↓
10. Backend writes user_id (and user_email) into store_mapping.metadata, updates store_mappings row
       ↓
11. (NCR/Clover) Frontend optionally: GET /api/store-mappings/{id}, then PUT /api/store-mappings/{id}
    with metadata: { ...currentMetadata, timezone } to save timezone for schedules
       ↓
12. Success → page reload; next load user has a store → main app (Create Schedule / Manage Schedules)
```

**Important:** The External Tool does **not** create new store mappings. It only **finds** an existing mapping by `(source_system, hipoink_store_code)` and **connects** the current user to it (1:1: one mapping per user connection; one user can be connected to one mapping at a time in the flow above; “my stores” can list multiple if the backend supports it).

---

## 2.4 Onboarding API (Auth & Store Mapping)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| (Supabase) | Login | Obtain JWT for Authorization header |
| `GET` | `/api/auth/me` or equivalent | Current user + whether they have a connected store (implementation-specific) |
| `POST` | `/api/auth/find-store-mapping` | Find mapping by `source_system` + `hipoink_store_code` (returns id, source_store_id, etc.) |
| `POST` | `/api/auth/connect-store` | Associate current user with mapping (`store_mapping_id`); writes `user_id` into metadata |
| `GET` | `/api/store-mappings/{id}` | Get mapping (e.g. to merge timezone into metadata) |
| `PUT` | `/api/store-mappings/{id}` | Update mapping (e.g. metadata.timezone); backend merges metadata |

All of these (except Supabase login) go through the FastAPI backend with `Authorization: Bearer <token>`. The backend verifies the JWT via Supabase Auth.

---

## 2.5 Connect vs Create

- **Connect:** User links their **account** to an **existing** NCR store mapping. No new row in `store_mappings` is created.
- **Create (store mapping):** Done **outside** the onboarding UI (e.g. `POST /api/store-mappings/` by an admin or script) with NCR credentials and `hipoink_store_code`. Users then use onboarding to **connect** to that mapping.

---

# 3. Time-Based Pricing with NCR

## 3.1 Two Ways to Run Time-Based Pricing with NCR

1. **Real-time scheduler (current default):** The **Price Scheduler** worker runs every 15 seconds. When a schedule’s time slot **start** or **end** is reached (in store timezone), it calls `NCRIntegrationAdapter.update_price(...)` for each product. NCR’s price is updated immediately; Supabase and sync_queue are updated; SyncWorker pushes the new price to ESL labels.
2. **Pre-scheduled prices (optional):** NCR supports **future-dated** price changes via `effectiveDate` in the item-prices API. The adapter’s `pre_schedule_prices(...)` computes all price events for a schedule (using `calculate_all_price_events`) and sends them to NCR in batches. NCR then applies those prices at the correct times **without** the middleware triggering at each moment. When NCR applies a scheduled price, the **NCR sync worker** (when enabled) detects the price change on its next poll, updates the Product in Supabase, and enqueues an update for ESL. In the current codebase, the **create schedule** flow does **not** call `pre_schedule_prices` (that call is commented out); the **real-time** path is the one in use.

---

## 3.2 Real-Time Path (Price Scheduler → NCR)

- **Worker:** `PriceScheduler` in `app/workers/price_scheduler.py`.
- **Interval:** Every 15 seconds.
- **Logic:** For each schedule due (e.g. `next_trigger_at <= now`), determine if current time is at **start** or **end** of a time slot (in store timezone).
  - **Start:** Apply promotional price → for NCR, call `_update_ncr_prices(..., use_original=False)` (uses `pp` from schedule products).
  - **End:** Restore original price → `_update_ncr_prices(..., use_original=True)` (uses `original_price`).
- **NCR update:** `_update_ncr_prices` uses `NCRIntegrationAdapter.update_price(item_code, price, store_mapping_config)` for each product. The adapter calls NCR’s PUT /item-prices, then updates the Product in Supabase and enqueues sync_queue (update). SyncWorker then updates ESL.

So for NCR, **only the price** is changed at slot start/end; product identity (item code, title, etc.) is unchanged.

---

## 3.3 Pre-Scheduled Path (Optional)

- **Method:** `NCRIntegrationAdapter.pre_schedule_prices(schedule, store_mapping_config)`.
- **Input:** A price adjustment schedule and the store mapping (with NCR config and timezone in metadata).
- **Steps:**
  1. Resolve store timezone from metadata (default UTC).
  2. `calculate_all_price_events(schedule, store_timezone)` → list of events (apply_promotion / restore_original at specific datetimes).
  3. Convert each event to `{ item_code, price, effective_date (UTC ISO), currency }`.
  4. `NCRAPIClient.pre_schedule_prices(price_events)` → batch PUT /item-prices to NCR with future `effectiveDate`s.
- **Result:** NCR applies prices at those times. The NCR sync worker (when enabled) will see the new prices on the next poll and update Supabase + sync_queue so ESL stays in sync.

Currently, the schedule **create** (and update) endpoints do **not** invoke `pre_schedule_prices` (code is commented out). To use this path, you would call the adapter’s `pre_schedule_prices` when creating or updating a schedule for an NCR store.

---

## 3.4 Schedule Model (Same as Other Integrations)

Same as in the main time-based pricing doc: `store_mapping_id`, `name`, `order_number`, `products` (e.g. `pc`, `pp`, `original_price`), `start_date`, `end_date`, `repeat_type`, `trigger_days`, `trigger_stores`, `time_slots`, `multiplier_percentage`, `is_active`, `last_triggered_at`, `next_trigger_at`. All times are interpreted in the **store’s timezone** (from store mapping metadata).

---

## 3.5 Timezone

NCR time-based pricing uses the **store’s timezone** from `store_mappings.metadata.timezone`. This is set during onboarding (External Tool) when the user selects a timezone and the frontend updates the store mapping. If missing, the system defaults to UTC.

---

# 4. User Flows

## 4.1 End-to-End: Admin Creates NCR Mapping → User Onboards → Schedules Run

```
Admin/backend creates NCR store mapping (POST /api/store-mappings/ or DB)
  - source_system: "ncr", source_store_id: "<enterprise_unit>"
  - hipoink_store_code: "001"
  - metadata: ncr_* credentials, optional timezone, department_id, category_id
       ↓
User opens External Tool → logs in (Supabase Auth)
       ↓
App sees no connected store → shows Onboarding
       ↓
User enters Hipoink store code "001", selects "NCR POS", selects timezone
       ↓
find-store-mapping → connect-store → (optional) PUT store-mappings to set timezone
       ↓
User sees main app: Create Schedule / Manage Schedules
       ↓
User creates a time-based pricing schedule (products, time slots, repeat type, etc.)
       ↓
POST /api/price-adjustments/create (or equivalent) with store_mapping_id
       ↓
Price Scheduler (every 15s) sees next_trigger_at; at slot start/end calls NCR adapter update_price
       ↓
NCR price updated → Supabase updated → sync_queue (update) → SyncWorker → ESL label updated
```

(If the NCR sync worker is enabled, product discovery from NCR POS also runs in the background and keeps products/prices in sync when items are created or changed in NCR.)

---

## 4.2 Create Schedule Flow (NCR Store)

Same as other POS types from the user’s perspective:

- User picks store (already connected NCR mapping).
- Fills schedule: name, dates, repeat type, time slots, trigger days/stores if needed.
- Adds products (by barcode/item code; for NCR, `pc` is typically the item code).
- Submits → backend creates schedule with `next_trigger_at` set.
- Price Scheduler applies/restores prices at slot start/end and updates NCR via `update_price`.

---

## 4.3 Manage Schedules Flow

- User opens “Manage Schedules” (or equivalent).
- Backend returns schedules for the user’s store(s) (e.g. filtered by store_mapping_id or user’s connected mappings).
- User can view, edit, or deactivate schedules. Deactivating sets `is_active=false` so the scheduler ignores the schedule.

---

## 4.4 Background Workers (NCR-Relevant)

| Worker | Role for NCR |
|--------|----------------|
| **SyncWorker** | Processes sync_queue; pushes product create/update/delete to Hipoink ESL. NCR adapter enqueues items after updating NCR and Supabase. |
| **PriceScheduler** | Every 15s; for NCR stores, at slot start/end calls `_update_ncr_prices` → `NCRIntegrationAdapter.update_price` → NCR API + Supabase + sync_queue. |
| **NCRSyncWorker** | **Disabled by default.** When enabled: every 60s polls NCR for all items, diff with Supabase, creates/updates products and enqueues sync. |

---

## 4.5 High-Level Data Flow (NCR)

```
┌─────────────────┐
│  NCR POS / API  │
└────────┬────────┘
         │ Poll (NCRSyncWorker) + Push (adapter create/update/delete/update_price)
         ▼
┌──────────────────┐
│  FastAPI Backend │
│  Store Mappings  │
│  Price Adj API   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Supabase       │
│  store_mappings  │
│  products       │
│  sync_queue     │
│  price_adj...   │
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐  ┌────────────────┐
│ Sync   │  │ Price Scheduler│
│ Worker │  │ (NCR update_   │
│        │  │  price at slot)│
└───┬────┘  └───────┬────────┘
    │               │
    ▼               ▼
┌────────────┐  ┌────────────┐
│ Hipoink ESL│  │  NCR API   │
│    API     │  │ (prices)   │
└────────────┘  └────────────┘
```

---

# 5. Data Models & APIs

## 5.1 Store Mapping (NCR)

- `source_system`: `"ncr"`
- `source_store_id`: e.g. NCR enterprise unit ID
- `hipoink_store_code`: Required for linking to Hipoink ESL store
- `metadata`: NCR credentials (`ncr_base_url`, `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, `ncr_enterprise_unit`), optional `timezone`, `department_id`, `category_id`, `user_id` (after connect), `connected_at`, etc.

## 5.2 Price Adjustment Schedule

Same as other integrations; see main time-based pricing documentation. Products in the schedule use `pc` (product/item code); for NCR this is typically the NCR item code (barcode or primary identifier).

## 5.3 Key Endpoints (NCR-Related)

| Area | Method | Endpoint |
|------|--------|----------|
| Auth (External Tool) | (Supabase) | Login → JWT |
| Auth | POST | `/api/auth/find-store-mapping` (source_system, hipoink_store_code) |
| Auth | POST | `/api/auth/connect-store` (store_mapping_id) |
| Store mappings | GET/PUT | `/api/store-mappings/{id}` |
| Store mappings | POST/GET list | `/api/store-mappings/` (create/list; create used by admin, not by end-user onboarding) |
| Price adjustments | POST | `/api/price-adjustments/create` (or equivalent) |
| Price adjustments | GET | `/api/price-adjustments/?store_mapping_id=...` |
| External (testing) | POST | `/external/ncr/trigger-price-update` (if implemented) |

---

# 6. Environment & Running

## 6.1 Environment Variables

No NCR-specific env vars at the app level. NCR credentials live **per store** in `store_mappings.metadata`:

- `ncr_base_url`
- `ncr_shared_key`
- `ncr_secret_key`
- `ncr_organization`
- `ncr_enterprise_unit`

Supabase (and any auth-related) settings are the same as for the rest of the app.

## 6.2 Services

- **FastAPI backend** — Serves API (auth, store mappings, price adjustments, etc.).
- **Workers process** — `python -m app.workers` runs SyncWorker, PriceScheduler, token refresh, Clover sync. **NCR sync worker is disabled** by default; uncomment in `__main__.py` to enable.
- **External Tool** — React app for login, onboarding (connect store), and schedule management (NCR and other POS types).

## 6.3 Troubleshooting (NCR)

| Problem | What to check |
|---------|----------------|
| Signature / auth errors | Verify `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, `ncr_enterprise_unit` in store metadata. Ensure system clocks are in sync (signatures are time-sensitive). |
| Wrong or inconsistent item codes | Adapter derives item code from barcode → SKU → source_id. Be consistent so updates/deletes target the right item. |
| ESL prices not matching NCR | Confirm `update_price` is being called (scheduler logs). Check sync_queue for update entries and that SyncWorker is running. |
| Pre-scheduled prices not applying | If using `pre_schedule_prices`, check timezone in metadata; effectiveDate is sent in UTC. |
| Products created in NCR not on ESL | Enable and run the NCR sync worker. Check `app/workers/__main__.py` and worker logs for successful polling. |
| User can’t connect store | Ensure a store mapping exists for that `source_system` + `hipoink_store_code`. If 409, mapping is already connected to another user. |

---

## Summary

- **NCR integration:** API-only (no webhooks). Poll NCR for product discovery (NCRSyncWorker, currently disabled); push product create/update/delete and price updates via NCRAPIClient. HMAC-SHA512 per request; credentials per store in metadata.
- **User onboarding (NCR):** In the External Tool. User logs in with Supabase Auth, then connects to an **existing** NCR store mapping by Hipoink store code and POS type (NCR). find-store-mapping + connect-store; optionally update timezone on the mapping.
- **Time-based pricing:** Price Scheduler runs every 15s and at slot start/end calls NCR `update_price` (real-time path). Optional `pre_schedule_prices` sends future-dated prices to NCR (effectiveDate); currently not invoked from the create-schedule API.
- **User flows:** Admin creates NCR store mapping → user onboarded via External Tool (connect store) → user creates/manages schedules → Price Scheduler updates NCR and ESL; optional NCR sync worker keeps NCR POS and ESL in sync from NCR-side changes.

This document is the single reference for NCR integration, onboarding, time-based pricing, and user flows in the ZKong-Demo / Hipoink ESL system.
