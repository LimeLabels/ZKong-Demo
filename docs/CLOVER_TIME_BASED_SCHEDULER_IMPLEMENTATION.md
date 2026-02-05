# Clover Time-Based Price Scheduler — Implementation Guide

This guide describes how to add **Clover** as a first-class option in the time-based price scheduler, so it behaves the same as **Square** and **NCR**: users can pick a Clover store, search/select products, and create schedules that apply and restore prices at the specified times.

**Scope:** Backend (API, scheduler worker, Clover API client/adapter) and frontend (external-tool Schedule UI). No coding in this doc — implementation steps and code snippets only.

---

## 1. Current behavior (Square / NCR)

- **Store list:** User’s stores come from `/api/auth/my-stores`; each store has `source_system` (e.g. `square`, `ncr`).
- **Products:** For the selected store, products are loaded from `/api/products/my-products` (filtered by that store’s `source_system` and `source_store_id`).
- **Schedule form:** Platform is derived from the selected store’s `source_system` (`square` or `ncr`). Only when platform is Square or NCR, the product search + multi-select table is shown.
- **Product identifier in schedule:**  
  - **Square:** `pc` = Square variation ID (`source_variant_id`), because Square updates by catalog object ID.  
  - **NCR:** `pc` = item code / barcode.  
  - Both store `original_price` and use it for restore.
- **Backend create:** `POST /api/price-adjustments/create` receives `products` with `pc`, `pp`, `original_price`. For NCR only, there is an extra “pre-schedule” step after creating the schedule; Square has no pre-schedule.
- **Scheduler worker:** Periodically evaluates schedules; when a time slot starts it calls `_apply_promotional_prices`, when it ends it calls `_restore_original_prices`. Both:
  - Update **Hipoink** (using barcode).
  - Then, if the store is **Square**, call `_update_square_prices`; if **NCR**, call `_update_ncr_prices`.

So the pattern is: one product list and one schedule flow; the only differences are how `pc` is set (variant_id vs barcode) and which POS update method is called (Square vs NCR). Clover will follow the same pattern.

---

## 2. Goal for Clover

- Clover appears as a **platform option** in the schedule UI (same as Square and NCR).
- When the user selects a **Clover store**, the UI shows the same **product search + multi-select** and uses the same schedule form (name, dates, repeat, time slots, multiplier).
- Schedules that belong to a Clover store **apply** and **restore** prices on **Clover** (and Hipoink) at the right times, with the same semantics as Square.

---

## 3. Backend implementation (step-by-step)

### 3.1. Clover API: update single item price

- **Endpoint:** `PATCH /v3/merchants/{mId}/items/{itemId}` (single-item update). Price is in **cents**.
- **Location:** `app/integrations/clover/api_client.py`

**Step 3.1.1** — Add a method to `CloverAPIClient`:

```python
async def update_item(
    self,
    merchant_id: str,
    item_id: str,
    price_cents: int,
    **kwargs: Any,  # optional: name, cost, etc.
) -> Dict[str, Any]:
    """
    Update an item's price (and optionally other fields).
    PATCH /v3/merchants/{mId}/items/{itemId}
    Price must be in cents.
    """
```

- Build body with at least `{"price": price_cents}`; merge in `kwargs` for other fields if needed.
- Use `PATCH` to the item URL; return the JSON response or raise `CloverAPIError` on non-2xx.

**Step 3.1.2** — Ensure `item_id` is sent without the `I:` prefix if the API expects a raw ID (our transformer uses `source_id` as the raw id; confirm from existing `get_item` usage).

---

### 3.2. Clover adapter: update price (and token)

- **Location:** `app/integrations/clover/adapter.py`

**Step 3.2.1** — Add a public method used by the price scheduler, e.g.:

```python
async def update_item_price(
    self,
    store_mapping: StoreMapping,
    item_id: str,
    price_dollars: float,
) -> None:
```

- Resolve merchant ID from `store_mapping.source_store_id`.
- Call `_ensure_valid_token(store_mapping)` to get a valid access token (refresh if needed).
- Convert `price_dollars` to cents (int).
- Instantiate `CloverAPIClient(access_token=token)` and call `update_item(merchant_id, item_id, price_cents)`.
- On success, optionally update the local product price in the DB (mirror Square’s “update local product price in database immediately” if you store price in products table).

**Step 3.2.2** — Reuse the same `_ensure_valid_token` and error handling as in `sync_products_via_polling` so that scheduler-triggered updates are not blocked by expired tokens.

---

### 3.3. Product identifier for Clover in schedules

- In the **DB**, Clover products have `source_id` = Clover item ID (string), and `source_variant_id` = None (one price per item).
- For the **scheduler**, the POS update must use the **Clover item ID** to call `PATCH .../items/{itemId}`. So in the schedule’s `products_data`, **`pc` for Clover should be the Clover item ID**, i.e. `source_id` (same as `product_id` in the frontend `ProductSearchResult`).

**Convention:**

- **Square:** `pc` = `source_variant_id` (variation ID).  
- **NCR:** `pc` = barcode / item code.  
- **Clover:** `pc` = `source_id` (Clover item ID).

No backend change is required for “what is pc” in the create endpoint — the backend just stores whatever `pc` the frontend sends. The frontend will send `source_id` for Clover (see below).

---

### 3.4. Price scheduler: resolve barcode for Hipoink (Clover)

- **Location:** `app/workers/price_scheduler.py`

In both `_apply_promotional_prices` and `_restore_original_prices`, today we resolve `barcode` from `product_data["pc"]` for **Square** (because `pc` is object_id), and for **NCR** we use `pc` as the item code. We need a **Clover** branch that behaves like Square: `pc` is the Clover item ID, and we need the product’s **barcode** for Hipoink.

**Step 3.4.1 — In `_apply_promotional_prices`**, after the existing `if store_mapping.source_system == "square":` block that sets `barcode` from the DB, add:

```python
# For Clover, product_data["pc"] is the Clover item ID (source_id)
if store_mapping.source_system == "clover":
    products_by_source = self.supabase_service.get_products_by_source_id(
        "clover", product_data["pc"], source_store_id=store_mapping.source_store_id
    )
    existing_product = products_by_source[0] if products_by_source else None
    if existing_product and existing_product.barcode:
        barcode = existing_product.barcode
    else:
        logger.warning(
            "Could not find barcode for Clover product",
            clover_item_id=product_data["pc"],
            schedule_id=str(schedule.id),
        )
```

Use the same multi-tenant pattern as Square: resolve by `source_system`, `source_id`, and `source_store_id` so the product belongs to the same merchant.

**Step 3.4.2 — In `_restore_original_prices`**, add the same Clover branch for resolving `barcode` from `product_data["pc"]` (Clover item ID) before building Hipoink product list.

---

### 3.5. Price scheduler: call Clover price update

- **Location:** `app/workers/price_scheduler.py`

**Step 3.5.1 — `_apply_promotional_prices`**  
After the block that calls `_update_square_prices`, add:

```python
# Update Clover prices if store mapping is for Clover
if store_mapping.source_system == "clover":
    await self._update_clover_prices(
        updated_products_data,
        store_mapping,
    )
```

**Step 3.5.2 — `_restore_original_prices`**  
After the block that calls `_update_square_prices(..., use_original=True)`, add:

```python
if store_mapping.source_system == "clover":
    await self._update_clover_prices(
        products_data,
        store_mapping,
        use_original=True,
    )
```

**Step 3.5.3 — Implement `_update_clover_prices`** in the same file, mirroring `_update_square_prices` / `_update_ncr_prices`:

- Signature: `(self, products_data: list, store_mapping: StoreMapping, use_original: bool = False)`.
- If `store_mapping.source_system != "clover"`, return immediately.
- Instantiate `CloverIntegrationAdapter` (or get it from a shared place if you refactor).
- For each `product_data` in `products_data`:
  - `item_id = product_data["pc"]` (Clover item ID).
  - Price: `float(product_data.get("original_price", 0))` if `use_original` else `float(product_data.get("pp", 0))`.
  - Validate price > 0; on failure log and continue.
  - Call `await clover_adapter.update_item_price(store_mapping, item_id, price_dollars)`.
- Wrap in try/except; log errors but do not fail the whole run (same as NCR/Square).

---

### 3.6. Pre-schedule (NCR-only; no change for Clover)

- **Location:** `app/routers/price_adjustments.py`

Today, after creating a schedule, we only run **NCR** pre-schedule logic. **Do not add** a Clover pre-schedule step unless you introduce an NCR-like “scheduled price” concept for Clover. For “same effect as Square,” Clover should **not** do pre-schedule — only apply/restore at trigger times.

---

### 3.7. Products API

- **Location:** `app/routers/products.py`

- **`GET /api/products/search`** already takes `source_system` and `shop`; it uses `get_store_mapping(source_system, shop)` and `get_products_by_system(source_system, source_store_id)`. As long as `source_system=clover` and `shop` = Clover merchant ID are supported by `get_store_mapping`, no change is required for search.
- **`GET /api/products/my-products`** uses the authenticated user’s store (from store_mappings where `metadata.user_id` = current user) and then `get_products_by_system(source_system, source_store_id)`. So for a user linked to a **Clover** store mapping, `my-products` will already return Clover products. **No change required** for listing products for the scheduler.

---

## 4. Frontend implementation (external-tool, step-by-step)

### 4.1. Platform type and store → platform mapping

- **File:** `external-tool/src/components/ScheduleCalendar.tsx`

**Step 4.1.1** — Extend the platform type to include Clover:

```ts
// Before
platform: 'ncr' | 'square' | ''

// After
platform: 'ncr' | 'square' | 'clover' | ''
```

**Step 4.1.2** — In the `useEffect` that sets form data from the selected store, extend the `systemMap` so Clover stores set `platform: 'clover'`:

```ts
const systemMap: Record<string, 'ncr' | 'square' | 'clover' | ''> = {
  'ncr': 'ncr',
  'square': 'square',
  'shopify': 'square',
  'clover': 'clover',
}
```

---

### 4.2. Show product UI for Clover

- **File:** `external-tool/src/components/ScheduleCalendar.tsx`

Everywhere the UI gates on “Square or NCR” for the **product search + multi-select** and related behavior, add `|| formData.platform === 'clover'`. Examples:

- Condition for fetching products: e.g. `(formData.platform === 'square' || formData.platform === 'ncr' || formData.platform === 'clover')` when deciding to call `my-products` and when to clear selection on search change.
- Condition for showing the product search + table: replace `(formData.platform === 'square' || formData.platform === 'ncr')` with the same triple condition so the block renders for Clover.
- Validation: “Select at least one product” when platform is Square, NCR, or Clover.
- Any other place that checks `formData.platform === 'square' || formData.platform === 'ncr'` for enabling the schedule form or submit should include `formData.platform === 'clover'`.

Search and limit params for `my-products` can stay as-is; the backend already filters by the user’s store (Clover included).

---

### 4.3. Product payload: `pc` for Clover

- **File:** `external-tool/src/components/ScheduleCalendar.tsx`

When building `productsPayload` for `POST /api/price-adjustments/create`:

- **Square:** `pc = p.variant_id` (source_variant_id).
- **NCR:** `pc = p.barcode || p.sku || ''`.
- **Clover:** `pc` must be the **Clover item ID** so the scheduler can call `PATCH .../items/{itemId}`. In `ProductSearchResult`, that is `product_id` (which maps to `source_id`). So:

```ts
const pc =
  formData.platform === 'square'
    ? (p.variant_id || '')
    : formData.platform === 'clover'
      ? (p.product_id || '')   // Clover item ID (source_id)
      : (p.barcode || p.sku || '')
```

- For Clover, **do not** use `variant_id` (it’s null); use `product_id` (source_id).

---

### 4.4. Validation for Clover products

- **File:** `external-tool/src/components/ScheduleCalendar.tsx`

Square has a check that every selected product has a variation ID. For Clover, require that every selected product has a `product_id` (source_id):

```ts
if (formData.platform === 'clover') {
  const missingIds = selectedProducts.filter((p) => !p.product_id)
  if (missingIds.length > 0) {
    const names = missingIds.map((p) => p.title || p.id).join(', ')
    throw new Error(
      `These Clover products are missing item IDs and cannot be scheduled: ${names}. ` +
        'Please ensure products are synced from Clover before creating a schedule.'
    )
  }
}
```

---

### 4.5. Multi-select and multiplier behavior

- **File:** `external-tool/src/components/ScheduleCalendar.tsx`

- Where you treat “multi-select platform” (e.g. defaulting to percentage mode when 2+ products selected), extend the condition to include `formData.platform === 'clover'`.
- Where you sync `originalPrice` / `price` from the single selected product, include Clover in the same condition as Square/NCR so one selected Clover product fills price fields correctly.

---

### 4.6. Optional: store name for Clover

- **File:** `app/routers/auth.py` (or wherever `my-stores` builds the list)

If you want a friendly label for Clover stores in the dropdown, add a branch for `source_system === 'clover'` when setting `store_name` (e.g. from `metadata.merchant_name` or `source_store_id`). This is optional and does not affect scheduler behavior.

---

## 5. End-to-end flow checklist

- User has a Clover store connected (OAuth) and linked to their user (e.g. `metadata.user_id`).
- User opens the schedule calendar and selects that Clover store → platform becomes `clover`.
- Product search + multi-select shows Clover products from `my-products`.
- User selects products, sets name/dates/times/multiplier and creates the schedule.
- Payload has `pc` = Clover item ID (`source_id`), `pp` and `original_price` as for Square/NCR.
- Worker, at slot start, runs `_apply_promotional_prices` → Hipoink + `_update_clover_prices` (using `pc` as item ID and token refresh if needed).
- Worker, at slot end, runs `_restore_original_prices` → Hipoink + `_update_clover_prices(..., use_original=True)`.

---

## 6. Files to touch (summary)

| Area | File | Changes |
|------|------|--------|
| Clover API | `app/integrations/clover/api_client.py` | Add `update_item(merchant_id, item_id, price_cents, **kwargs)`. |
| Clover adapter | `app/integrations/clover/adapter.py` | Add `update_item_price(store_mapping, item_id, price_dollars)` using `_ensure_valid_token` and API client. |
| Scheduler | `app/workers/price_scheduler.py` | Resolve barcode for Clover in apply/restore; add `_update_clover_prices`; call it from apply and restore. |
| Frontend | `external-tool/src/components/ScheduleCalendar.tsx` | Platform type + systemMap include `clover`; show product UI for Clover; set `pc` from `product_id` for Clover; validate Clover product_id; include Clover in multi-select/multiplier logic. |
| Optional | `app/routers/auth.py` (my-stores) | Friendly store name for Clover. |

No change to `price_adjustments.py` for Clover (no pre-schedule). No change to `products.py` if `get_store_mapping("clover", merchant_id)` already works and products are synced into the DB for that store.

---

## 7. Testing suggestions

1. **Unit:** Clover API client `update_item` with a mock HTTP client (price in cents, correct URL and body).
2. **Unit:** Adapter `update_item_price` with a mock client and store mapping (token refresh path and happy path).
3. **Integration:** Create a Clover schedule via API (products with `pc` = Clover item IDs), then run the scheduler in a test harness and assert Clover PATCH is called with correct prices (and optionally Hipoink).
4. **E2E:** In the external-tool UI, select Clover store → search products → select one or more → create schedule → (in test env) trigger slot and confirm Clover item prices change and restore.

This gives you a robust, step-by-step implementation path so Clover behaves like Square and NCR in the time-based scheduler, with code snippets you can paste and adapt.
