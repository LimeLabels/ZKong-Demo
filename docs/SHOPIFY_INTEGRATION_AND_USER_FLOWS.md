# Shopify Integration, User Onboarding, Time-Based Pricing & User Flows

This document provides an in-depth reference for the **Shopify integration**, **user onboarding**, **time-based pricing system**, and **end-to-end user flows** in the Hipoink ESL (Electronic Shelf Label) middleware.

---

## Table of Contents

1. [Shopify Integration](#1-shopify-integration)
2. [User Onboarding](#2-user-onboarding)
3. [Time-Based Pricing](#3-time-based-pricing)
4. [User Flows](#4-user-flows)
5. [Data Models & APIs](#5-data-models--apis)
6. [Environment & Running the System](#6-environment--running-the-system)

---

# 1. Shopify Integration

## 1.1 Overview

The Shopify integration connects **Shopify stores** to the Hipoink ESL middleware. It:

- Listens for **real-time product and inventory changes** from Shopify via **webhooks**
- **Normalizes** product data (including multi-variant handling)
- **Stores** products in Supabase and enqueues them for ESL sync
- Uses the central pipeline: **products → sync_queue → sync_worker → Hipoink**

No Shopify-specific code talks to Hipoink directly; all updates flow through the shared sync pipeline.

---

## 1.2 Capabilities

| Capability | Description |
|------------|-------------|
| **Webhook handling** | Receives product create/update/delete and inventory_levels/update events |
| **Product sync** | Creates, updates, deletes products in Supabase and queues for ESL sync |
| **Multi-variant support** | Each Shopify variant becomes its own `NormalizedProduct` (one row per variant) |
| **Inventory tracking** | Receives inventory level updates (extension point; currently logged) |
| **Signature verification** | Validates every webhook with HMAC SHA256 using `SHOPIFY_WEBHOOK_SECRET` |
| **Multi-tenant support** | Isolates data by shop domain (`source_store_id` = shop domain) |

---

## 1.3 Data Flow (Webhook-Driven)

```
Product created/updated/deleted in Shopify
        ↓
Shopify sends webhook POST to:
  /webhooks/shopify/products/create
  /webhooks/shopify/products/update
  /webhooks/shopify/products/delete
  /webhooks/shopify/inventory_levels/update
        ↓
System verifies X-Shopify-Hmac-Sha256 (HMAC SHA256 over raw body)
        ↓
Adapter resolves integration; payload parsed with Pydantic models
        ↓
ShopifyTransformer: one NormalizedProduct per variant
        ↓
Upsert in Supabase (source_system="shopify", source_store_id=shop_domain)
        ↓
Enqueue in sync_queue
        ↓
sync_worker processes queue → Hipoink ESL API
```

**Supported webhook events:**

| Event | Shopify Trigger | Operation Queued |
|-------|------------------|------------------|
| `products/create` | New product in Shopify | `create` |
| `products/update` | Product/variant edited | `update` |
| `products/delete` | Product deleted | `delete` |
| `inventory_levels/update` | Inventory quantity changed | Logged (extension point) |

---

## 1.4 Variant Handling

Shopify products can have **multiple variants** (e.g. sizes S, M, L). The integration treats **each variant as a separate product** in the system:

```
Shopify Product (1 product)
  ├── Variant: Small  → NormalizedProduct (source_variant_id = variant_id_1)
  ├── Variant: Medium → NormalizedProduct (source_variant_id = variant_id_2)
  └── Variant: Large  → NormalizedProduct (source_variant_id = variant_id_3)
```

Each variant gets its own row in `products` and its own `sync_queue` entry so ESL labels can show the correct price per variant.

---

## 1.5 Authentication & Security

### Webhook Signature Verification

- Shopify signs every webhook with **HMAC SHA256** over the **raw request body**.
- The system:
  1. Reads `X-Shopify-Hmac-Sha256` from headers
  2. Computes HMAC SHA256 of raw body using `settings.shopify_webhook_secret`
  3. Compares with `hmac.compare_digest` (constant-time)
  4. Returns `401 Unauthorized` on mismatch

> Proxies must not modify headers or body or verification will fail.

### Store Identification (Multi-Tenancy)

- Each store is identified by **shop domain** (e.g. `mystore.myshopify.com`).
- Stored as `store_mappings.source_store_id`.
- All product/sync queries filter by `source_system="shopify"` and this `source_store_id`.

---

## 1.6 Key Components

| Component | Role |
|-----------|------|
| **`adapter.py` — ShopifyIntegrationAdapter** | Webhook handling, signature verification, `extract_store_id`, `transform_product` (→ list of NormalizedProduct), product create/update/delete handlers, inventory handler (extension point) |
| **`models.py`** | Pydantic models for webhook payloads (e.g. ShopifyProduct, ProductCreateWebhook, InventoryLevelsUpdateWebhook) |
| **ShopifyTransformer** | Maps raw Shopify product/variant data to NormalizedProduct (titles, barcodes, SKUs, pricing, images); enforces validation |

---

## 1.7 Product Data in Supabase

Each Shopify-sourced row in `products` includes:

| Field | Value |
|-------|--------|
| `source_system` | `"shopify"` |
| `source_id` | Shopify product ID |
| `source_variant_id` | Shopify variant ID |
| `source_store_id` | Shop domain (e.g. `mystore.myshopify.com`) |
| `status` | `"validated"` or `"pending"` |
| `validation_errors` | Any validation issues |

---

## 1.8 OAuth (App Installation)

Shopify app installation uses **OAuth 2.0**:

- **Scopes:** `read_products`, `write_products`, `read_inventory`, `write_inventory`
- **Initiate:** `GET /auth/shopify?shop=myshop.myshopify.com` → redirects to Shopify OAuth
- **Callback:** `GET /auth/shopify/callback?code=...&shop=...` → exchange code for access token
- **Storage:** Access token is stored in `store_mappings.metadata.shopify_access_token`
- **Post-install:** Backend may create or update a store mapping and optionally trigger an initial full product sync from Shopify

Redirect URI for OAuth must be the **Shopify app frontend** callback URL (e.g. `{SHOPIFY_APP_URL}/auth/shopify/callback`).

---

# 2. User Onboarding

## 2.1 Purpose

Onboarding is the **first-time setup** after a merchant installs the Shopify app. It collects:

- **Hipoink Store Code** — links the Shopify store to a physical store in the Hipoink ESL system
- **Store Name** (optional) — friendly name for the store
- **Timezone** — used for all time-based pricing (schedules run in store local time)

Until onboarding is complete, the app shows the onboarding UI instead of the main strategy UI.

---

## 2.2 When Onboarding Is Shown

The frontend decides to show onboarding based on:

1. **Auth state:** `GET /api/auth/me?shop=...` returns `needs_onboarding: true` when:
   - There is **no** store mapping for the shop, or
   - The store mapping exists but **does not** have a non-empty `hipoink_store_code`
2. **URL override:** `?onboarding=true` forces the onboarding screen (e.g. to re-enter details).

So: **OAuth can be complete** (store mapping exists with access token) but **onboarding incomplete** (no Hipoink store code yet).

---

## 2.3 Onboarding Flow (Step-by-Step)

```
1. User opens app (embedded in Shopify Admin)
       ↓
2. Frontend calls GET /api/auth/me?shop=myshop.myshopify.com
       ↓
3. Backend returns:
   - is_authenticated: true (if OAuth token present)
   - needs_onboarding: true (if hipoink_store_code missing)
   - store_mapping: { id, hipoink_store_code, timezone } or null
       ↓
4. Frontend shows Onboarding component (Polaris form)
       ↓
5. On load: GET /api/store-mappings/current?shop=... to pre-fill (if mapping exists)
       ↓
6. User enters:
   - Hipoink Store Code (required)
   - Store Name (optional)
   - Timezone (dropdown, e.g. America/New_York)
       ↓
7. User clicks "Complete Setup"
       ↓
8. If mapping exists (from OAuth): PUT /api/store-mappings/{id}
   Body: { source_system, source_store_id, hipoink_store_code, is_active, metadata }
   metadata includes: timezone, shopify_shop_domain, store_name
       ↓
   If no mapping: POST /api/store-mappings/ (same body)
   On 409 Conflict (already exists): list mappings, find by shop, then PUT
       ↓
9. Backend updates (or creates) store mapping; metadata is merged, not replaced
       ↓
10. Frontend shows success, then redirects to app root with ?shop=... (removes ?onboarding)
       ↓
11. Next GET /api/auth/me returns needs_onboarding: false → main app (Create / Manage Strategies)
```

---

## 2.4 Onboarding API (Store Mappings)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/store-mappings/current?shop=...` | Get current shop’s mapping (by source_store_id or metadata.shopify_shop_domain) |
| `POST` | `/api/store-mappings/` | Create mapping (used if OAuth didn’t create one or for conflict recovery) |
| `PUT` | `/api/store-mappings/{id}` | Update mapping (onboarding writes hipoink_store_code, timezone, store_name into metadata) |
| `GET` | `/api/store-mappings/?source_system=shopify` | List mappings (e.g. to find existing by shop after 409) |

**Important:** On `PUT`, backend **merges** `metadata` with existing so OAuth tokens and other keys are not lost.

---

## 2.5 Auth/Me Response Shape

`GET /api/auth/me?shop=...` returns:

```json
{
  "shop": "myshop.myshopify.com",
  "is_authenticated": true,
  "needs_onboarding": false,
  "store_mapping": {
    "id": "uuid",
    "hipoink_store_code": "001",
    "timezone": "America/New_York"
  }
}
```

- **is_authenticated:** true if store mapping exists and `metadata.shopify_access_token` is set.
- **needs_onboarding:** true if no mapping or `hipoink_store_code` is missing/empty.

---

# 3. Time-Based Pricing

## 3.1 What It Is

Time-based pricing lets merchants **schedule automatic price changes**: products go to a **promotional price** at a **start time** and **restore to the original price** at an **end time**. Schedules can be one-time or **repeating** (daily, weekly, monthly).

---

## 3.2 Concepts

- **Schedule:** A named set of products, time slots, repeat rules, and optional end date.
- **Time slot:** A pair of times per day, e.g. `09:00`–`17:00` (store local time).
- **Trigger:** The scheduler runs periodically; when “current time” is at the **start** of a slot it applies promotional prices; when at the **end** it restores original prices.
- **Repeat types:** `none` (once), `daily`, `weekly` (with trigger_days), `monthly`.

All times are interpreted in the **store’s timezone** (from store mapping metadata).

---

## 3.3 Schedule Model (Logical)

| Field | Description |
|-------|-------------|
| `store_mapping_id` | Which store this schedule belongs to |
| `name` | Display name (e.g. “Evening Flash Sale”) |
| `order_number` | Unique reference (e.g. for orders) |
| `products` | JSON: `{ "products": [ { "pc": "barcode", "pp": "promo_price", "original_price": 10.99 } ] }` |
| `start_date` | When the schedule becomes active |
| `end_date` | Optional; for repeating schedules, when to stop |
| `repeat_type` | `none` \| `daily` \| `weekly` \| `monthly` |
| `trigger_days` | For weekly: days of week (e.g. 1=Mon … 7=Sun) |
| `trigger_stores` | Optional list of store codes to apply to |
| `time_slots` | `[ { "start_time": "09:00", "end_time": "17:00" } ]` (HH:MM, store time) |
| `multiplier_percentage` | Optional; e.g. 10 = 10% increase; if set, can override explicit `pp` |
| `is_active` | If false, scheduler ignores the schedule |
| `last_triggered_at` | Last time the scheduler ran this schedule (UTC) |
| `next_trigger_at` | Next run time (UTC); scheduler only runs when current time ≥ this |

---

## 3.4 How the Scheduler Works

1. **Loop:** Price scheduler worker runs every **15 seconds** (configurable).
2. **Query:** Fetch schedules where `is_active = true` and `next_trigger_at <= now` (UTC).
3. **Per schedule:**
   - Load **store mapping** and **timezone**.
   - Convert current time to **store timezone**.
   - **Time-slot check:** Is current time within any `time_slots`?
     - **At start** (within ~2 minutes of slot start): **Apply promotional prices** (Hipoink + Shopify if configured).
     - **At end** (within ~5 minutes of slot end): **Restore original prices**.
     - **In middle of slot:** If already triggered today → wait for end; else treat as start.
4. **Next trigger:**
   - After applying promo: set `next_trigger_at` to **end of current slot** (store time → UTC).
   - After restore: compute **next occurrence** (e.g. next day for daily, next week for weekly) and set `next_trigger_at`.
5. **Missed restore:** If we’re past the slot end and last trigger was near a **start** time, the worker performs a “missed restore” and restores original prices, then advances `next_trigger_at` appropriately.

All “next trigger” math is done in **store timezone**, then converted to UTC for storage.

---

## 3.5 Repeat Types (Behavior)

| Repeat | Behavior |
|--------|----------|
| **none** | Single occurrence: start/end on start_date; then schedule effectively done (next_trigger can be null). |
| **daily** | Same time slots every day from start_date until end_date (if set). |
| **weekly** | Only on `trigger_days` (e.g. Sat/Sun); same time slots each of those days. |
| **monthly** | Same day-of-month and same time slots each month. |

If `end_date` is missing or same as `start_date` for daily/weekly/monthly, the code treats it as “no end” (indefinite repeat).

---

## 3.6 Price Application (Hipoink + Shopify)

When the scheduler triggers:

- **Apply promotion:** For each product in the schedule, set price to **promotional price** (from `pp` or from `original_price * (1 + multiplier_percentage/100)`).
- **Restore:** Set price back to **original_price**.

Updates are sent to:

1. **Hipoink ESL API** — so physical shelf labels update.
2. **Shopify API** (if store has Shopify and credentials) — so online/storefront prices stay in sync.

Only the **price** is changed; other product attributes (name, image, barcode, etc.) are unchanged.

---

## 3.7 Time-Slot Tolerance

- **Start:** Trigger when current time is within **2 minutes** of slot start.
- **End:** Trigger when current time is within **5 minutes** of slot end (to reduce risk of missing restore).

This accounts for the scheduler’s 15-second polling interval.

---

## 3.8 Creating a Schedule (API)

- **POST** `/api/price-adjustments/create` (or equivalent create endpoint) with:
  - `store_mapping_id`
  - `name`, `order_number` (optional)
  - `products`: list of `{ pc, pp, original_price }`
  - `start_date`, `end_date`, `repeat_type`, `trigger_days`, `trigger_stores`
  - `time_slots`: `[ { start_time, end_time } ]`
  - optional `multiplier_percentage`

Backend validates, then computes **next_trigger_at** (first occurrence in store timezone, then UTC) and persists the schedule. The worker then picks it up when that time is reached.

---

## 3.9 Calculator Utility (Pre-Scheduling)

`price_schedule_calculator` can compute **all** price events for a schedule (for systems that need to pre-schedule many events, e.g. NCR effectiveDate). It:

- Expands dates from `start_date` to `end_date` according to `repeat_type` and `trigger_days`.
- For each date and each time slot, generates:
  - **apply_promotion** at slot start
  - **restore_original** at slot end
- Uses store timezone for all datetimes.
- Supports `multiplier_percentage` for deriving promotional price from original.

---

# 4. User Flows

## 4.1 End-to-End: Install → Onboarding → Use

```
User clicks "Install App" in Shopify Admin
    ↓
Redirect to /auth/shopify?shop=myshop.myshopify.com
    ↓
Backend redirects to Shopify OAuth (scopes: read/write products, read/write inventory)
    ↓
User approves → redirect to /auth/shopify/callback?code=...&shop=...
    ↓
Backend exchanges code for access token; creates or updates store mapping (token in metadata)
    ↓
Optional: background initial product sync from Shopify
    ↓
Redirect to frontend: ?shop=...&installed=true
    ↓
Frontend calls GET /api/auth/me?shop=...
    ↓
needs_onboarding=true → show Onboarding
    ↓
User enters Hipoink store code, timezone, optional store name → PUT /api/store-mappings/{id}
    ↓
Redirect; next auth/me → needs_onboarding=false
    ↓
Main app: tabs "Create Strategy" and "Manage Strategies"
```

---

## 4.2 Create Strategy Flow

```
User selects "Create Strategy" tab
    ↓
Fills form: name, start/end dates, repeat type, time slots, trigger days/stores if needed
    ↓
Clicks "Select Product" → product picker (search by barcode/SKU/name)
    ↓
GET /api/products/search?shop=...&q=... (local DB + Shopify API via stored token)
    ↓
User selects product(s); form gets barcode, original price; user enters promotional price
    ↓
Clicks "Create Strategy"
    ↓
POST /api/price-adjustments/create with store_mapping_id, products, time_slots, etc.
    ↓
Backend validates, computes next_trigger_at, saves schedule
    ↓
Success; form resets
```

---

## 4.3 Manage Strategies Flow

```
User selects "Manage Strategies" tab
    ↓
GET /api/price-adjustments/?store_mapping_id=...
    ↓
List of schedules: name, order number, product count, time slots, next trigger, active/inactive
    ↓
User can view details (modal) or delete (deactivate schedule)
```

---

## 4.4 Background Workers (Always Running)

**Sync worker (e.g. every 5s):**

- Reads `sync_queue` for pending items.
- For each: load product, load store mapping, transform to Hipoink format, call Hipoink API, update sync_log, mark item success/failure.
- Fed by: Shopify webhooks (products/create, update, delete, inventory_levels/update) → DB → queue.

**Price scheduler (e.g. every 15s):**

- Loads schedules with `is_active=true` and `next_trigger_at <= now`.
- For each: get store timezone, check time slot (start vs end), apply or restore prices (Hipoink + Shopify), update `last_triggered_at` and `next_trigger_at`.

---

## 4.5 High-Level Data Flow Diagram

```
┌─────────────────┐
│  Shopify Store   │
└────────┬────────┘
         │ Install (OAuth) + Webhooks
         ▼
┌──────────────────┐
│  FastAPI Backend │
│  OAuth, Webhooks │
│  Store Mappings  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Supabase       │
│  store_mappings  │
│  products        │
│  sync_queue      │
│  price_adj...    │
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐  ┌────────────────┐
│ Sync   │  │ Price Scheduler│
│ Worker │  │ (every 15s)    │
└───┬────┘  └───────┬────────┘
    │               │
    ▼               ▼
┌────────────┐  ┌────────────┐
│ Hipoink ESL│  │  Shopify   │
│    API     │  │    API     │
└────────────┘  └────────────┘
```

---

# 5. Data Models & APIs

## 5.1 Store Mapping

- **source_system:** `"shopify"`
- **source_store_id:** shop domain
- **hipoink_store_code:** set at onboarding; required for pricing/sync targeting
- **metadata:** timezone, store_name, shopify_access_token, shopify_shop_domain, etc. (merged on update)

## 5.2 Price Adjustment Schedule

See [Schedule Model (Logical)](#33-schedule-model-logical) above. Stored in `price_adjustment_schedules`; `products` and `time_slots` are JSON.

## 5.3 Key Endpoints Summary

| Area | Method | Endpoint |
|------|--------|----------|
| Auth | GET | `/api/auth/me?shop=...` |
| Store mappings | GET | `/api/store-mappings/current?shop=...` |
| Store mappings | POST/PUT/GET list/GET by id | `/api/store-mappings/`, `/api/store-mappings/{id}` |
| Price adjustments | POST | `/api/price-adjustments/create` |
| Price adjustments | GET | `/api/price-adjustments/?store_mapping_id=...` |
| Products (search) | GET | `/api/products/search?shop=...&q=...` |
| Shopify OAuth | GET | `/auth/shopify`, `/auth/shopify/callback` |
| Webhooks | POST | `/webhooks/shopify/products/create|update|delete`, `/webhooks/shopify/inventory_levels/update` |

---

# 6. Environment & Running the System

## 6.2 Services to Run

1. **FastAPI backend** (e.g. port 8000): `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. **Workers:** `python -m app.workers` (sync worker + price scheduler)
3. **Shopify app frontend** (e.g. port 3000): `cd shopify-app && npm run dev`
4. **Shopify CLI** (dev): `cd shopify-app && shopify app dev` (tunnel + inject App Bridge)

---

## Summary

- **Shopify integration:** Webhook-driven product/inventory sync, multi-variant → one row per variant, HMAC verification, multi-tenant by shop domain; OAuth stores token in store mapping metadata.
- **User onboarding:** One-time collection of Hipoink store code, timezone, and optional store name via store mapping APIs; `needs_onboarding` drives UI until `hipoink_store_code` is set.
- **Time-based pricing:** Schedules with products, time slots, and repeat rules; scheduler runs every 15s, applies/restores prices at slot start/end in store timezone, updates Hipoink and Shopify.
- **User flows:** Install → OAuth → onboarding → Create/Manage Strategies; background sync worker and price scheduler keep ESL and Shopify in sync with no manual steps after setup.

This document is the single reference for Shopify integration, onboarding, time-based pricing, and end-to-end user flows in the ZKong-Demo / Hipoink ESL system.
