## Shopify Integration

### What Is This?

The Shopify integration connects **Shopify stores** to the Hipoink ESL (Electronic Shelf
Label) middleware. It listens for real-time product and inventory changes from Shopify via
webhooks, normalizes the data, and automatically updates your physical shelf labels.

Whenever a product is created, updated, or deleted in Shopify — including inventory
changes — that change flows through this integration and reaches your ESL labels without
manual work.

---

### What Does It Do?

| Capability | Description |
| --- | --- |
| **Webhook handling** | Receives real-time product and inventory events from Shopify |
| **Product sync** | Creates, updates, and deletes products in Supabase and queues them for ESL sync |
| **Multi-variant support** | Handles Shopify’s variant model — each variant becomes its own `NormalizedProduct` |
| **Inventory tracking** | Receives inventory level updates (currently an extension point) |
| **Signature verification** | Validates every webhook is genuinely from Shopify using HMAC SHA256 |
| **Multi-tenant support** | Safely handles multiple stores using the shop domain as the tenant identifier |

All Shopify flows still use the central `products → sync_queue → sync_worker` pipeline;
no code here talks to Hipoink directly.

---

### How Data Flows

#### Webhook-Driven Product Updates

The Shopify integration is entirely webhook-driven.

```text
Product created/updated/deleted in Shopify
        ↓
Shopify sends webhook POST to one of:
  /webhooks/shopify/products/create
  /webhooks/shopify/products/update
  /webhooks/shopify/products/delete
  /webhooks/shopify/inventory_levels/update
        ↓
System verifies HMAC SHA256 signature
(X-Shopify-Hmac-Sha256 header, signed with shopify_webhook_secret)
        ↓
Adapter resolves integration from registry and checks event is supported
        ↓
Payload parsed and validated with Pydantic models 
        ↓
ShopifyTransformer extracts all variants from the product 
(one NormalizedProduct per variant)
        ↓
Each variant validated and upserted in Supabase
(source_system="shopify", source_store_id=shop_domain)
        ↓
Valid products enqueued in sync_queue
        ↓
sync_worker picks up queued items and syncs to Hipoink ESL
```

**Supported webhook events (core ones):**

| Event | Shopify Trigger | Operation Queued |
| --- | --- | --- |
| `products/create` | New product added in Shopify | `create` |
| `products/update` | Product or variant edited in Shopify | `update` |
| `products/delete` | Product deleted in Shopify | `delete` |
| `inventory_levels/update` | Inventory quantity changed | Logged (extension point) |

---

### How Variants Are Handled

Shopify products can have multiple variants (e.g. a t-shirt with sizes S, M, L). This
integration treats **each variant as its own product** in Supabase:

```text
Shopify Product (1 product)
  ├── Variant: Small  → NormalizedProduct (source_variant_id = variant_id_1)
  ├── Variant: Medium → NormalizedProduct (source_variant_id = variant_id_2)
  └── Variant: Large  → NormalizedProduct (source_variant_id = variant_id_3)
```

Each variant gets its own row in the `products` table and its own entry in `sync_queue`,
allowing each ESL label to show the correct variant price independently.

---

### Authentication & Security

#### Webhook Signature Verification

Shopify signs every webhook using **HMAC SHA256** over the raw request body.

The system:

1. Extracts `X-Shopify-Hmac-Sha256` from the request headers.
2. Computes HMAC SHA256 over the raw body using `settings.shopify_webhook_secret`.
3. Compares using constant-time `hmac.compare_digest`.
4. Rejects any mismatch with `401 Unauthorized`.

> Any reverse proxy or middleware must preserve headers and the raw body exactly, or
> signature verification will fail.

#### Store Identification (Multi-Tenancy)

Each Shopify store is identified by its **shop domain** (e.g. `mystore.myshopify.com`).

- The shop domain is extracted from webhook headers (and/or payload).
- That domain is stored as `store_mappings.source_store_id`.
- Every Supabase query for Shopify filters by `source_system="shopify"` and that 
  `source_store_id`.

This guarantees data isolation between stores.

---

### Key Components

#### `adapter.py` — `ShopifyIntegrationAdapter`

Orchestrates webhook handling and product sync:

- `get_name()` → `"shopify"`.
- `verify_signature(...)`:
  - Validates HMAC signatures using the shop’s webhook secret.
- `extract_store_id(...)`:
  - Extracts shop domain from headers to determine `source_store_id`.
- `transform_product(...)`:
  - Converts a full Shopify product (with all variants) into a list of
    `NormalizedProduct` instances (one per variant).
- `transform_inventory(...)`:
  - Parses inventory-level updates into `NormalizedInventory` (currently an extension point).
- `_handle_product_create(...)`, `_handle_product_update(...)`, `_handle_product_delete(...)`:
  - Validate, normalize, upsert into Supabase, and enqueue appropriate `sync_queue`
    operations (`create`, `update`, `delete`).
- `_handle_inventory_update(...)`:
  - Validates and logs inventory events; can be extended to drive ESL updates.

#### `models.py`

Pydantic models that define and validate Shopify webhook payloads:

- `ShopifyProduct`, `ShopifyVariant`, `ShopifyImage`, etc.
- `ProductCreateWebhook`, `ProductUpdateWebhook`, `ProductDeleteWebhook`,
  `InventoryLevelsUpdateWebhook`.

These ensure incoming payloads are well-formed before the adapter processes them.

#### `ShopifyTransformer`

Central place for mapping raw Shopify data into `NormalizedProduct`:

- Extracts titles, barcodes, SKUs, pricing, images, and other fields.
- Enforces internal validation via `validate_normalized_product`.

---

### Webhook Endpoints

Core endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/webhooks/shopify/products/create` | Product created in Shopify |
| `POST` | `/webhooks/shopify/products/update` | Product updated in Shopify |
| `POST` | `/webhooks/shopify/products/delete` | Product deleted in Shopify |
| `POST` | `/webhooks/shopify/inventory_levels/update` | Inventory level changed |
| `POST` | `/webhooks/shopify/{event_type}` | Generic consolidated handler (routes above traffic through) |

All of these are ultimately routed through the generic webhooks router, which resolves
the `ShopifyIntegrationAdapter` from `integration_registry`.

---

### Product Data in Supabase

Each row created by this integration in `products` has:

| Field | Value |
| --- | --- |
| `source_system` | `"shopify"` |
| `source_id` | Shopify product ID |
| `source_variant_id` | Shopify variant ID |
| `source_store_id` | Shop domain (e.g. `mystore.myshopify.com`) |
| `status` | `"validated"` or `"pending"` based on validation result |
| `validation_errors` | Any validation issues found |

This keeps multi-variant and multi-tenant state clearly separated.

---

### Multi-Tenant Safety

The Shopify integration is multi-tenant by design:

- Every store has its own `StoreMapping` row keyed by `source_system="shopify"` and
  `source_store_id=<shop_domain>`.
- All Supabase queries for Shopify products include `source_store_id` filters.
- If a webhook arrives for a shop with no mapping, the system can respond with a clear
  error and/or log the mismatch for onboarding.

---

### Troubleshooting

| Problem | What To Check |
| --- | --- |
| Webhooks rejected with 401 | Ensure `settings.shopify_webhook_secret` matches the secret in Shopify Admin. Confirm proxies aren’t modifying headers/body. |
| `404` — store mapping not found | The shop sending the webhook has not been onboarded. Create a mapping via `/api/store-mappings/`. |
| Products not appearing on ESL | Check `sync_queue` for operations for the relevant `store_mapping_id`. Confirm the sync worker is running. |
| Specific variant missing | Review transformer validation; some variants may be filtered out due to validation errors. Check logs around that product ID. |

---

### Extending This Integration

#### Adding new webhook events

1. Add the event type to `ShopifyIntegrationAdapter.get_supported_events()`.
2. Extend `handle_webhook(...)` with a handler for the new event.
3. Add a new Pydantic model in `models.py` for the payload shape.
4. Use `ShopifyTransformer` to normalize new data fields.
5. Persist via `SupabaseService` and enqueue `sync_queue` operations as needed.

#### Extending inventory handling

`_handle_inventory_update(...)` currently logs inventory events. To activate
inventory-driven ESL updates:

1. Update the handler to modify the corresponding `Product` rows’ inventory fields.
2. Decide how inventory affects ESL labels (e.g. hide tags for out-of-stock items).
3. Enqueue `sync_queue` updates consistent with the existing product sync pipeline.

