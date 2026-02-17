## Square Integration

### Overview

The Square integration connects Square Catalog, Inventory, and Order webhooks and APIs
to the Hipoink ESL middleware. It is responsible for:

- Verifying Square webhook signatures using HMAC SHA256 over `(notification_url + body)`.
- Normalizing Square catalog objects into the internal product model.
- Keeping products in Supabase in sync with Square Catalog (both via webhooks and full sync).
- Managing Square OAuth tokens (including proactive refresh).
- Enqueuing products into the `sync_queue` so workers can sync to Hipoink.

All Square logic is encapsulated in `SquareIntegrationAdapter` and associated services.
Routers and controllers do not talk to Square directly.

### Data flow

There are two primary data paths: **webhook‑driven updates** and **API‑driven full/initial sync**.

#### Webhook‑driven updates

1. **Webhook ingress**
   - Square sends webhooks (e.g. `catalog.version.updated`, `inventory.count.updated`,
     `order.created`, `order.updated`) to:
     - `POST /webhooks/square/{event_type}` (generic webhooks router).

2. **Signature verification**
   - `x-square-hmacsha256-signature` is extracted in `app/routers/webhooks.py`.
   - The router enforces that the header is present for Square and rejects requests if missing.
   - `SquareIntegrationAdapter.verify_signature(payload, signature, headers, request_url)`:
     - Computes HMAC SHA256 over `notification_url + payload` using `settings.square_webhook_secret`.
     - Uses the actual request URL (forcing HTTPS if Railway terminates SSL).
     - Compares using `hmac.compare_digest`.

3. **Adapter dispatch**
   - `integration_registry.get_adapter("square") → SquareIntegrationAdapter`.
   - `get_supported_events()` includes:
     - `"catalog.version.updated"`
     - `"inventory.count.updated"`
     - `"order.created"`
     - `"order.updated"`
   - The generic webhook router calls:
     - `SquareIntegrationAdapter.handle_webhook(event_type, request, headers, payload)`.

4. **Event handling**
   - `catalog.version.updated`:
     - Validates payload (`CatalogVersionUpdatedWebhook`).
     - Extracts `merchant_id` (location identifier) via `extract_store_id`.
     - Looks up a `StoreMapping` for `"square"` + `merchant_id`.
     - Ensures a valid OAuth access token via `_ensure_valid_token` and
       `SquareTokenRefreshService`.
     - Uses a **hybrid strategy**:
       - Optimized path: if the webhook includes a `catalog_object` (item or variation),
         fetches only that object from the Square Catalog API and updates just that item.
       - Fallback path: if optimization fails or object cannot be retrieved, performs a
         full catalog sync (see below) and reconciles deletes.
     - For each normalized variation:
       - Creates/updates `Product` with `source_system="square"` and `source_store_id=merchant_id`.
       - For changed and valid products, enqueues `sync_queue` entries for ESL updates.
       - Detects and logs unit‑cost changes by comparing `normalized_data` (`f2`, `f4`).
   - `inventory.count.updated`:
     - Validates with `InventoryCountUpdatedWebhook`.
     - Logs the event; currently does not alter products or queue items.
   - `order.created` / `order.updated`:
     - Logs high‑level order details (merchant, event_id, order_id).
     - Parses order payload for potential future use (e.g. popularity metrics).
     - Acknowledges the event so Square will not retry.

5. **Supabase persistence and queueing**
   - `SupabaseService.create_or_update_product(...)` is used to upsert products.
   - `SupabaseService.add_to_sync_queue(...)` is used to enqueue create/update/delete
     operations for Hipoink sync when products are valid and changed.
   - Deletions are handled via `_handle_catalog_delete(...)` and full sync reconciliation:
     - Products present in the DB but not returned by the Catalog API are scheduled
       for deletion via `sync_queue`.

#### API‑driven full / initial sync

The adapter also exposes an API for initial or ad‑hoc full sync of all catalog items:

- `sync_all_products_from_square(merchant_id, access_token, store_mapping_id, base_url)`:
  - Uses `httpx.AsyncClient` to call Square Catalog API `GET /v2/catalog/list?types=ITEM`
    with cursor‑based pagination.
  - Collects all items, logging pages and item counts.
  - Builds a cache of measurement units via `_fetch_measurement_units(...)`.
  - For each catalog item:
    - Builds a `SquareCatalogObject`.
    - Converts to `NormalizedProduct` variations via `SquareTransformer`.
    - Validates using `validate_normalized_product`.
    - Creates/updates `Product` rows with multi‑tenant isolation by `source_store_id=merchant_id`.
    - For valid products:
      - Checks for existing Hipoink mappings using
        `get_hipoink_product_by_product_id(product_id, store_mapping_id)`.
      - Enqueues `sync_queue` entries with `operation="create"` if not already synced.
  - Returns detailed statistics (`total_items`, `products_created`, `products_updated`,
    `queued_for_sync`, `errors`).

### Key components

- `adapter.py`
  - `SquareIntegrationAdapter(BaseIntegrationAdapter)`:
    - `get_name()` → `"square"`.
    - `verify_signature(payload, signature, headers, request_url=None)`:
      - Implements Square’s HMAC specification over `(notification_url + payload)`.
      - Auto‑corrects `http://` to `https://` to handle SSL termination.
    - `extract_store_id(headers, payload)`:
      - Returns a merchant or location ID via the `SquareTransformer`.
    - `transform_product(raw_data)`:
      - Extracts `catalog_object` from webhook payload and transforms it via
        `SquareTransformer.extract_variations_from_catalog_object(...)`.
    - `transform_inventory(raw_data)`:
      - Currently returns `None` (inventory sync is not primary focus).
    - `get_supported_events()`:
      - Lists all recognized webhook event types.
    - `handle_webhook(...)`:
      - Dispatches to `_handle_catalog_update`, `_handle_inventory_update`,
        and `_handle_order_event`.
    - `_ensure_valid_token(store_mapping)`:
      - Uses `SquareTokenRefreshService` to refresh expiring tokens based on
        metadata (`square_expires_at`), updating the store mapping before use.
    - `_get_square_credentials(store_mapping)`:
      - Resolves merchant ID and a valid access token from metadata, with logging
        and no global token fallback.
    - `sync_all_products_from_square(...)`:
      - Implements paginated full sync, measurement unit lookup, and
        `sync_queue` enqueueing.
    - `update_catalog_object_price(object_id, price, access_token)`:
      - Fetches the existing catalog variation object.
      - Updates `item_variation_data.price_money` and saves it via
        `POST /v2/catalog/object` with an idempotency key.

- `api_client.py`
  - The Square integration uses `httpx.AsyncClient` directly inside the adapter for REST calls;
    there is no separate Square API client module. Token management is delegated to
    `SquareTokenRefreshService`.

### Webhook and auth endpoints

- **Webhooks**
  - Handled generically via `app/routers/webhooks.py`:
    - `POST /webhooks/square/{event_type:path}`
  - The router:
    - Verifies `x-square-hmacsha256-signature` is present.
    - Passes `request.url` into `verify_signature` for correct HMAC.

- **OAuth and onboarding**
  - Square OAuth endpoints are defined in `app/routers/square_auth.py`:
    - `router` under `/auth` for user‑facing OAuth flows.
    - `api_router` under `/api/auth/square` for backend API usage.
  - Access tokens and expiry are stored in `store_mappings.metadata` and refreshed
    via `SquareTokenRefreshService`.

### Extending the Square integration

When extending Square behavior:

- **Add support for new webhook events**
  - Append the event type to `get_supported_events()`.
  - Add a new branch in `handle_webhook(...)` and implement a dedicated handler.
  - Validate with a Pydantic model (in `square/models.py`) before processing.
  - Ensure all Supabase queries filter by `source_store_id` (merchant/location ID).

- **Extend product/price sync**
  - Add fields to `SquareCatalogObject` and the transformer where needed.
  - Keep responsibility boundaries:
    - Adapter: orchestration, validation, and calls into Supabase.
    - Transformer: mapping from Square objects to `NormalizedProduct`.
    - Workers: Hipoink sync.

- **Be careful with tokens and multi‑tenancy**
  - Never fall back to a global Square access token.
  - Always derive the token from the `StoreMapping` that corresponds to the
    incoming merchant/location.

### Gotchas and troubleshooting

- **Signature validation failures**
  - Ensure `settings.square_webhook_secret` matches the Square Dashboard configuration.
  - Confirm the webhook URL in Square is the externally visible HTTPS URL
    (including path); mismatches will break signature verification.

- **Token expiry**
  - If you see `No access token found` or repeated `401` errors:
    - Check that the `store_mappings.metadata` for the Square store contains
      `square_access_token` and `square_expires_at`.
    - Verify the `token_refresh_scheduler` worker is running and completing without errors.

- **Unexpected deletes or missing products**
  - The fallback full sync path reconciles DB products against the current
    Square Catalog API result and may enqueue delete operations for items no
    longer present in Square.
  - When debugging, compare:
    - `get_products_by_system("square", merchant_id)` against
    - current items in the Square Catalog UI.

