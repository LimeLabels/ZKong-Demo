## Shopify Integration

### Overview

The Shopify integration connects Shopify product webhooks to the Hipoink ESL middleware.
It is responsible for:

- Receiving product and inventory webhooks from Shopify.
- Normalizing Shopify data into the internal product model.
- Writing records into Supabase (`products`, `sync_queue`) for downstream syncing to Hipoink.
- Enforcing multi‑tenant isolation by `source_store_id` (Shopify shop domain).

All business logic for Shopify lives behind the `ShopifyIntegrationAdapter` and operates
through Supabase and the background workers. Routers do not talk to Hipoink directly.

### Data flow

High‑level flow for Shopify product events:

1. **Webhook ingress**
   - Shopify sends webhooks to:
     - `POST /webhooks/shopify/products/create`
     - `POST /webhooks/shopify/products/update`
     - `POST /webhooks/shopify/products/delete`
     - `POST /webhooks/shopify/inventory_levels/update`
   - These legacy routes call the generic handler:
     - `POST /webhooks/shopify/{event_type}` (via the consolidated `webhooks.py`).

2. **Signature verification**
   - `X-Shopify-Hmac-Sha256` is extracted in `app/routers/webhooks.py`.
   - `ShopifyIntegrationAdapter.verify_signature(...)` computes an HMAC SHA256 using
     `settings.shopify_webhook_secret` and validates the header.
   - Requests with invalid or missing signatures are rejected with `401`.

3. **Adapter dispatch**
   - The generic webhook router resolves the adapter by name:
     - `integration_registry.get_adapter("shopify") → ShopifyIntegrationAdapter`.
   - It checks `ShopifyIntegrationAdapter.get_supported_events()` for the `event_type`.
   - It parses the JSON body, passes `payload` and `headers` into:
     - `ShopifyIntegrationAdapter.handle_webhook(event_type, request, headers, payload)`.

4. **Transformation and validation**
   - Product payloads (`products/create`, `products/update`, `products/delete`) are validated
     using Pydantic models in `app/integrations/shopify/models.py`:
     - `ProductCreateWebhook`
     - `ProductUpdateWebhook`
     - `ProductDeleteWebhook`
   - Variants are extracted via `ShopifyTransformer.extract_variants_from_product(...)` as
     `NormalizedProduct` instances, one per variant.

5. **Supabase persistence**
   - For each normalized variant, a `Product` row is created/updated through
     `SupabaseService.create_or_update_product(...)` with:
     - `source_system="shopify"`
     - `source_id` = Shopify product ID
     - `source_variant_id` = variant ID
     - `source_store_id` = Shopify shop domain (multi‑tenant isolation)
     - `status` and `validation_errors` populated from `validate_normalized_product`.

6. **Queueing for Hipoink sync**
   - For valid products, the adapter enqueues work via:
     - `SupabaseService.add_to_sync_queue(product_id, store_mapping_id, operation)`
   - Operations used:
     - `"create"` for new variants.
     - `"update"` for updates.
     - `"delete"` for deletions.
   - The background `SyncWorker` picks up these `sync_queue` entries and performs Hipoink API calls.

7. **Audit and logging**
   - All operations are logged using `structlog` with product identifiers and
     store context, enabling traceability across webhooks, Supabase and sync worker.

### Key components

- `adapter.py`
  - `ShopifyIntegrationAdapter(BaseIntegrationAdapter)`:
    - `get_name()` → `"shopify"`.
    - `verify_signature(payload, signature, headers)`:
      - HMAC SHA256 using `settings.shopify_webhook_secret`.
      - Compares computed HMAC against `X-Shopify-Hmac-Sha256` using `hmac.compare_digest`.
    - `extract_store_id(headers, payload)`:
      - Uses `ShopifyTransformer` to extract the shop domain from webhook headers.
    - `transform_product(raw_data)`:
      - Parses `ProductCreateWebhook`.
      - Returns a list of `NormalizedProduct` objects (one per variant). 
    - `transform_inventory(raw_data)`:
      - Parses `InventoryLevelsUpdateWebhook` and exposes a `NormalizedInventory` representation. 
    - `get_supported_events()`:
      - `["products/create", "products/update", "products/delete", "inventory_levels/update"]`.
    - `handle_webhook(event_type, request, headers, payload)`:
      - Routes to `_handle_product_create`, `_handle_product_update`,
        `_handle_product_delete`, `_handle_inventory_update`.
    - `_handle_product_create(...)`:
      - Validates payload (`ProductCreateWebhook`).
      - Resolves store mapping via `SupabaseService.get_store_mapping("shopify", store_domain)`.
      - Normalizes variants and creates/updates `Product` rows.
      - Enqueues valid products into `sync_queue` with `operation="create"`.
    - `_handle_product_update(...)`: 
      - Mirrors create path but uses `operation="update"`.
    - `_handle_product_delete(...)`:
      - Validates payload (`ProductDeleteWebhook`).
      - Looks up all `Product` rows for the Shopify product ID and store.
      - Enqueues deletions into `sync_queue` with `operation="delete"`.
    - `_handle_inventory_update(...)`:
      - Validates and logs inventory updates. Currently does not update pricing/stock;
        this is an extension point. 

- `models.py`
  - Pydantic models describing Shopify webhook payloads:
    - `ShopifyImage`: product image structure.
    - `ShopifyVariant`: variant fields (price, barcode, SKU, inventory, etc.).
    - `ShopifyProduct`: full product model.
    - `ProductCreateWebhook`, `ProductUpdateWebhook`, `ProductDeleteWebhook`:
      webhook payloads.
    - `InventoryLevelsUpdateWebhook`: payload for inventory updates.

- `transformer.py` (not shown here, but used extensively):
  - Responsible for converting `ShopifyProduct`/variants into `NormalizedProduct`.
  - Performs validation (`validate_normalized_product`) used by the adapter.

### Webhook and auth endpoints

- **Webhooks**
  - Legacy Shopify‑specific endpoints:
    - `POST /webhooks/shopify/products/create`
    - `POST /webhooks/shopify/products/update`
    - `POST /webhooks/shopify/products/delete`
    - `POST /webhooks/shopify/inventory_levels/update`
  - Generic handler:
    - `POST /webhooks/shopify/{event_type:path}`
  - All are defined in `app/routers/webhooks.py` and ultimately dispatched through
    `ShopifyIntegrationAdapter`.

- **OAuth and onboarding**
  - Shopify OAuth and API authentication are handled in `app/routers/shopify_auth.py`
    and the related service layer. This integration README focuses on webhook
    processing and product sync; refer to `shopify_auth` and the root `README.md`
    for full OAuth details.

### Extending the Shopify integration

When adding new Shopify behavior, follow these guidelines:

- **New webhook events**
  - Add the event to `get_supported_events()`.
  - Extend `handle_webhook(...)` with a new branch and implement a dedicated handler:
    - Validate using a new Pydantic model in `models.py`.
    - Translate into one or more `NormalizedProduct` or other normalized entities.
    - Use `SupabaseService` to persist and enqueue changes for `sync_worker`.

- **New product fields or validation rules**
  - Add fields to `ShopifyVariant` / `ShopifyProduct` models where appropriate.
  - Update `ShopifyTransformer` and its validation methods.
  - Keep all multi‑tenant constraints (`source_store_id`, `store_mapping_id`) intact.

- **Do not**
  - Do not call Hipoink directly from the adapter or routers.
  - Do not bypass `SupabaseService` with raw SQL.
  - Do not reuse global/shared API keys across merchants; always resolve per-store
    configuration via store mappings.

### Gotchas and troubleshooting

- **Signature mismatches**
  - Confirm `settings.shopify_webhook_secret` matches the secret configured in the
    Shopify admin for each webhook.
  - Ensure the deployed base URL and the Shopify webhook URLs are correct; any proxy
    or middleware must preserve the raw body and headers.

- **Missing store mappings**
  - If a webhook arrives for a shop that is not onboarded, the adapter will
    return `404` with a message instructing the user to create a store mapping
    via `/api/store-mappings/`.

- **Multi‑tenant isolation**
  - All queries filter by `source_store_id` = shop domain; be careful to preserve
    this when adding new helper methods or Supabase queries.

- **Inventory webhooks**
  - Currently treated as informational and only logged. If you need inventory‑driven
    price or availability updates, extend `_handle_inventory_update(...)` to update
    `Product` records and enqueue sync work in a way that is consistent with the
    existing pipeline.

