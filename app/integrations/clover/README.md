## Clover Integration

### Overview

The Clover integration connects Clover inventory signals (webhooks and polling) to the
Hipoink ESL middleware. It is responsible for:

- Verifying Clover webhooks using a static `X-Clover-Auth` code (no body HMAC).
- Handling Clover webhook notifications for item create/update/delete.
- Polling the Clover API for incremental changes and ghost‑item cleanup.
- Updating Supabase `products` and `sync_queue` in a multi‑tenant‑safe way.
- Updating prices in Clover BOS when time‑based pricing is applied.

All Clover-specific logic is encapsulated in `CloverIntegrationAdapter` and
`CloverAPIClient`, plus supporting token‑refresh and encryption utilities.

### Data flow

There are three primary data paths for Clover:

1. **Webhook‑driven inventory events (near‑real time).**
2. **Polling‑based incremental sync (regular worker job).**
3. **Initial full sync and BOS price updates (via API calls).**

#### Webhook‑driven events

1. **Webhook ingress**
   - Clover sends webhook POST requests to:
     - `POST /webhooks/clover/{event_type}` (generic webhooks router).

2. **Verification phase**
   - Clover performs a one‑time verification POST that contains only
     `{"verificationCode": "..."}` and no `merchants` field.
   - `CloverIntegrationAdapter.handle_webhook(...)` detects this case and responds
     with `{"verificationCode": ...}` so the Clover Dashboard can validate the URL.
   - For real events, the router:
     - Reads `X-Clover-Auth` and passes it as `signature` into
       `verify_signature(payload, signature, headers)`.
     - The adapter compares `signature` against `settings.clover_webhook_auth_code`
       using `secrets.compare_digest`.

3. **Adapter dispatch and validation**
   - The generic webhooks router resolves the adapter:
     - `integration_registry.get_adapter("clover") → CloverIntegrationAdapter`.
   - `get_supported_events()` currently returns `["inventory"]`.
   - `handle_webhook(event_type, request, headers, payload)`:
     - Validates payload structure using `CloverWebhookPayload`.
     - Iterates over all merchants in the payload.

4. **Per‑merchant processing**
   - For each `merchant_id`:
     - Resolves `StoreMapping` via `SupabaseService.get_store_mapping("clover", merchant_id)`.
     - Decrypts OAuth tokens using `decrypt_tokens_from_storage(metadata)`.
     - Ensures a valid access token is present.
     - For each update record:
       - If `type == "DELETE"`:
         - Looks up products in Supabase with `source_system="clover"`,
           `source_id` matching the item ID, and `source_store_id=merchant_id`.
         - Queues delete operations in `sync_queue` for ESL removal.
       - For create/update:
         - Calls `CloverAPIClient.get_item(merchant_id, item_id)` to fetch full item data.
         - Uses `CloverTransformer.transform_item(...)` to obtain a `NormalizedProduct`.
         - Validates with `validate_normalized_product`.
         - Upserts a `Product` row with:
           - `source_system="clover"`
           - `source_id` and `source_variant_id` from the normalized product
           - `source_store_id` = `merchant_id`
         - If valid, and either changed or not yet synced to Hipoink, enqueues
           `sync_queue` entries with `operation="create"` or `operation="update"`.

5. **Slack alerting**
   - Errors per merchant are captured and, where possible, sent to Slack via
     `slack_service.send_webhook_error_alert(integration="clover", ...)`.

#### Polling‑based incremental sync (worker)

The Clover sync worker uses a polling strategy to ensure eventual consistency and to
clean up “ghost” items (present in our DB but removed in Clover).

- `CloverIntegrationAdapter.sync_products_via_polling(store_mapping, skip_token_refresh=False)`:
  - Reads sync state from `store_mapping.metadata`:
    - `clover_last_sync_time` (milliseconds).
    - `clover_poll_count`.
  - Determines an access token:
    - If `skip_token_refresh` is `False`, uses `_ensure_valid_token(store_mapping)` which
      decrypts metadata, checks expiry via `CloverTokenRefreshService` and refreshes if
      necessary.
    - Otherwise, uses the current decrypted token “as is” (used right after OAuth to
      avoid race conditions with the worker).
  - Uses `CloverAPIClient.list_items_modified_since(merchant_id, modified_since)` to fetch
    items changed since `clover_last_sync_time`, with pagination and a short delay between
    pages to avoid rate limits.
  - For each item:
    - If `deleted` or `hidden` → `_handle_item_deletion(...)` and queue delete operations.
    - Else:
      - Normalizes to `NormalizedProduct`, validates, and upserts `Product` in Supabase.
      - If valid:
        - Checks for existing Hipoink product.
        - Enqueues `sync_queue` operations (`create` or `update`) where appropriate.
  - Periodically performs ghost‑item cleanup:
    - Every N polls (default every 10) or after a configurable number of hours:
      - Calls `CloverAPIClient.list_all_item_ids(merchant_id)` to get all active IDs.
      - Compares against our `products` for `source_system="clover"` and same `source_store_id`.
      - Any IDs only present in our DB are treated as ghosts:
        - `_mark_product_deleted(...)` sets product status to `"deleted"` and queues ESL deletions.
  - Updates sync metadata via `SupabaseService.update_store_mapping_metadata(...)` for:
    - `clover_last_sync_time`
    - `clover_poll_count`
    - Optionally `clover_last_cleanup_time`.

#### Initial full sync and price updates

- `sync_all_products_from_clover(merchant_id, access_token, store_mapping_id, base_url=None)`:
  - Fetches all items using `CloverAPIClient.list_items(...)` with `limit/offset` pagination
    and small delays between pages to respect rate limits.
  - For each item:
    - Normalizes and validates.
    - Upserts `Product` with `source_system="clover"` and `source_store_id=merchant_id`.
    - If valid:
      - Checks for existing Hipoink mapping.
      - Enqueues `sync_queue` entries for `create` or `update`.
  - Returns counts for total items, created, updated, queued, and errors.

- `update_item_price(store_mapping, item_id, price_dollars, existing_product=None)`:
  - Ensures a valid, decrypted access token via `_ensure_valid_token(...)`.
  - Converts dollars to integer cents with `round(...)`.
  - Uses `CloverAPIClient.update_item(merchant_id, item_id, price_cents)`:
    - Sends `POST /v3/merchants/{mId}/items/{itemId}` with `{ "price": price_cents }`.
  - If `existing_product` is provided:
    - Updates its price in Supabase via `create_or_update_product` so
      the local DB mirrors BOS state.

### Key components

- `adapter.py`
  - `CloverIntegrationAdapter(BaseIntegrationAdapter)`:
    - `get_name()` → `"clover"`.
    - `verify_signature(payload, signature, headers)`:
      - Constant‑time compare between `signature` and `settings.clover_webhook_auth_code`.
      - No body HMAC; Clover uses a static auth code.
    - `extract_store_id(headers, payload)`:
      - Reads the first merchant ID from `payload["merchants"]`, if present.
    - `transform_product(raw_data)`:
      - Uses `CloverTransformer.transform_item(...)` to produce one `NormalizedProduct`.
    - `transform_inventory(...)`:
      - Currently not implemented (returns `None`).
    - `validate_normalized_product(product)`:
      - Delegates to `CloverTransformer.validate_normalized_product`.
    - `get_supported_events()`:
      - Currently `["inventory"]`.
    - `_ensure_valid_token(store_mapping)`:
      - Decrypts stored tokens, checks expiry using `CloverTokenRefreshService`, and refreshes if
        expiring soon, preferring the refreshed mapping’s tokens.
    - `update_item_price(...)`:
      - Calls `CloverAPIClient.update_item(...)` and updates local DB price if successful.
    - `sync_products_via_polling(...)`:
      - Implements incremental polling and ghost‑item cleanup logic as described above.
    - `_handle_item_deletion(...)`, `_mark_product_deleted(...)`, `_cleanup_ghost_items(...)`:
      - Mark products deleted and enqueue ESL delete operations.
    - `handle_webhook(...)`:
      - Handles verification requests and normal webhook payloads per merchant as
        described in the data flow.
    - `sync_all_products_from_clover(...)`:
      - Initial/full sync via `CloverAPIClient.list_items(...)`.

- `api_client.py`
  - `CloverAPIClient`:
    - Uses `httpx.AsyncClient` with a configurable base URL determined by
      `settings.clover_environment` (sandbox vs production) unless overridden.
    - Authenticates using bearer tokens (OAuth access tokens) provided by the adapter.
    - `list_items(merchant_id)`:
      - Limit/offset pagination with small delays between requests.
    - `get_item(merchant_id, item_id)`:
      - Fetches a specific item by ID.
    - `update_item(...)`:
      - Sends a POST request to update an item’s price and potentially other fields.
    - `list_items_modified_since(...)`:
      - Fetches items changed since a given timestamp for incremental polling.
    - `list_all_item_ids(merchant_id)`:
      - Returns only IDs for ghost‑item detection.
    - Raises `CloverAPIError` with status and body on HTTP failures.

### Webhook and auth endpoints

- **Webhooks**
  - `POST /webhooks/clover/{event_type:path}` (generic webhooks router).
  - The router:
    - Passes raw body and `X-Clover-Auth` to the adapter for verification.
    - Allows the verification POST (with only `verificationCode`) through without
      requiring `X-Clover-Auth`, as required by Clover’s setup flow.

- **OAuth and tokens**
  - Clover OAuth flows and token storage are handled in `app/routers/clover_auth.py`
    and related services.
  - Access tokens are encrypted in store mapping metadata; `decrypt_tokens_from_storage`
    is used by the adapter before calling `CloverAPIClient`.

### Extending the Clover integration

When adding new Clover behavior:

- **Support additional webhook types**
  - Add entries to `get_supported_events()` and extend `handle_webhook(...)` accordingly.
  - Update or extend `CloverWebhookPayload` to validate new payload shapes.

- **Extend product mapping**
  - Update `CloverTransformer` to include additional fields (e.g. categories, tags)
    in `NormalizedProduct`.
  - Ensure validation remains strict enough to avoid sending incomplete data to ESL.

- **Inventory and pricing**
  - Inventory is currently not fully modeled; if you introduce inventory‑driven behavior,
    keep mapping and business logic in the adapter and transformer, and continue to use
    `sync_queue` to communicate with the Hipoink sync worker.

- **Multi‑tenant safety**
  - Always filter Supabase queries by `source_store_id = merchant_id` to avoid
    cross‑merchant leakage.
  - Avoid sharing Clover tokens across merchants; all access tokens come from the
    specific store mapping for the merchant.

### Gotchas and troubleshooting

- **Missing or invalid `X-Clover-Auth`**
  - If webhooks are rejected with `401`:
    - Confirm `settings.clover_webhook_auth_code` matches the value configured in
      the Clover Dashboard.
    - Ensure the value is not accidentally encrypted; the adapter expects plaintext.

- **Encrypted access tokens**
  - If the worker logs indicate tokens starting with a ciphertext prefix (for example
    `"gAAAAA"`), it is likely that `CLOVER_TOKEN_ENCRYPTION_KEY` or related configuration
    is missing. The adapter explicitly logs this case and refuses to make API calls.

- **Ghost items not cleaned up**
  - Ghost cleanup runs periodically based on `clover_poll_count` and
    `clover_last_cleanup_time`. If you never see ghost cleanup messages:
    - Confirm the Clover sync worker is running.
    - Check store mapping metadata to ensure `clover_poll_count` is incrementing.

