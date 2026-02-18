## NCR Integration

### What Is This?

The NCR integration connects the middleware to the **NCR PRO Catalog API** — a retail
catalog and pricing system used in enterprise point-of-sale environments. Unlike some
other integrations, NCR does **not** send webhooks in this system. All communication is
API-driven: the middleware **polls NCR** to discover products created directly in NCR POS, and also **pushes** data to NCR when creating/updating products or prices.

The integration handles:
- **Polling NCR** to discover products created directly in NCR POS and sync them to ESL labels (primary sync mechanism)
- Creating, updating, and logically deleting products in NCR
- Managing prices (including future-dated scheduled prices)
- Keeping Supabase and ESL labels in sync with NCR's catalog

---

### What Does It Do?

| Capability | Description |
| --- | --- |
| **Product discovery (polling)** |  **Primary sync mechanism** — Polls NCR API to discover products created directly in NCR POS and syncs them to ESL labels |
| **Create products** | Creates new catalog items in NCR and saves them to Supabase |
| **Update prices** | Updates item prices in NCR and propagates changes to ESL labels |
| **Delete products** | Logically deletes (marks INACTIVE) items in NCR and queues ESL removal |
| **Pre-schedule prices** | Sends future-dated price changes to NCR ahead of time for time-based pricing |
| **Multi-tenant support** | Each store has its own NCR credentials stored in its store mapping |

> **No webhooks.** NCR does not send real-time notifications in this integration. All
> operations are explicit API calls; any `/webhooks/ncr/...` traffic is misconfigured.

---

### How Data Flows

#### 1. Creating a Product

```text
NormalizedProduct received
        ↓
NCRIntegrationAdapter.create_product() called
        ↓
Determines item code (barcode → SKU → source_id, in priority order)
        ↓
Calls NCRAPIClient.create_product()
Sends HMAC-signed PUT /items/{itemCode} to NCR
(optionally creates an initial item-prices record if price provided)
        ↓
Validates and upserts Product in Supabase
(source_system="ncr", source_id=item_code, source_store_id=enterprise_unit_id)
        ↓
If product is valid and changed:
  → Enqueues sync_queue entry (operation="create")
  → sync_worker picks it up and creates the ESL label
```

---

#### 2. Updating a Price

```text
Price update triggered (e.g. by time-based pricing)
        ↓
NCRIntegrationAdapter.update_price(item_code, price, store_mapping_config)
        ↓
NCRAPIClient.update_price() called
Sends HMAC-signed PUT /item-prices to NCR
(price expressed in correct currency and effective immediately or at a given time)
        ↓
Looks up existing Product in Supabase
Updates both product.price AND normalized_data["price"]
(sync worker uses normalized_data first)
        ↓
Enqueues sync_queue update → ESL label reflects new price
```

---

#### 3. Deleting a Product

NCR uses **logical (soft) deletes** — items are not physically removed, they are marked
`INACTIVE`.

```text
Delete triggered
        ↓
NCRIntegrationAdapter.delete_product(item_code, store_mapping_config)
        ↓
Sends HMAC-signed PUT /items/{itemCode} with status="INACTIVE" to NCR
        ↓
Looks up Product in Supabase by source_id
(falls back to barcode/SKU search if needed)
        ↓
Enqueues sync_queue entries with operation="delete"
        ↓
sync_worker removes or deactivates the corresponding ESL label
```

---

#### 4. Pre-Scheduling Prices (Time-Based Pricing)

NCR natively supports **future-dated price changes** using `effectiveDate` in the
`item-prices` API. This lets you send all upcoming price events to NCR in advance instead
of pushing changes at the exact moment.

```text
Time-based pricing schedule created or updated
        ↓
NCRIntegrationAdapter.pre_schedule_prices(schedule, store_mapping_config)
        ↓
Derives store timezone from StoreMapping metadata (defaults to UTC)
        ↓
calculate_all_price_events() generates every discrete price event
(start times, end times, each window for the full schedule)
        ↓
Each event converted to:
  { item_code, price, effective_date (UTC ISO 8601), currency }
        ↓
NCRAPIClient.pre_schedule_prices() batches events (e.g. 50 at a time)
Sends HMAC-signed PUT /item-prices calls for each batch
        ↓
Returns: count of scheduled vs failed events, per-item results
```

NCR then applies those prices at the correct times without the middleware needing to
trigger each change in real time.

When NCR applies a scheduled price change, the NCR sync worker detects the price difference on its next poll, updates the Product price in Supabase, and enqueues a `sync_queue` entry with `operation="update"`. The SyncWorker then pushes the new price to the ESL shelf labels — meaning both the NCR BOS and the physical shelf labels always reflect the same price at the right time.

---

#### 5. Product Discovery via Polling (NCR → ESL)

> ⚠️ **Temporarily disabled** — The NCR sync worker is currently commented out in `app/workers/__main__.py` while NCR API rate limits are being validated for production load. Re-enabling it is the intended production state — see instructions below.

This is the **primary mechanism** for syncing products from NCR to ESL labels when products are created or updated directly in NCR POS. Since NCR doesn't send webhooks, the system polls NCR on a regular schedule to discover changes.

```text
NCRSyncWorker runs every 60 seconds
        ↓
Fetches all active NCR store mappings from Supabase
        ↓
For each store mapping:
  Builds NCRAPIClient using credentials from store metadata
  Calls GET /items with pagination (200 items per page)
        ↓
Fetches ALL items from NCR catalog
        ↓
For each NCR item:
  Compares with existing Product rows in Supabase
  Fetches current effective price from NCR (respects scheduled prices)
        ↓
If new product:
  Transforms to NormalizedProduct
  Creates Product row in Supabase
  Enqueues sync_queue entry (operation="create")
        ↓
If existing product changed:
  (title, barcode, SKU, or price difference > $0.01)
  Updates Product row in Supabase
  Enqueues sync_queue entry (operation="update")
        ↓
SyncWorker picks up queue entries → pushes to ESL labels
```

**Key behaviors:**

- **Price change detection**: The poller detects both manual price changes and scheduled prices that became active (by comparing current NCR price with stored price)
- **Full catalog scan**: Every poll fetches the entire catalog, ensuring nothing is missed
- **Multi-tenant isolation**: All queries filter by `source_store_id` to prevent cross-store data leaks
- **Pagination**: Uses NCR's pagination API (`pageNumber`/`pageSize`) to handle large catalogs efficiently

**How to re-enable:**

1. Uncomment `run_ncr_sync_worker()` in `app/workers/__main__.py`
2. Verify NCR API rate limits can handle polling every 60 seconds
3. Confirm Supabase and ESL capacity for the resulting sync volume

For more details on the worker implementation, see `app/workers/README.md`.

---

### Authentication — HMAC-SHA512

NCR uses **HMAC-SHA512** for all API authentication. Every request is signed; there are
no OAuth tokens to manage.

The signature flow (implemented in `NCRAPIClient._generate_signature`) is:

1. Build a **nonce** from the current date.
2. Concatenate:
   - HTTP method
   - Full URI (including query)
   - `Content-Type`
   - `Content-MD5`
   - `nep-organization`
3. Compute HMAC-SHA512 using `secret_key + nonce`.
4. Base64-encode the result.
5. Send header:

   ```http
   Authorization: AccessKey {shared_key}:{signature}
   ```

Per-store NCR configuration is stored in `store_mappings.metadata`:

| Field | Description |
| --- | --- |
| `ncr_base_url` | NCR API base URL |
| `ncr_shared_key` | Public key for the Authorization header |
| `ncr_secret_key` | Private key used for HMAC signing |
| `ncr_organization` | NCR organization identifier |
| `ncr_enterprise_unit` | Enterprise unit / store identifier |
| `department_id` | Default department for new items |
| `category_id` | Default merchandise category for new items |

All of these are resolved per `StoreMapping`; there is no global/shared NCR credential.

---

### Key Components

#### `adapter.py` — `NCRIntegrationAdapter`

High-level orchestration for NCR:

- `get_name()` → `"ncr"`.
- `transform_product(raw_data)`:
  - Converts NCR catalog records into `NormalizedProduct`, extracting:
    - `itemCode` as `source_id`.
    - Descriptions, SKU, barcodes.
- `create_product(...)`:
  - Builds `ItemWriteData` and calls `NCRAPIClient.create_product(...)`.
  - Upserts `Product` into Supabase and enqueues `sync_queue` entries when needed.
- `update_price(...)`:
  - Calls `NCRAPIClient.update_price(...)`.
  - Updates both `product.price` and `normalized_data["price"]` and enqueues updates.
- `delete_product(...)`:
  - Soft-deletes item in NCR by setting `status="INACTIVE"`.
  - Queues ESL deletions based on Supabase products matching `source_id`.
- `pre_schedule_prices(...)`:
  - Bridges `price_adjustments` schedules into NCR `item-prices` with future
    `effectiveDate`s.

NCR has **no webhooks** in this integration:

- `get_supported_events()` returns `[]`.
- `handle_webhook(...)` always responds with `501 Not Implemented` indicating that NCR
  should use API endpoints instead.

#### `api_client.py` — `NCRAPIClient`

Handles all direct HTTP calls to NCR, including signing and header construction:

- `_generate_signature(...)`:
  - Builds the HMAC-SHA512 signature as described above.
- `_get_request_headers(method, url, body)`:
  - Sets:
    - `Content-Type`, `Accept`
    - `nep-organization`, `nep-enterprise-unit`
    - `Date`, `Content-MD5`
    - `Authorization: AccessKey {shared_key}:{signature}`

Key public methods:

- `create_product(...)`:
  - HMAC-signed `PUT /items/{itemCode}` with `ItemWriteData`.
  - Optionally chains to `update_price(...)` for initial price.
- `update_price(...)`:
  - HMAC-signed `PUT /item-prices` with `SaveMultipleItemPricesRequest`.
- `delete_product(...)`:
  - HMAC-signed `PUT /items/{itemCode}` with `status="INACTIVE"`.
- `list_items(...)`:
  - Signed `GET /items` with pagination and optional filters.
- `get_item_price(...)` / `get_item_prices_batch(...)`:
  - Read current prices for one or more items.
- `pre_schedule_prices(price_events)`:
  - Batches and sends `PUT /item-prices` calls for future-dated prices.

---

### Webhooks

NCR does **not** use webhooks in this integration:

- `NCRIntegrationAdapter.get_supported_events()` returns an empty list.
- `handle_webhook(...)` always returns a `501 Not Implemented` response explaining that
  NCR does not provide webhooks and API operations must be used instead.

Any traffic to `/webhooks/ncr/...` is a configuration error.

---

### Multi-Tenant Safety

Each store has its own NCR credentials:

- `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, and `ncr_enterprise_unit` live
  in that store’s `store_mappings.metadata`.
- All Supabase queries go through `SupabaseService` and filter by `source_store_id`.
- There are no shared or global NCR tokens/keys beyond what NCR itself requires.

---

### Troubleshooting

| Problem | What To Check |
| --- | --- |
| Signature / auth errors | Verify `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, and `ncr_enterprise_unit` in store metadata. Ensure system clocks are reasonably synchronized (signatures depend on time). |
| Wrong or inconsistent item codes | The adapter may derive `item_code` from barcode → SKU → `source_id`. Be consistent in how you identify items to avoid ambiguity when updating or deleting. |
| ESL prices not matching NCR | Confirm `update_price(...)` is being called, and that `sync_queue` has `update` entries. Ensure the sync worker is running for that `store_mapping_id`. If using the poller, verify it's enabled and running — it detects price changes automatically. |
| Pre-scheduled prices not applying | Check timezones in `store_mappings.metadata`. All `effectiveDate` values are converted to UTC; a wrong timezone can shift prices by hours. |
| Products created in NCR not appearing on ESL | The NCR sync worker must be enabled and running. Check `app/workers/__main__.py` — `run_ncr_sync_worker()` should be uncommented. Verify the worker logs show successful polling cycles. |

---

### Extending This Integration

#### Adding new catalog fields

1. Update `NCRTransformer` and `NormalizedProduct` to include the new fields.
2. Keep mapping logic in the transformer and orchestration logic in the adapter.

#### Adding new NCR API operations

1. Add a new method to `NCRAPIClient` (all HMAC logic stays inside this client).
2. Add a high-level method to `NCRIntegrationAdapter` that:
   - Accepts normalized data,
   - Calls `NCRAPIClient`,
   - Updates Supabase via `SupabaseService`,
   - Enqueues `sync_queue` entries as needed.

#### Multi-tenant isolation

- Always resolve NCR configuration from the current store’s `StoreMapping`.
- Never hardcode or reuse credentials across tenants.

