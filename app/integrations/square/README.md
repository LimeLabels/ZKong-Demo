## Square Integration

### What Is This?

The Square integration connects **Square point-of-sale systems** to the Hipoink ESL
(Electronic Shelf Label) middleware. It listens for real-time catalog and inventory
changes from Square via webhooks, and also supports full catalog syncs on demand.

Whenever a product is created or updated in Square, the change flows automatically
through the system and updates the physical shelf labels in your store.

---

### What Does It Do?

| Capability | Description |
| --- | --- |
| **Webhook handling** | Receives real-time catalog, inventory, and order events from Square |
| **Full catalog sync** | Pulls all products from Square for initial setup or reconciliation |
| **Price updates** | Updates catalog variation prices directly in Square |
| **Delete reconciliation** | Detects and queues removal of products no longer present in Square |
| **OAuth token management** | Manages and proactively refreshes Square access tokens |
| **Multi-tenant support** | Safely handles multiple merchants without data leaking between them |

All Square flows still go through Supabase (`products`, `sync_queue`) and the background
sync workers; routers and adapters never talk to Hipoink directly.

---

### How Data Flows

#### 1. Webhook-Driven Updates (Real-Time)

This is the primary path for keeping shelf labels in sync with Square.

```text
Square detects a catalog/inventory/order change
        ↓
Sends webhook POST to: /webhooks/square/{event_type}
        ↓
System verifies HMAC SHA256 signature
(computed over notification_url + raw body using square_webhook_secret)
        ↓
Adapter dispatches to the correct handler based on event type
        ↓
Handler processes the event (see event types below)
        ↓
Valid products upserted in Supabase
        ↓
sync_queue entries created → sync_worker updates ESL labels
```

**Supported webhook events (examples):**

| Event | What Triggers It | What The System Does |
| --- | --- | --- |
| `catalog.version.updated` | Any product change in Square | Fetches and syncs updated catalog item(s) |
| `inventory.count.updated` | Inventory quantity changes | Logs the event (extension point) |
| `order.created` | New order placed | Logs order details for future use |
| `order.updated` | Existing order modified | Logs order details for future use |

##### Catalog Update — Hybrid Strategy

For `catalog.version.updated`, the system uses a smart two-path approach:

```text
Webhook received for catalog.version.updated
        ↓
Does the webhook include a specific catalog_object?
        ↓
  YES → Optimized path:
    Fetch only the specific changed item from Square API
    Normalize and sync just that item
        ↓
  NO (or fetch fails) → Fallback path:
    Perform a full catalog sync
    Reconcile deletes (items in DB but not in Square)
```

This keeps single-item changes fast while ensuring a correct, reconciled catalog when
Square sends aggregate updates or when the optimized path fails.

---

#### 2. Full Catalog Sync (Initial Setup or Ad-Hoc)

Used when connecting a new Square store or when a full reconciliation is needed.

```text
sync_all_products_from_square() triggered
        ↓
Calls Square Catalog API: GET /v2/catalog/list?types=ITEM
Paginated with cursor-based pagination
        ↓
Builds a cache of measurement units for accurate product normalization
        ↓
For each catalog item:
  → Build SquareCatalogObject
  → Convert to NormalizedProduct variations (one per variation)
  → Validate each variation
  → Upsert Product in Supabase (filtered by source_store_id=merchant_id)
  → If valid and not yet synced to Hipoink → queue for ESL sync
        ↓
Returns: total_items, products_created, products_updated, queued_for_sync, errors
```

The initial full sync is typically triggered right after OAuth completion (via a
background task), so merchants see products appear quickly without blocking the OAuth
callback response.

---

#### 3. Price Updates

When time-based pricing fires for a Square catalog variation:

```text
update_catalog_object_price(object_id, price, access_token) called
        ↓
Fetches the existing catalog variation object from Square
        ↓
Updates item_variation_data.price_money with the new amount
        ↓
Saves it via POST /v2/catalog/object with an idempotency key
(idempotency key prevents duplicate updates if the request is retried)
        ↓
Local Product row updated in Supabase + sync_queue update → ESL label changes price
```

---

### Authentication & Security

#### Webhook Signature Verification

Square uses **HMAC SHA256** over the combination of the full notification URL and the raw
request body.

The system:

1. Extracts `x-square-hmacsha256-signature` from request headers.
2. Computes HMAC SHA256 over `notification_url + raw_body` using
   `settings.square_webhook_secret`.
3. Normalizes `http://` to `https://` in URLs to account for SSL termination (e.g. on
   Railway).
4. Compares signatures using `hmac.compare_digest`.
5. Rejects mismatches with `401 Unauthorized`.

> The webhook URL used for HMAC must **exactly** match the URL configured in the Square
> Dashboard, including protocol (`https`), host, and path.

#### OAuth Access Tokens

Square uses OAuth 2.0 for API access.

Your flow (`square_auth.py`):

- Initiates OAuth via `/auth/square`, encoding:
  - `hipoink_store_code`, `store_name`, `timezone` into a base64 JSON `state`.
- Square redirects back to `/auth/square/callback` with:
  - `code` (authorization code)
  - `state` (original onboarding data)
- Backend exchanges `code` with Square’s `/oauth2/token` endpoint, receiving:
  - `access_token`, `refresh_token`, `merchant_id`, `expires_at`, etc.
- Fetches merchant locations via `GET /v2/locations`.
- Stores everything in a `StoreMapping`:
  - `source_system = "square"`
  - `source_store_id = merchant_id`
  - `metadata` includes tokens, locations, timezone, and install timestamps.
- Schedules a background **initial product sync** using
  `SquareIntegrationAdapter.sync_all_products_from_square(...)`.

Tokens are later refreshed by a dedicated worker (`token_refresh_scheduler`) before they
expire, and are always resolved per merchant.

---

### Key Components

#### `adapter.py` — `SquareIntegrationAdapter`

Orchestrates Square webhook handling and catalog sync:

- `get_name()` → `"square"`.
- `handle_webhook(...)`:
  - Parses `integration_name="square"` events routed from the generic webhooks router.
  - Verifies signatures and dispatches to specific handlers.
- `verify_signature(...)`:
  - Validates HMAC SHA256 webhook signatures.
- `extract_store_id(...)`:
  - Extracts `merchant_id` (and/or location) from webhook payload or metadata.
- `sync_all_products_from_square(...)`:
  - Implements the full catalog sync with pagination and normalization.
- `update_catalog_object_price(...)`:
  - Updates variation prices via the Square Catalog API.
- `_ensure_valid_token(...)`:
  - Refreshes expiring OAuth tokens before API calls.
- `_handle_catalog_update(...)` and related helpers:
  - Implements the hybrid “single-item vs full-sync” update strategy described above.

#### Transformer & Models

- `SquareTransformer`:
  - Converts raw Square catalog objects into `NormalizedProduct` instances.
  - Handles multi-variation items (one product row per variation).
- Models in `square/models.py`:
  - Strongly typed representations of Square webhook payloads and catalog objects.

---

### Webhook & Auth Endpoints

Key endpoints that involve Square:

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/webhooks/square/{event_type}` | Main Square webhook handler (catalog, inventory, orders) |
| `GET`  | `/auth/square` | Initiate user-facing Square OAuth flow |
| `GET`  | `/auth/square/callback` | OAuth callback, exchanges code for tokens and creates store mapping |
| `GET`  | `/api/auth/square/me` | Returns Square auth + store mapping status for a merchant |
| `GET`  | `/api/auth/square/locations` | Returns all locations for a Square merchant |

All of these feed into, or derive from, the `store_mappings` table and the shared
`products → sync_queue → sync_worker` pipeline.

---

### Delete Reconciliation

Square does not always send explicit delete webhooks for every catalog item. The
integration addresses this by:

1. When a full catalog sync runs (fallback path), it compares:
   - Products returned by Square Catalog API
   - Against `products` in Supabase (`source_system="square"`, `source_store_id=merchant_id`)
2. Any product present in Supabase but **not** in Square’s response is treated as deleted.
3. Those products are queued in `sync_queue` with `operation="delete"` so the ESL sync
   worker can remove the labels.

This keeps the ESL view aligned with Square’s source of truth even when explicit delete
events are missing.

---

### Multi-Tenant Safety

The Square integration is multi-tenant by design:

- Every Supabase query filters by `source_store_id = merchant_id`.
- OAuth tokens are always read from the specific `StoreMapping` for that merchant.
- There is **no global Square access token**; if a token is missing for a merchant, the
  operation fails with a clear error.

---

### Troubleshooting

| Problem | What To Check |
| --- | --- |
| Signature validation failures | Confirm `settings.square_webhook_secret` matches the Square Dashboard secret and the webhook URL (including `https://` + full path) matches exactly. |
| `No locations found` after OAuth | Ensure the Square app has `MERCHANT_PROFILE_READ` and `ITEMS_READ` scopes, and the merchant actually has locations configured. |
| `No access token found` or repeated 401s | Check `store_mappings.metadata` for `square_access_token` / `square_expires_at`. Verify the token refresh worker is running. |
| Missing or unexpectedly deleted products | Review full sync logs and Supabase `products` for that `merchant_id`. Full sync may have reconciled and queued deletions. |
| Price not updating on ESL | Confirm `update_catalog_object_price(...)` is called, `sync_queue` has `update` operations, and the sync worker is running. |

---

### Extending This Integration

#### Adding new webhook event types

1. Add the event to `get_supported_events()` in the adapter.
2. Extend `handle_webhook(...)` with a new branch to handle that event.
3. Add or update Pydantic models in `square/models.py`.
4. Normalize data via `SquareTransformer` and persist via `SupabaseService`.

#### Adding new product fields

1. Update `SquareTransformer` and related catalog models.
2. Keep field mapping in the transformer and orchestration in the adapter.

#### Important Rules

- Do **not** call Hipoink directly from Square code — always use `sync_queue` and
  background workers.
- Always derive credentials and metadata from the `StoreMapping` for the current
  merchant.
- Always filter Supabase queries by `source_store_id`.

