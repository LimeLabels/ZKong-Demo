## NCR Integration

### Overview

The NCR integration connects the middleware to the **NCR PRO Catalog API** using
HMAC‑SHA512 authenticated REST calls. NCR does **not** provide webhooks in this
integration; all communication is API‑driven.

The integration is responsible for:

- Creating, updating, and logically deleting catalog items in NCR.
- Managing and scheduling prices in NCR via `item-prices` endpoints.
- Normalizing NCR catalog responses into the internal product model.
- Writing records into Supabase (`products`, `sync_queue`) for ESL sync.

All NCR‑specific behavior is implemented in `NCRIntegrationAdapter` and
`NCRAPIClient`. There are **no NCR webhooks**; router‑level webhook handling
for NCR is not used.

### Data flow

Because NCR is API‑only (in this integration), the primary data paths are:

1. **Create product in NCR and sync into Supabase.**
2. **Update price in NCR and reflect it in Supabase / ESL.**
3. **Logically delete product in NCR and queue deletion for ESL.**
4. **Pre‑schedule future prices in NCR based on local price adjustment schedules.**

Store‑specific NCR configuration (keys, organization, enterprise unit, defaults) is
stored in `store_mappings.metadata` and passed into adapter methods as
`store_mapping_config`.

#### Product creation

1. **Input**
   - A `NormalizedProduct` representing the item to be created.
   - A `store_mapping_config` dictionary containing NCR configuration, including:
     - `metadata.ncr_base_url`
     - `metadata.ncr_shared_key`
     - `metadata.ncr_secret_key`
     - `metadata.ncr_organization`
     - `metadata.ncr_enterprise_unit`
     - `metadata.department_id`
     - `metadata.category_id`
     - (and optionally `source_store_id`).

2. **API call**
   - `NCRIntegrationAdapter.create_product(normalized_product, store_mapping_config)`:
     - Instantiates `NCRAPIClient` with configuration from `metadata`.
     - Chooses an `actual_item_code` for NCR:
       - Prefer `normalized_product.barcode`.
       - Else `normalized_product.sku`.
       - Else `normalized_product.source_id`.
     - Calls `NCRAPIClient.create_product(...)` which:
       - Constructs an `ItemWriteData` with:
         - `itemId.itemCode`
         - `departmentId`
         - `merchandiseCategory`
         - `shortDescription` as `MultiLanguageTextData`.
         - `status` (e.g. `ACTIVE`).
         - `sku` and optional barcode mapping (via `packageIdentifiers`).
       - Sends a HMAC‑signed `PUT /items/{itemCode}` request.
       - Optionally creates an initial `item-prices` record if a price is provided.

3. **Normalization and persistence**
   - The adapter validates the `NormalizedProduct` using `validate_normalized_product`.
   - It constructs a `Product` row with:
     - `source_system="ncr"`.
     - `source_id=actual_item_code` (NCR item code).
     - `source_store_id` from:
       - `store_mapping_config["source_store_id"]`, or
       - `metadata.ncr_enterprise_unit` / `metadata.enterprise_unit_id`.
     - `raw_data` = NCR API response.
     - `normalized_data` = `normalized_product.to_dict()`.
   - The product is upserted via `SupabaseService.create_or_update_product(...)`.

4. **Queueing for ESL sync**
   - If the product is valid and changed, and `store_mapping_config["id"]` is set:
     - The adapter enqueues:
       - `SupabaseService.add_to_sync_queue(product_id, store_mapping_id, operation="create")`.
   - This allows the generic `SyncWorker` to create/refresh corresponding ESL products.

#### Price updates

1. **Input**
   - `item_code` of the NCR product.
   - New `price` (float).
   - `store_mapping_config` with NCR credentials and enterprise unit.

2. **API call**
   - `NCRIntegrationAdapter.update_price(item_code, price, store_mapping_config)`:
     - Configures `NCRAPIClient` with `ncr_base_url`, `shared_key`, `secret_key`,
       `organization`, `enterprise_unit`.
     - Calls `NCRAPIClient.update_price(...)`, which:
       - Builds a `SaveMultipleItemPricesRequest` containing a single `ItemPriceWriteData`.
       - `ItemPriceIdData` is set with:
         - `itemCode=item_code`.
         - `priceCode` (commonly equal to `item_code` for base prices).
         - `enterpriseUnitId`.
       - Sets effective date (current UTC if not provided), currency, status, and base price flags.
       - Sends a HMAC‑signed `PUT /item-prices` request.

3. **Database and ESL sync**
   - If a `store_mapping_id` is present:
     - The adapter looks up the existing `Product` via `get_product_by_source("ncr", item_code, source_store_id)`.
     - If found:
       - Updates `price` on the `Product`.
       - Ensures `normalized_data["price"]` is also updated (the sync worker uses normalized data first).
       - Upserts the product.
       - Enqueues an `update` operation in `sync_queue` to propagate price changes to ESL.

#### Product delete (logical)

1. **Input**
   - `item_code` of the NCR product.
   - `store_mapping_config` with NCR credentials and enterprise unit.

2. **API call**
   - `NCRIntegrationAdapter.delete_product(item_code, store_mapping_config)`:
     - Initializes `NCRAPIClient`.
     - Calls `NCRAPIClient.delete_product(...)`:
       - Builds a minimal `ItemWriteData` with:
         - `status="INACTIVE"`.
         - Required fields such as `departmentId`, `merchandiseCategory`, `shortDescription`.
       - Sends `PUT /items/{itemCode}` to mark the product inactive (soft delete).

3. **Database and ESL sync**
   - If `store_mapping_id` is present:
     - Finds products with `source_system="ncr"` and `source_id=item_code` using
       `get_products_by_source_id("ncr", item_code, source_store_id)`.
     - If none are found, performs a secondary search across NCR products by barcode or SKU.
     - For each product, enqueues `sync_queue` entries with `operation="delete"` so
       the ESL worker can remove or deactivate the associated ESL records.

#### Pre‑scheduling prices

For time‑based pricing, NCR supports pre‑scheduling price changes using `effectiveDate`
in the `item-prices` API.

- `NCRIntegrationAdapter.pre_schedule_prices(schedule, store_mapping_config)`:
  - Uses `calculate_all_price_events(schedule, store_timezone)` to derive all discrete
    price events for the schedule (start/end times, individual price windows).
  - Derives `store_timezone` from the `StoreMapping` metadata if available; falls back
    to UTC.
  - Converts each event into a record with:
    - `item_code`
    - `price`
    - `effective_date` (UTC ISO 8601 with milliseconds and `Z`)
    - `currency` (default `"USD"`).
  - Calls `NCRAPIClient.pre_schedule_prices(price_events)` which:
    - Batches events (e.g. 50 at a time).
    - Builds a `SaveMultipleItemPricesRequest` with multiple `ItemPriceWriteData` entries.
    - Sends HMAC‑signed `PUT /item-prices` calls for each batch.
    - Returns counts of scheduled vs failed events and per‑item results.

### Key components

- `adapter.py`
  - `NCRIntegrationAdapter(BaseIntegrationAdapter)`:
    - `get_name()` → `"ncr"`.
    - `verify_signature(payload, signature, headers)`:
      - Returns `True`. NCR does not use webhooks; HMAC‑SHA512 is handled at the API
        client level instead.
    - `extract_store_id(headers, payload)`:
      - Returns `None`; store identification is done via `store_mappings` and
        `enterprise_unit` metadata, not webhook headers.
    - `transform_product(raw_data)`:
      - Converts NCR catalog records into `NormalizedProduct`, extracting:
        - `itemCode` (or `itemId.itemCode`) as `source_id`.
        - `shortDescription` (multi‑language) as title.
        - `sku` and barcodes (from `packageIdentifiers`).
    - `transform_inventory(raw_data)`:
      - Currently returns `None`; inventory is not modeled in this adapter.
    - `get_supported_events()`:
      - Returns an empty list; there are no NCR webhooks.
    - `handle_webhook(...)`:
      - Raises `HTTPException(501)` with a clear message that NCR does not
        support webhooks; clients should use API operations.
    - `create_product(...)`, `update_price(...)`, `delete_product(...)`:
      - High‑level operations described in the data flow section, each:
        - Calls `NCRAPIClient` with HMAC‑signed requests.
        - Normalizes and persists results in Supabase.
        - Enqueues `sync_queue` operations for ESL.
    - `pre_schedule_prices(...)`:
      - Bridges between local price adjustment schedules and NCR’s pre‑scheduled
        price capability.

- `api_client.py`
  - `NCRAPIClient`:
    - Responsible for generating correct HMAC‑SHA512 signatures for NCR API.
    - `_generate_signature(...)`:
      - Builds nonce from date.
      - Concatenates method, URI (including query), content type, content MD5,
        and organization.
      - HMAC‑SHA512 with `secret_key + nonce`, base64‑encodes the result.
    - `_get_request_headers(method, url, body)`:
      - Sets NCR‑required headers:
        - `Content-Type`, `Accept`.
        - `nep-organization`, `nep-enterprise-unit` where configured.
        - `Date`, `Content-MD5`.
        - `Authorization: AccessKey {shared_key}:{signature}`.
    - `create_product(...)`:
      - HMAC‑signed `PUT /items/{itemCode}` with `ItemWriteData`.
      - Optionally chains to `update_price(...)` for initial pricing.
    - `update_price(...)`:
      - HMAC‑signed `PUT /item-prices` with `SaveMultipleItemPricesRequest`.
    - `list_items(...)`:
      - HMAC‑signed `GET /items` with pagination and optional `itemCodePattern`.
    - `delete_product(...)`:
      - HMAC‑signed `PUT /items/{itemCode}` with `status="INACTIVE"`.
    - `get_item_price(...)` and `get_item_prices_batch(...)`:
      - Read current prices for one or more items.
    - `pre_schedule_prices(price_events)`:
      - Batches and sends `PUT /item-prices` calls for multiple effective‑dated price
        records.

### Webhooks

NCR does **not** use webhooks in this integration:

- `NCRIntegrationAdapter.get_supported_events()` returns `[]`.
- `handle_webhook(...)` always returns a `501 Not Implemented` error indicating that
  NCR does not provide webhooks and that API endpoints must be used instead.

If you see requests hitting any hypothetical `/webhooks/ncr/...` endpoints, they are
likely misconfigured; all NCR operations should use the documented API routes instead.

### Extending the NCR integration

When extending NCR behavior:

- **Additional catalog fields**
  - Update `NCRTransformer` and `NormalizedProduct` attributes as needed.
  - Keep mapping logic in the transformer and orchestration in the adapter.

- **Inventory support**
  - If inventory endpoints are introduced, add mapping logic to `transform_inventory`
    and keep business rules in the adapter.

- **New operations**
  - Implement new high‑level methods on `NCRIntegrationAdapter` for new NCR API
    capabilities (e.g. promotions), and wrap corresponding methods on `NCRAPIClient`.
  - Keep all NCR authentication inside `NCRAPIClient` so HMAC logic remains in one place.

- **Multi‑tenant isolation**
  - Always resolve enterprise unit and NCR credentials from per‑store `store_mappings`.
  - Never reuse shared keys or secrets across tenants beyond what NCR itself requires.

### Gotchas and troubleshooting

- **Signature or authentication errors**
  - Verify `ncr_shared_key`, `ncr_secret_key`, `ncr_organization`, and
    `ncr_enterprise_unit` are correctly set in `store_mappings.metadata`.
  - Ensure system clocks are reasonably synchronized; HMAC signatures include a
    timestamp/nounce that depends on the current time.

- **Unexpected product identifiers**
  - The adapter may derive `item_code` from barcode or SKU if the caller does not
    provide an explicit item code. Be consistent in how you identify items to avoid
    ambiguity when performing updates or deletes later.

- **Price discrepancies**
  - `update_price(...)` updates both the remote NCR price and the local product’s
    `price` and `normalized_data["price"]`. If ESL prices do not match NCR:
    - Verify the `sync_queue` has `update` entries for the relevant products.
    - Confirm the `SyncWorker` is running and successfully processing NCR products
      for the corresponding `store_mapping_id`.

