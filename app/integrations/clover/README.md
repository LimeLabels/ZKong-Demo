## Clover Integration

### What Is This?

The Clover integration connects **Clover point-of-sale (POS) systems** to the Hipoink ESL
(Electronic Shelf Label) middleware. Whenever products are created, updated, or deleted in
Clover, those changes are automatically reflected on your electronic shelf labels — no
manual work required.

Think of it as a live bridge: anything that changes in Clover’s inventory flows
automatically to your physical store shelf labels.

---

### What Does It Do?

| Capability | Description |
| --- | --- |
| **Webhook handling** | Receives near real-time inventory events from Clover when items change |
| **Incremental polling** | Periodically checks Clover for any changes it may have missed |
| **Full sync** | Can pull all products from Clover from scratch when needed |
| **Price updates** | Applies time-based price changes back into Clover’s Back Office System (BOS) |
| **Ghost item cleanup** | Detects and removes products that no longer exist in Clover |
| **Multi-tenant support** | Safely handles multiple merchants/stores without data leaking between them |

All of this is implemented strictly through the `products` / `sync_queue` /
`sync_worker` pipeline. Routers and adapters **never** call the Hipoink ESL API directly.

---

### How Data Flows

There are three main ways data moves from Clover into the system:

#### 1. Webhook-Driven (Real-Time)

This is the fastest path — changes in Clover appear on shelf labels within seconds.

```text
Clover detects item change
        ↓
Sends webhook POST to: /webhooks/clover/{event_type}
        ↓
System verifies the request is genuinely from Clover
(checks X-Clover-Auth header against stored auth code)
        ↓
Fetches full item details from Clover API
        ↓
Normalizes and saves product to Supabase (products table)
        ↓
Queues item in sync_queue for ESL sync
        ↓
sync_worker updates the physical shelf label via Hipoink API
```

**Supported webhook events today:** `inventory` (item create, update, delete).

> Engineering detail: Clover uses a static auth code rather than a body HMAC signature.
> The `X-Clover-Auth` header is compared to `settings.clover_webhook_auth_code` using
> `secrets.compare_digest` for constant-time comparison.

---

#### 2. Polling-Based Incremental Sync (Regular Worker)

Webhooks can occasionally be missed or delayed. The polling worker acts as a safety net,
running regularly to catch anything that slipped through and to drive ghost-item cleanup.

```text
Clover sync worker runs on a schedule
        ↓
Reads last sync timestamp from store mapping metadata (clover_last_sync_time)
        ↓
Fetches all items modified since that timestamp (list_items_modified_since)
        ↓
For each item:
  - If deleted/hidden → mark as deleted, queue ESL removal
  - If new/updated   → normalize, upsert in Supabase, queue ESL sync
        ↓
Updates clover_last_sync_time and clover_poll_count in store metadata
        ↓
Every N polls (default 10) or after N hours → ghost-item cleanup
```

**Ghost item cleanup** compares:

- All active items in Clover (via `list_all_item_ids`)
- Against all active `products` for that Clover merchant in Supabase.

Any product in Supabase that no longer exists in Clover is marked deleted and queued for
ESL removal. This guarantees eventual consistency even if some events were missed.

---

#### 3. Initial Full Sync (First-Time Setup)

When a new Clover store is connected for the first time, a full sync pulls every product
from Clover into the system.

```text
Full sync triggered (e.g. onboarding or admin action)
        ↓
Fetches ALL items from Clover with limit/offset pagination
(small delays between pages to respect rate limits)
        ↓
For each item:
  - Normalize → validate → upsert in Supabase (products)
  - If valid and changed → queue in sync_queue
        ↓
Returns summary: total, created, updated, queued, errors
```

Pagination for Clover uses:

- `limit` (page size, default 100)
- `offset` (0, 100, 200, …)
- `PAGINATION_DELAY_SECONDS` (small sleep between pages)

This keeps API calls small and rate-limit friendly even for large catalogs.

---

### Authentication & Security

#### Webhook Verification

Clover uses a **static auth code** for webhook verification.

The system:

1. Reads the `X-Clover-Auth` header from every incoming webhook.
2. Compares it against `settings.clover_webhook_auth_code` using constant-time comparison.
3. Rejects any mismatch with `401 Unauthorized`.

#### One-Time URL Verification

When first registering a webhook URL in the Clover Dashboard, Clover sends a POST that
contains only:

```json
{ "verificationCode": "..." }
```

`CloverIntegrationAdapter.handle_webhook(...)` detects this case and simply echoes back
the verification code so Clover can validate the URL. No authentication is required for
this one-time verification request.

#### OAuth Access Tokens

Clover uses OAuth for API access (for item APIs and BOS price updates). This system:

- Stores tokens in `store_mappings.metadata` (per merchant).
- **Encrypts** tokens at rest using Fernet (`token_encryption.py`).
- **Refreshes** tokens proactively using `CloverTokenRefreshService` (token refresh worker).
- Always resolves tokens per store mapping — never shares tokens across merchants.

If a token appears to be encrypted ciphertext (e.g. starts with `"gAAAAA"`), but no
decryption key is configured, the adapter logs a clear error and refuses to call the API
with that value.

---

### Key Components

#### `adapter.py` — `CloverIntegrationAdapter`

The main orchestration layer. It owns the Clover ↔ Supabase ↔ sync_queue pipeline.

Key responsibilities:

- `get_name()` → `"clover"`.
- `verify_signature(payload, signature, headers)`:
  - Compares `signature` (from `X-Clover-Auth`) against `settings.clover_webhook_auth_code`.
- `extract_store_id(headers, payload)`:
  - Reads the first merchant ID from `payload["merchants"]`, if present.
  - That merchant ID becomes `store_mappings.source_store_id`.
- `transform_product(raw_data)`:
  - Uses `CloverTransformer.transform_item(...)` to produce a `NormalizedProduct`.
- `transform_inventory(...)`:
  - Currently a placeholder (`return None`) — inventory is not modeled as a separate
    object yet.
- `validate_normalized_product(product)`:
  - Delegates to `CloverTransformer.validate_normalized_product`.
- `get_supported_events()`:
  - Currently returns `["inventory"]`.
- `_ensure_valid_token(store_mapping)`:
  - Decrypts tokens using `decrypt_tokens_from_storage`.
  - Uses `CloverTokenRefreshService` to refresh tokens when they are close to expiring.
- `sync_products_via_polling(...)`:
  - Incremental polling + ghost-item cleanup as described above.
- `sync_all_products_from_clover(...)`:
  - Full initial sync via `CloverAPIClient.list_items(...)`.
- `update_item_price(...)`:
  - Validates the token is decrypted/plaintext.
  - Calls `CloverAPIClient.update_item(...)` to update BOS prices.
  - Keeps local `products` table in sync with the BOS price.

#### `api_client.py` — `CloverAPIClient`

Handles all direct HTTP communication with the Clover REST API.

Key behaviors:

- Uses `httpx.AsyncClient` with configurable base URL based on `settings.clover_environment`
  (`sandbox` vs `production`).
- Authenticates with **Bearer tokens**:

  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```

- Supports:
  - `get_item(merchant_id, item_id)`
  - `list_items(merchant_id)` (full catalog, paginated)
  - `list_items_modified_since(merchant_id, modified_since)` (incremental polling)
  - `list_all_item_ids(merchant_id)` (for ghost cleanup)
  - `update_item(merchant_id, item_id, price_cents)` (BOS price updates)

#### `token_encryption.py`

Implements Fernet-based encryption for Clover tokens:

- `encrypt_tokens_for_storage(metadata)`:
  - Encrypts `clover_access_token` and `clover_refresh_token` before writing them to
    `store_mappings.metadata`.
- `decrypt_tokens_from_storage(metadata)`:
  - Decrypts those fields when loading metadata for API calls.

Fernet gives you authenticated encryption (AES + HMAC) with a simple API and a single
44-character base64 key (`CLOVER_TOKEN_ENCRYPTION_KEY`).

#### `clover_sync_worker.py` — `CloverSyncWorker`

Background worker responsible for periodic polling:

- Runs every `clover_sync_interval_seconds` (default 300 seconds / 5 minutes).
- For each active Clover store mapping:
  - Validates there is a token in metadata.
  - Calls `adapter.sync_products_via_polling(mapping)`.
  - Logs counts of processed, deleted, and errored items.

---

### Webhook & Diagnostic Endpoints

Key endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/webhooks/clover/{event_type}` | Main Clover webhook handler (inventory events + verification POST) |
| `GET`  | `/external/clover/diagnose/{store_mapping_id}` | Manual diagnostic endpoint for Clover BOS / sync issues |

---

### Price Updates (Time-Based Pricing)

When a time-based pricing event fires for a Clover store, the system ultimately calls
`CloverIntegrationAdapter.update_item_price(...)`:

1. Ensures a valid, decrypted OAuth token for the store (via `_ensure_valid_token`).
2. Converts the price from dollars to **integer cents**:

   ```python
   price_cents = round(price_dollars * 100)
   ```

3. Calls `CloverAPIClient.update_item(...)` with the new price.
4. Updates the product price in Supabase so the local DB stays aligned with Clover BOS.
5. Queues appropriate operations in `sync_queue` so ESL labels update.

---

### Multi-Tenant Safety

The Clover integration is designed to safely handle multiple merchants:

- Every Supabase query for Clover is filtered by `source_store_id = merchant_id`.
- OAuth tokens are always read from the specific `StoreMapping` for that merchant.
- Tokens are never reused or shared across merchants.
- Ghost cleanup runs per-store, comparing that store’s Supabase products to its Clover
  items only.

---

### Troubleshooting

| Problem | What To Check |
| --- | --- |
| Webhooks rejected with 401 | Confirm `CLOVER_WEBHOOK_AUTH_CODE` matches the value configured in the Clover Dashboard. This must be **plaintext**, not encrypted. |
| Tokens starting with `"gAAAAA"` in logs | Indicates Clover tokens are encrypted but `CLOVER_TOKEN_ENCRYPTION_KEY` is missing or invalid. Configure the correct Fernet key in environment. |
| Ghost items not being cleaned up | Confirm the Clover sync worker is running and that `clover_poll_count` is incrementing in store metadata. Also check `clover_last_cleanup_time`. |
| Products not appearing after webhook | Ensure a `StoreMapping` exists for the Clover `merchant_id`, and the webhook URL and `X-Clover-Auth` are correctly configured in the Clover Dashboard. |

---

### Extending This Integration

#### Adding new webhook event types

1. Add the event type to `CloverIntegrationAdapter.get_supported_events()`.
2. Extend `handle_webhook(...)` with a new handler branch for that event type.
3. Update or extend `CloverWebhookPayload` to validate the new payload shape.
4. Keep Supabase access behind `SupabaseService` and always filter by `source_store_id`.

#### Adding new product fields

1. Update `CloverTransformer` to map additional fields into `NormalizedProduct`.
2. Keep validation strict enough to prevent sending incomplete/bad data to ESL.

#### Inventory and pricing

- Inventory is currently not fully modeled (see `transform_inventory`).
- If you add inventory-driven behavior, keep mapping in the transformer/adapter and
  continue to use `sync_queue` to talk to the ESL sync worker.

#### Multi-tenant isolation

- Always filter Supabase queries by `source_store_id = merchant_id`.
- Do not share Clover credentials or tokens between merchants.

