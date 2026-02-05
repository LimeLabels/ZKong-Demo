# Clover Token Refresh: Implementation Plan

**Status:** Option B implemented (on-demand refresh in adapter).

---

## 1. Problem (agreed by Cursor, Claude, Gemini)

- The **token refresh scheduler** runs **once every 24 hours**, not every 5 minutes.
- If Clover access tokens are short-lived (e.g. 30 min), a token can expire soon after creation.
- With a 24h scheduler, we might not run again until the next day → **long period of failed syncs** (e.g. ~23.5 hours).
- Changing **only** the refresh threshold (e.g. to 15 min) does **not** fix this while the scheduler stays at 24h.

---

## 2. Two Possible Approaches

| Approach | What it does | Pros | Cons |
|----------|--------------|------|------|
| **A. Faster scheduler** | Run token refresh scheduler every **10 min** and set threshold to **15 min**. | Small change; no adapter logic. | Still depends on scheduler timing; more refresh checks per day. |
| **B. On-demand refresh** | Before **each** Clover API use (e.g. each sync), check token and refresh if expiring within 15 min. Keep 24h scheduler as backup. | No gap; self-healing; works regardless of token lifetime. | Requires adapter changes and a bit more code. |

**Recommendation:** **Option B (on-demand refresh)** — Cursor and Claude both recommend it; Gemini calls it the “gold standard.” Option A is acceptable if you prefer minimal change for now.

---

## 3. Proposed Implementation (Option B – On-Demand Refresh)

We will implement **on-demand refresh** so every sync uses a valid token. The 24h scheduler stays as a backup.

### 3.1 Token refresh service (no change)

- Keep `REFRESH_THRESHOLD_SECONDS = 24 * 3600` in the **scheduler** (it only runs daily).
- Reuse `CloverTokenRefreshService.is_token_expiring_soon(expiration, threshold_seconds=...)` with a **15-minute** threshold (900 seconds) **only** in the adapter’s on-demand check.

### 3.2 Clover adapter: add `_ensure_valid_token()`

- **File:** `app/integrations/clover/adapter.py`
- **New method:** `_ensure_valid_token(store_mapping: StoreMapping) -> Optional[str]`
  - Read `clover_access_token` and `clover_access_token_expiration` from `store_mapping.metadata`.
  - If no token, return `None`.
  - If token is expiring within **15 minutes** (call `CloverTokenRefreshService().is_token_expiring_soon(expiration, threshold_seconds=900)`):
    - Call `CloverTokenRefreshService().refresh_token_and_update(store_mapping)`.
    - If success and updated mapping returned, return `updated_mapping.metadata.get("clover_access_token")`.
    - If refresh fails, return the existing token (so the caller can try and get a clear API error if it’s expired).
  - Otherwise return the existing `clover_access_token`.

### 3.3 Clover adapter: use token from `_ensure_valid_token()` in sync

- **File:** `app/integrations/clover/adapter.py`
- In `sync_products_via_polling()` (and any other path that calls Clover with this store’s token):
  - At the start, call `access_token = await self._ensure_valid_token(store_mapping)`.
  - If `access_token` is `None`, log, set errors in the result, and return (no API calls).
  - Pass `access_token` into `CloverAPIClient(access_token=access_token)` (or equivalent) so **every** Clover API call in that sync uses this validated token.
- No change to how the **worker** invokes the adapter (it still calls `sync_products_via_polling(mapping)` once per store per poll).

### 3.4 Scheduler (no change)

- **File:** `app/workers/token_refresh_scheduler.py`
- Leave **as-is**: run every 24 hours, use current threshold.
- It remains a **backup** for tokens that might not have been refreshed during sync (e.g. store not synced for a long time).

### 3.5 Optional: 15-min threshold constant for on-demand use

- In `token_refresh.py` we can add a constant, e.g. `ON_DEMAND_REFRESH_THRESHOLD_SECONDS = 15 * 60`, and use it in the adapter when calling `is_token_expiring_soon(..., threshold_seconds=ON_DEMAND_REFRESH_THRESHOLD_SECONDS)` so the “15 min” is defined in one place.

---

## 4. What we will not do (unless you ask)

- We will **not** change the token refresh scheduler interval (e.g. to 10 min) unless you explicitly choose **Option A** instead.
- We will **not** change `REFRESH_THRESHOLD_SECONDS` in the scheduler to 15 min as a standalone “fix” (it doesn’t fix the gap with a 24h run).
- We will **not** assume or document a specific Clover token lifetime (e.g. 30 min); we only use “expiring within 15 min” as the trigger for refresh.

---

## 5. Files to touch (Option B)

| File | Action |
|------|--------|
| `app/integrations/clover/adapter.py` | Add `_ensure_valid_token()`; in `sync_products_via_polling()` (and any other Clover API path for this store), get token via `_ensure_valid_token()` and use it for the client. |
| `app/integrations/clover/token_refresh.py` | Optional: add `ON_DEMAND_REFRESH_THRESHOLD_SECONDS = 15 * 60` and use it in adapter. |
| `app/workers/token_refresh_scheduler.py` | No change. |

---

## 6. Approval

- If you approve **Option B** as above, implementation will follow this plan.
- If you prefer **Option A** (10-min scheduler + 15-min threshold, no adapter changes), say so and we’ll switch the plan to that instead.
