# Clover Integration — Phase 1: Implementation Guide

This document is a **step-by-step implementation guide** for the first phase of the Clover integration: building the core adapter, API client, models, and transformer so that Clover dashboard changes can flow into your database and sync queue (same pattern as Square). OAuth onboarding and token refresh are out of scope for this phase.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Clover Developer Account Setup](#2-clover-developer-account-setup)
3. [Application Configuration](#3-application-configuration)
4. [Phase 1 File Structure](#4-phase-1-file-structure)
5. [Step-by-Step Implementation](#5-step-by-step-implementation)
6. [Registry and Webhook Router Updates](#6-registry-and-webhook-router-updates)
7. [Testing Checklist](#7-testing-checklist)
8. [References](#8-references)

---

## 1. Overview

### 1.1 Goal

- Mirror the Square integration pattern: **adapter**, **api_client**, **models**, **transformer** for Clover.
- After onboarding (later phase), changes in the merchant’s Clover dashboard (inventory items) should:
  - Be received via Clover webhooks.
  - Be transformed to your normalized product format.
  - Be written to the database and queued for ESL sync.

### 1.2 Clover Concepts (Relevant to Phase 1)

| Concept | Notes |
|--------|--------|
| **Merchant** | Identified by `mId` (merchant ID). All API calls are per-merchant. |
| **Items** | Inventory items. REST: `GET/POST /v3/merchants/{mId}/items`. |
| **Price** | Integer in **cents** (e.g. $20.99 → `2099`). |
| **Webhooks** | Single callback URL per app. Payload can contain multiple merchants and multiple updates. Each update has `objectId` (e.g. `I:ITEM_ID`), `type` (CREATE/UPDATE/DELETE), `ts`. |
| **Auth** | REST: `Authorization: Bearer <token>`. Webhook: **X-Clover-Auth** header equals your Clover Auth Code (static string comparison only — Clover does **not** sign the body like Stripe/Square). |
| **Sandbox** | Base URL: `https://sandbox.dev.clover.com`. Production: `https://api.clover.com`. |

### 1.3 Alignment With Existing Integrations

- **Square**: Same flow (webhooks → transform → DB → queue). Clover adapter should follow the same adapter interface and patterns (e.g. `sync_all_products_from_*`, webhook handlers).
- **NCR**: Has a dedicated `api_client.py` and `transformer.py` (normalized → NCR format). For Clover, transformer is **Clover → normalized** (like Square).
- **Base contract**: `app/integrations/base.py` — `get_name`, `verify_signature`, `extract_store_id`, `transform_product`, `transform_inventory`, `get_supported_events`, `handle_webhook`.

### 1.4 Critical Implementation Notes (Gotchas)

| Gotcha | Detail |
|--------|--------|
| **Webhook “signature” is not HMAC** | Clover sends `X-Clover-Auth` with a **static auth code**. Do **not** HMAC the body. Use `secrets.compare_digest(header_value, settings.clover_webhook_auth_code)`. |
| **Pagination is limit/offset** | Clover uses `limit` and `offset` query params. Loop `offset=0`, `offset=100`, … until the response has fewer items than `limit` or is empty. |
| **Verification POST must be handled first** | When you save the Webhook URL, Clover immediately POSTs `{"verificationCode": "..."}`. If the handler tries to parse `merchants` or `objectId` on that request, it will error and the dashboard will show “Verification Failed.” Detect `"verificationCode" in payload and "merchants" not in payload` and return 200 with the code. |
| **Multi-merchant: never fail the whole webhook** | One POST can contain multiple merchants. Process all; on per-merchant failure (e.g. no store mapping), log and collect errors but **always return 200** so Clover doesn’t retry the entire payload. |
| **objectId edge cases** | Only process `I:<id>` (inventory). Skip `O:...` (orders). Reject malformed: `I:` with no id, empty, or `None` — log and skip. |

---

## 2. Clover Developer Account Setup

Do these in the Clover Developer Dashboard **before** or in parallel with implementation.

### 2.1 Create / Use a Clover Developer Account

- **Sandbox**: [https://sandbox.dev.clover.com](https://sandbox.dev.clover.com) — sign up / log in.
- **Production**: Use the [Global Developer Platform](https://docs.clover.com/dev/docs/get-started-with-the-global-developer-platform) when you go live.
- For Phase 1, **sandbox is enough**.

### 2.2 Create an App (Sandbox)

1. In the sandbox dashboard: **Your Apps** → **Create new app** (or use an existing app).
2. **App name**: e.g. “ZKong ESL Integration”.
3. Note the **App ID** (and later, when you use OAuth, **App Secret**). For Phase 1 you may only need the app for webhook configuration.

### 2.3 Set App Permissions

1. Go to **Your Apps** → *Your app* → **App Settings** (or **Permissions**).
2. Enable at least:
   - **Read inventory** — required for item webhooks and for pulling items via REST.
3. If you later add orders or payments, add the corresponding read permissions. For Phase 1, **Read inventory** is the critical one.

Reference: [Set app permissions](https://docs.clover.com/dev/docs/set-app-permissions).

### 2.4 Configure Webhooks

1. **Your Apps** → *Your app* → **App Settings** → **Webhooks**.
2. **Webhook URL**: Your public HTTPS endpoint, e.g.  
   `https://your-backend.example.com/webhooks/clover/inventory`  
   (Must be HTTPS; localhost will not receive Clover webhooks.)
3. **Send Verification Code**: Clover sends a POST with a JSON body like `{"verificationCode": "..."}`.
4. Copy the `verificationCode` from that request (or from logs), paste it into the **Verification Code** field in the dashboard, then click **Verify**.
5. **Subscribe to event types**: In **Events Subscriptions**, subscribe to **Inventory** (item create/update/delete).
6. **Save**.
7. Note the **Clover Auth Code** shown in the Webhooks section — you will compare this with the `X-Clover-Auth` header (simple string comparison; Clover does **not** HMAC the body).

Reference: [Use webhooks](https://docs.clover.com/dev/docs/webhooks).

### 2.5 Get a Merchant API Token (Sandbox) — Phase 1 Token Storage

For Phase 1 testing without full OAuth:

1. Create or use a **test merchant** and install your app on that merchant.
2. In the dashboard, **generate a merchant-specific API token** for that test merchant.
3. Use this token as the Bearer token for REST calls to `GET /v3/merchants/{mId}/items` etc.

**How the token gets into your app (Phase 1):** Store it in the **store mapping metadata** for that merchant (e.g. key `clover_access_token`). In Phase 1 this is **test-only**: you can add the mapping manually (DB insert) or via a simple admin/internal endpoint that accepts `merchant_id` + `access_token` and creates/updates the store mapping. **Production Phase 2** will replace this with OAuth (access + refresh tokens) and token refresh; the adapter can continue to read the token from `store_mapping.metadata["clover_access_token"]` so the migration path is just “write OAuth tokens there instead of the test token”.

### 2.6 Summary of What You Need From the Dashboard

| Item | Where | Use |
|------|--------|-----|
| App ID | App settings | OAuth later; optional in Phase 1 |
| App Secret | App settings | OAuth later |
| Clover Auth Code | Webhooks section | `CLOVER_WEBHOOK_AUTH_CODE` → verify `X-Clover-Auth` |
| Webhook URL | Webhooks section | Your backend URL, e.g. `https://.../webhooks/clover/inventory` |
| Merchant ID (mId) | Test merchant | `source_store_id` / merchant identifier in API calls |
| Merchant API token | Test merchant / API tokens | Bearer token for REST (Phase 1 testing) |

---

## 3. Application Configuration

Add to `app/config.py` in the `Settings` class (e.g. after the Square block) and to `.env`:

**Exact placement in `Settings`:**

```python
# Square Configuration
square_webhook_secret: str = ""
# ...

# Clover Configuration
clover_webhook_auth_code: str = ""   # Clover Auth Code from Dashboard → Webhooks (static auth code, NOT HMAC)
clover_environment: str = "sandbox"  # "sandbox" | "production"

# Optional for Phase 2 OAuth
clover_app_id: str = ""
clover_app_secret: str = ""
```

**Notes:**

- `clover_webhook_auth_code`: Compared with the `X-Clover-Auth` header. **Clover does not sign the payload** — use a constant-time string compare (e.g. `secrets.compare_digest`), not HMAC of the body.
- `clover_environment`: Drives API base URL (`https://sandbox.dev.clover.com` vs `https://api.clover.com`).

**Example `.env`:**

```env
CLOVER_WEBHOOK_AUTH_CODE=your-auth-code-from-dashboard
CLOVER_ENVIRONMENT=sandbox
```

---

## 4. Phase 1 File Structure

Create the following under `app/integrations/clover/`:

```
app/integrations/clover/
├── __init__.py       # Optional: export adapter, e.g. "Clover integration"
├── models.py         # Pydantic models for Clover item and webhook payload
├── api_client.py     # Clover REST client (items list, get item)
├── transformer.py    # Clover item → NormalizedProduct
└── adapter.py         # BaseIntegrationAdapter implementation
```

No token refresh or OAuth in Phase 1; those can be added in a later phase.

---

## 5. Step-by-Step Implementation

### 5.1 `app/integrations/clover/models.py`

**Purpose:** Define Pydantic models for Clover API and webhook payloads so the rest of the code is type-safe and validated.

**Clover webhook payload (from docs):**

- Top level: `appId`, `merchants`.
- `merchants`: object mapping merchant ID → list of **update** objects.
- Each update: `objectId` (e.g. `I:ITEM_ID`), `type` (`CREATE` | `UPDATE` | `DELETE`), `ts` (Unix ms).

**Clover item (from REST API / docs):**

- Fields you need for normalization: `id`, `name`, `price` (cents), `sku`, `alternateName`, optional barcode/code fields.  
  Exact field names may vary; check [Clover API Reference – Inventory Items](https://docs.clover.com/dev/reference/inventorygetitems) and [Create inventory item](https://docs.clover.com/dev/reference/inventorycreateitem). Common pattern:
  - `id` — string
  - `name` — string
  - `price` — integer (cents)
  - `sku` — string (optional)
  - Tax rates, categories, etc. as needed later.

**Suggested models:**

1. **Webhook**
   - `CloverWebhookUpdate`: `objectId: str`, `type: Literal["CREATE", "UPDATE", "DELETE"]`, `ts: int`.
   - `CloverWebhookPayload`: `appId: Optional[str]`, `merchants: Dict[str, List[CloverWebhookUpdate]]` (key = merchant ID).

2. **Item**
   - `CloverItem`: Pydantic model with at least: `id`, `name`, `price` (int), `sku` (optional), and any barcode/alternate id field Clover uses. Use `Optional` for fields that may be missing.

3. **Verification (optional)**
   - If Clover sends a verification POST with only `verificationCode`, you can have a small model for that (e.g. `CloverWebhookVerification`) so the webhook handler can parse and optionally echo it.

**Implementation steps:**

1. Add `from pydantic import BaseModel` and typing (`Dict`, `List`, `Optional`, `Literal`).
2. Define `CloverWebhookUpdate` and `CloverWebhookPayload`.
3. Define `CloverItem` with the fields you get from `GET /v3/merchants/{mId}/items` and `GET /v3/merchants/{mId}/items/{itemId}`. Match the actual API response (you can refine after first API test).
4. Export all from `models.py`.

---

### 5.2 `app/integrations/clover/api_client.py`

**Purpose:** Encapsulate all Clover REST calls for items so the adapter and webhook handler do not deal with HTTP or base URLs.

**Exact API endpoints:**

- **List items (paginated):** `GET https://{base}/v3/merchants/{mId}/items?limit=100&offset=0`  
  Clover uses **limit/offset** pagination (not cursor). Loop with `offset=0`, then `offset=100`, etc., until the returned list is empty or shorter than `limit`.
- **Get single item:** `GET https://{base}/v3/merchants/{mId}/items/{itemId}`

**Responsibilities:**

- Use base URL from config: `https://sandbox.dev.clover.com` (sandbox) or `https://api.clover.com` (production).
- Set `Authorization: Bearer <token>` and `Content-Type: application/json`.
- Return parsed JSON (dict/list) so callers get item(s) in a consistent shape.
- Handle non-2xx by raising or returning a structured error so the adapter can log and optionally trigger Slack alerts.

**Implementation steps:**

1. Read `settings.clover_environment` and set `self.base_url` accordingly.
2. Constructor: e.g. `__init__(self, access_token: str, base_url: Optional[str] = None)` — if `base_url` is None, derive from settings.
3. Implement `list_items(merchant_id: str) -> List[Dict[str, Any]]`:
   - Loop: `offset=0`, then `offset=100`, … (or use Clover’s documented `limit`/`offset` param names).
   - Append each page’s items; stop when the response has fewer items than `limit` or is empty.
   - **Rate limiting:** When implementing `sync_all_products_from_clover`, add a small delay between pages (e.g. 100–200 ms) if Clover documents rate limits, to avoid throttling.
4. Implement `get_item(merchant_id: str, item_id: str) -> Optional[Dict[str, Any]]`:
   - GET single item; return None on 404, raise or return error on other failures.
5. Use `httpx.AsyncClient` and async methods so the adapter can `await` them.
6. Centralize logging and optionally add a small retry for 5xx.

---

### 5.3 `app/integrations/clover/transformer.py`

**Purpose:** Convert Clover item payloads into your normalized product format (`NormalizedProduct` from `app.integrations.base`), so the rest of the pipeline (DB, queue, ESL) stays integration-agnostic.

**Behavior:**

- **One Clover item → one NormalizedProduct** (Clover does not have variants like Square; one item = one sellable product).
- Map:
  - `source_id` ← Clover item `id`.
  - `source_variant_id` ← `None` (no variants).
  - `title` ← item `name` (or alternate name if you prefer).
  - `price` ← item `price` **in dollars** (Clover stores cents → divide by 100).
  - `currency` ← `"USD"` (or from item/merchant if available).
  - `barcode` / `sku` ← from item’s `sku` or barcode field per Clover API.
  - `image_url` ← if Clover provides it; otherwise `None`.
- Put any extra Clover-specific fields you need into `extra_data` (e.g. for debugging or future rules).

**Implementation steps:**

1. Import `NormalizedProduct` from `app.integrations.base`.
2. Implement a function or static method, e.g. `CloverTransformer.transform_item(raw_item: Dict[str, Any]) -> NormalizedProduct`.
3. Parse `raw_item` (from API or webhook “fetch by id” response): id, name, price (convert cents → float dollars), sku/barcode.
4. Return `NormalizedProduct(...)` with the mappings above.
5. Add a small `validate_normalized_product(product: NormalizedProduct) -> Tuple[bool, List[str]]` (same contract as Square/NCR) so the adapter can validate before DB write.
6. Optional: add a helper to extract `merchant_id` from Clover webhook payload (e.g. first key in `payload["merchants"]` when handling a single merchant, or loop over all keys). This can live in transformer or adapter.

---

### 5.4 `app/integrations/clover/adapter.py`

**Purpose:** Implement `BaseIntegrationAdapter` for Clover so the app can verify webhooks, parse store id, transform products, and handle inventory events (and later full-sync).

**Implement these methods:**

1. **`get_name(self) -> str`**  
   Return `"clover"`.

2. **`verify_signature(self, payload: bytes, signature: str, headers: Dict[str, str]) -> bool`**  
   - **Important:** Clover does **not** sign the webhook body (unlike Stripe or Square). The “signature” is just the **X-Clover-Auth** header value.  
   - Compare the header value (or the `signature` argument if the router passes `X-Clover-Auth` as `signature`) with `settings.clover_webhook_auth_code` using **constant-time comparison** (e.g. `secrets.compare_digest(a, b)`).  
   - **Do not** HMAC or hash the body; simple string equality is correct.  
   - Return `True` only if both are non-empty and equal; otherwise `False`.

3. **`extract_store_id(self, headers: Dict[str, str], payload: Dict[str, Any]) -> Optional[str]`**  
   - Clover payload has `merchants` (dict: merchant_id → list of updates).  
   - For a single-merchant webhook you might have one key; for batch, you may need to return the first merchant or all (design choice).  
   - Return one `merchant_id` (e.g. first key in `payload.get("merchants", {})`) so the rest of the pipeline can resolve store mapping and token.  
   - If payload is not in expected shape, return `None`.

4. **`transform_product(self, raw_data: Dict[str, Any]) -> List[NormalizedProduct]`**  
   - `raw_data` here is a **single Clover item** (dict).  
   - Call `CloverTransformer.transform_item(raw_data)` and return `[normalized_product]` (list of one).

5. **`transform_inventory(self, raw_data: Dict[str, Any]) -> Optional[NormalizedInventory]`**  
   - Phase 1: return `None`. You can later map Clover inventory/stock to `NormalizedInventory` if needed.

6. **`get_supported_events(self) -> List[str]`**  
   - Return `["inventory"]` (or the event_type you use in the webhook route, e.g. `"inventory"`).  
   - This must match the path you register in the webhook router (e.g. `POST /webhooks/clover/inventory`).

7. **`async def handle_webhook(self, event_type: str, request: Request, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]`**  

   **a) Verification POST (handle first)**  
   When you first save the Webhook URL in the Clover dashboard, Clover sends a one-time POST with only `{"verificationCode": "..."}`. Your handler **must** detect this and return immediately; otherwise parsing `merchants` or `objectId` will error and the dashboard will show “Verification Failed.”

   ```python
   if "verificationCode" in payload and "merchants" not in payload:
       return {"verificationCode": payload["verificationCode"]}  # 200 OK
   ```

   **b) Payload validation**  
   Before processing, validate the payload so malformed JSON doesn’t crash the handler:

   ```python
   try:
       webhook_payload = CloverWebhookPayload(**payload)
   except ValidationError as e:
       logger.error("Invalid Clover webhook payload", error=str(e))
       raise HTTPException(status_code=400, detail="Invalid payload")
   ```

   **c) Multi-merchant processing and error handling**  
   Clover can send **one webhook for multiple merchants**. Process **all** merchants; do **not** fail the entire webhook if one merchant fails (e.g. missing store mapping or token). That would cause Clover to retry the whole payload and create retry storms.

   - Loop over each `merchant_id` in `payload.merchants`.
   - For each merchant: resolve store mapping, get token, then process that merchant’s update list. If resolution or processing fails, **log the error**, **record it in a per-merchant or global error list**, and **continue** to the next merchant.
   - **Always return 200** with a body that can include partial success and errors, e.g. `{"status": "ok", "updated": N, "deleted": M, "errors": [{"merchant_id": "...", "message": "..."}]}`. Log and/or send Slack alerts for any collected errors.

   **d) Per-update processing**  
   For each update in the merchant’s list:

   - **objectId parsing and validation:**  
     - Accept inventory: `objectId` starts with `I:` and has an id after it (e.g. `I:ITEM123`). Strip the `I:` prefix to get the item id.  
     - Skip non-inventory: e.g. `O:ORDER456` (orders) — log and skip.  
     - Reject malformed: `I:` with nothing after it, empty string, or `None` — log and skip (do not crash).
   - **DELETE:** Mark product deleted / queue delete in DB and sync queue (same idea as Square).
   - **CREATE / UPDATE:** Call `api_client.get_item(merchant_id, item_id)`, then `transform_product(item)`, validate, then `create_or_update_product` and add to sync queue.

   **e) Optional — replay protection**  
   Each update has a `ts` (Unix ms). You may validate that `ts` is not too old (e.g. reject if older than 5–10 minutes) to mitigate replay if the auth code were ever leaked. Document or implement as needed.

8. **Optional but recommended for parity with Square:**  
   - **`async def sync_all_products_from_clover(self, merchant_id: str, access_token: str, store_mapping_id: UUID, base_url: Optional[str] = None) -> Dict[str, Any]`**  
   - Use `CloverAPIClient(access_token, base_url).list_items(merchant_id)` to fetch all items.  
   - For each item, `transform_product(item)`, validate, then create/update product and add to sync queue (same as Square’s initial sync).  
   - Return stats (total_items, products_created, products_updated, queued_for_sync, errors).  
   - You can call this from an onboarding or “sync” endpoint in a later phase.

**Dependencies:**

- Import `ValidationError` from `pydantic` for payload validation in `handle_webhook`.
- Use `SupabaseService` for `get_store_mapping`, `create_or_update_product`, `add_to_sync_queue`, `get_products_by_source_id`, etc., same as Square adapter.
- Use `CloverAPIClient` for fetching items by id or listing.
- Use `CloverTransformer` for item → normalized and validation.
- Use `get_slack_service()` for error alerts if you want behavior similar to Square.

**Multiple locations:** Clover merchants can have multiple locations (similar to Square). Phase 1 can treat the merchant as a single store; location-specific behavior can be deferred to Phase 2 if needed.

---

## 6. Registry and Webhook Router Updates

### 6.1 Register the Clover Adapter

In `app/integrations/registry.py`:

- In `_load_integrations`, add a block that:
  - Tries to `from app.integrations.clover.adapter import CloverIntegrationAdapter`.
  - Instantiates `CloverIntegrationAdapter()` and calls `self.register(clover_adapter)`.
  - Logs "Loaded Clover integration" (and log warning/error on ImportError or exception).

### 6.2 Webhook Router: Signature and Routing for Clover

In `app/routers/webhooks_new.py` (or wherever you handle `POST /webhooks/{integration_name}/{event_type}`):

**Signature extraction (add alongside Shopify and Square):**

```python
elif integration_name == "clover":
    signature = headers.get("X-Clover-Auth") or headers.get("x-clover-auth")
```

**Important:** For Clover, this “signature” is **not** an HMAC of the body — it is a **static auth code** from the dashboard. The adapter’s `verify_signature` will perform a simple constant-time string comparison with `settings.clover_webhook_auth_code`, not HMAC verification.

**Verification flow:**

- Require that the header is present and that `adapter.verify_signature(body_bytes, signature, headers)` returns True; otherwise return 401.
- Use the same `event_type` as in `get_supported_events()` (e.g. `"inventory"`), so `POST /webhooks/clover/inventory` is the URL you configure in the Clover dashboard.

---

## 7. Testing Checklist

- **Config**: `CLOVER_WEBHOOK_AUTH_CODE` and `CLOVER_ENVIRONMENT` set; app starts without import errors.
- **Models**: Parse a sample webhook JSON and a sample item JSON using your Pydantic models; no validation errors.
- **API client**: With a sandbox merchant token and merchant ID, call `list_items` and `get_item`; confirm response shape matches your models and transformer.
- **Transformer**: Pass a sample Clover item dict; get one `NormalizedProduct` with correct price (dollars), title, barcode/sku.
- **Adapter**:  
  - `get_name()` returns `"clover"`.  
  - `verify_signature` returns True when header matches auth code, False otherwise (and does **not** HMAC the body).  
  - `extract_store_id` returns merchant id from a sample payload.  
  - `transform_product(sample_item)` returns a one-element list.  
  - **Verification POST:** Send `{"verificationCode": "test123"}` with valid `X-Clover-Auth`; handler must return 200 with body containing the same code (no parsing of `merchants`).  
  - **handle_webhook:** Send a test POST with valid `X-Clover-Auth` and payload with one merchant and one inventory UPDATE; confirm one product is created/updated in DB and one item is queued. For a payload with two merchants where one has no store mapping, response must still be 200 with errors recorded in the body.
- **Registry**: On app startup, log shows “Loaded Clover integration” and `list_available()` includes `"clover"`.
- **End-to-end**: From Clover sandbox dashboard, change an item (e.g. name or price); confirm webhook is received and DB + queue updated (if you have a test merchant and token wired).

---

## 8. References

- [Clover Platform Docs – Home](https://docs.clover.com/dev/docs/home)
- [Use webhooks](https://docs.clover.com/dev/docs/webhooks) – callback URL, verification, X-Clover-Auth, event type keys (e.g. I = Inventory)
- [Developer support](https://docs.clover.com/dev/docs/developer-technical-support)
- [Clover REST API – Get all inventory items](https://docs.clover.com/dev/reference/inventorygetitems)
- [Clover REST API – Get a single inventory item](https://docs.clover.com/dev/reference/inventorygetitem)
- [Clover REST API – Create inventory item](https://docs.clover.com/dev/reference/inventorycreateitem)
- [Clover OAuth (for later phases)](https://docs.clover.com/dev/docs/oauth-flows-in-clover)
- [Medium – Clover Platform Blog](https://medium.com/clover-platform-blog)

---

After you complete Phase 1, we can add OAuth onboarding, token refresh, and any Clover-specific edge cases (pagination, rate limits, error handling). If you want, the next step can be concrete code snippets for `models.py`, `api_client.py`, `transformer.py`, and `adapter.py` following this guide.
