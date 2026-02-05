# Clover Cross-Process Token Refresh Fix

**Status:** Implementation plan for review.  
**Problem:** Web (initial sync) and Worker (polling) both refresh the same single-use token → second attempt gets 401 Invalid refresh token.  
**Consensus:** Claude Code, Gemini, and Cursor agree on root cause and options below.

---

## 1. Root Cause (Split-Brain Refresh)

| Process | Trigger | Behavior |
|--------|---------|----------|
| **Web (FastAPI)** | OAuth callback → `_trigger_clover_initial_sync()` | Runs initial sync in background; calls `sync_products_via_polling()` → `_ensure_valid_token()` → may refresh |
| **Worker** | Poll every 300s | Runs `sync_products_via_polling()` → `_ensure_valid_token()` → may refresh |

Both can decide “token expiring soon” and call Clover’s refresh endpoint. Clover’s refresh token is **single-use**: first call succeeds, second gets **401 Invalid refresh token**.  
`asyncio.Lock` only applies **inside one process**, so Web and Worker do not coordinate.

**Timeline:**
- T0 Web: OAuth callback saves new tokens.
- T1 Web: Background “initial sync” starts.
- T2 Web: `_ensure_valid_token()` → “expiring soon” → refresh (Token A → Token B).
- T3 Worker: Poll runs for same merchant.
- T4 Worker: `_ensure_valid_token()` → “expiring soon” → refresh (still using Token A).
- T5 Web: Clover returns new tokens → DB updated.
- T6 Worker: Clover returns 401 (Token A already used) → failure and retries.

---

## 2. Fix Options (Ranked)

| Option | Effort | Risk | When |
|--------|--------|------|------|
| **A: Skip refresh on initial sync** | Low | Low | **Do first** |
| **B: Move initial sync to worker** | Medium | Low | Optional, cleaner long-term |
| **C: Distributed lock (Postgres/Redis)** | High | Medium | Multiple worker instances |

---

## 3. Option A: Skip Refresh on Initial Sync (Recommended First)

**Idea:** The token used in initial sync was **just** issued by the OAuth callback. It does not need a refresh check. Only the **worker** should ever refresh; then the in-process lock is enough.

**Changes:**

1. **Adapter**  
   - Add an optional parameter to `sync_products_via_polling(store_mapping, *, skip_token_refresh: bool = False)`.  
   - When `skip_token_refresh=True`, do **not** call `_ensure_valid_token()`; use `store_mapping.metadata["clover_access_token"]` (and optionally a quick “token present” check).  
   - When `skip_token_refresh=False` (default), keep current behavior (call `_ensure_valid_token()`).

2. **Clover auth router**  
   - In `_trigger_clover_initial_sync()`, after fetching the store mapping, call:
     - `await adapter.sync_products_via_polling(store_mapping, skip_token_refresh=True)`  
   - So initial sync never triggers a refresh.

**Result:** Only the worker runs refresh logic → no cross-process race for the single-use token. Existing `asyncio.Lock` in the worker remains valid.

**Files to touch:**
- `app/integrations/clover/adapter.py`: add `skip_token_refresh` to `sync_products_via_polling`, branch on it before `_ensure_valid_token`.
- `app/routers/clover_auth.py`: pass `skip_token_refresh=True` when calling the adapter from `_trigger_clover_initial_sync`.

---

## 4. Option B: Move Initial Sync to Worker (Optional)

**Idea:** Do not run initial sync in the web process. After OAuth, only persist the store mapping (and maybe a “needs_initial_sync” flag). The worker, on its next poll, sees the new merchant and runs `sync_products_via_polling` once; only the worker ever refreshes.

**Pros:** Single process responsible for sync + refresh; no race by design.  
**Cons:** Slightly delayed first product sync (up to one poll interval).  
**Implementation:** Add optional flag on store_mapping or a small “pending_sync” table; worker checks it and clears after first sync. No change to refresh logic beyond “only worker runs it.”

---

## 5. Option C: Distributed Lock (Future)

**When:** Multiple worker instances or need strict coordination across Web + Worker.

**Options:**
- **Postgres advisory lock** (e.g. keyed by merchant id) so only one process holds the lock for “clover_refresh:{merchant_id}” while refreshing.  
- **Redis lock** if you introduce Redis.

**Note:** Option A (or B) removes the current race without a distributed lock. Option C is for scaling or stricter guarantees.

---

## 6. Optional: Verify Expiration Logic (Gemini)

If tokens are “just created” but `is_token_expiring_soon()` is still True, check:

- Clover may return expiration in **milliseconds**; our code may expect **seconds** (or vice versa).  
- Run (adjust id to your mapping):

```sql
SELECT 
  metadata->>'clover_access_token_expiration' AS expiration,
  metadata->>'clover_refresh_token_expiration' AS refresh_exp
FROM store_mappings 
WHERE id = '5f4aa949-538b-40ec-ad20-048d990a4880';
```

If values are in ms (e.g. 13 digits), ensure `is_token_expiring_soon()` normalizes (e.g. divide by 1000) consistently. This is a secondary check; Option A fixes the main failure even if threshold is slightly off.

---

## 7. Implementation Checklist (Option A Only)

- [ ] **adapter.py:** Add `skip_token_refresh: bool = False` to `sync_products_via_polling()`.  
- [ ] **adapter.py:** If `skip_token_refresh` is True, skip `_ensure_valid_token()` and use token from `store_mapping.metadata` (with a simple presence check).  
- [ ] **clover_auth.py:** In `_trigger_clover_initial_sync()`, call `sync_products_via_polling(store_mapping, skip_token_refresh=True)`.  
- [ ] **Tests / manual:** Run OAuth → initial sync (web) + worker poll; confirm only one refresh in logs and no 401.  
- [ ] **(Optional)** Run the SQL above and confirm expiration parsing if you still see “expiring soon” right after OAuth.

---

## 8. Summary

- **Cause:** Web (initial sync) and Worker (poll) both refresh the same single-use Clover token; in-process lock does not help across processes.  
- **Immediate fix:** Option A — skip refresh on initial sync so only the worker refreshes.  
- **Later:** Option B (initial sync in worker) and/or Option C (distributed lock) if needed.  
- **Doc:** This file is the implementation plan for review; implement Option A first, then re-verify in production.
