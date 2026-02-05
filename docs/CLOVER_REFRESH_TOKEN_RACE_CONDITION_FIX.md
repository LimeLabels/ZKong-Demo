# Clover Refresh Token Race Condition & Single-Use Token Issue

## Problem Summary

**Symptom:** Clover token refresh succeeds once, then immediately fails on subsequent attempts with `401 Unauthorized: Invalid refresh token`, even though no manual changes were made to the store mapping.

**Root Cause:** Two critical issues:
1. **Clover refresh tokens are single-use** — Each refresh token becomes invalid immediately after being used to generate a new token pair
2. **Race condition in token refresh logic** — Multiple concurrent refresh attempts can use the same (now-invalid) refresh token

### ⚠️ Important: Initial OAuth Failure Issue

**Critical Finding:** Some merchants may have **never successfully completed initial OAuth** due to failed token exchange during onboarding. If you see errors like:

```
{"detail":"Failed to exchange authorization code for tokens"}
```

This means the merchant's store mapping was created **without valid tokens** from the start. The refresh fixes below will help **future** refresh cycles, but merchants with failed initial OAuth need to **re-authorize** your app.

**Action Required:**
- Check Railway environment variables: `CLOVER_APP_SECRET` and `CLOVER_APP_ID` must be set correctly
- Delete stale store mappings for merchants with failed OAuth
- Have those merchants reconnect through Clover App Market

---

## Technical Analysis

### Clover's Refresh Token Behavior

According to [Clover's official documentation](https://docs.clover.com/dev/docs/refresh-access-tokens):

> **"Limitations on refresh token usage—Refresh token is for single use and becomes invalid immediately after a new access_token and refresh_token pair is generated using the /oauth/v2/refresh endpoint."**

**Key points:**
- When you call `/oauth/v2/refresh` with a refresh token, Clover returns a **NEW** refresh token
- The **OLD** refresh token becomes invalid **immediately** (not after some delay)
- You **MUST** use the new refresh token for the next refresh attempt
- Clover also limits the number of active refresh tokens per merchant

### Current Code Flow

**File:** `app/integrations/clover/adapter.py` → `_ensure_valid_token()`

```python
async def _ensure_valid_token(self, store_mapping: StoreMapping) -> Optional[str]:
    # ... checks if token expiring soon ...
    success, updated_mapping = await refresh_service.refresh_token_and_update(store_mapping)
    if success and updated_mapping and updated_mapping.metadata:
        return updated_mapping.metadata.get("clover_access_token")
    # Falls back to old token if refresh fails
    return access_token
```

**File:** `app/integrations/clover/token_refresh.py` → `refresh_token_and_update()`

```python
async def refresh_token_and_update(self, store_mapping: StoreMapping):
    # Reads refresh_token from store_mapping.metadata (in-memory object)
    refresh_token = store_mapping.metadata.get("clover_refresh_token")
    
    # Calls Clover API with this refresh_token
    success, new_token_data = await self.refresh_token(store_mapping)
    
    # Updates DB with new tokens
    updated = await asyncio.to_thread(_update_store_mapping_metadata_sync, ...)
    return True, updated
```

### The Race Condition Scenario

**What happens in your logs:**

1. **11:52:27** — First refresh succeeds:
   - `_ensure_valid_token()` detects token expiring soon
   - Calls `refresh_token_and_update()` with `store_mapping` object containing **old refresh_token**
   - Clover API accepts old refresh_token, returns **new** access_token + refresh_token
   - DB updated with new tokens ✅
   - Returns updated StoreMapping object

2. **11:57:27** — Second refresh attempt fails:
   - `_ensure_valid_token()` called again (token still considered "expiring soon" within 15-min threshold)
   - **Problem:** The `store_mapping` object passed to `refresh_token_and_update()` might still have the **old refresh_token** in memory
   - OR: If the refresh_token wasn't properly saved to DB, or if there's a race where two refreshes happen simultaneously
   - Calls Clover API with **old refresh_token** (which is now invalid after first refresh)
   - Clover returns `401 Invalid refresh token` ❌

**Why the old refresh_token might still be used:**

1. **Stale in-memory object:** The `store_mapping` passed to `_ensure_valid_token()` is from the worker's initial fetch. Even after DB update, the in-memory object still has old metadata.

2. **Concurrent refresh attempts:** If two syncs trigger refresh simultaneously:
   - Both read the same refresh_token from DB
   - Both call Clover API with the same refresh_token
   - First succeeds, second fails (token already used)

3. **Refresh token not in response:** If Clover's response doesn't include `refresh_token` (edge case), line 176 falls back to old token:
   ```python
   "refresh_token": data.get("refresh_token") or refresh_token,  # Falls back to OLD token!
   ```

---

## Solution

### Fix 1: Always Re-Fetch Store Mapping After Refresh

**Problem:** Using stale in-memory `store_mapping` object with old refresh_token.

**Fix:** After successful refresh, always re-fetch the store mapping from DB before using it, OR ensure the refresh function always uses the refresh_token from the DB (not the in-memory object).

**Location:** `app/integrations/clover/token_refresh.py`

**Change in `refresh_token()` method:**

```python
async def refresh_token(self, store_mapping: StoreMapping) -> Tuple[bool, Optional[Dict[str, Any]]]:
    # ... existing validation ...
    
    # CRITICAL FIX: Re-fetch refresh_token from DB to avoid stale in-memory data
    # This ensures we always use the latest refresh_token, even if another process just updated it
    fresh_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping.id)
    if not fresh_mapping or not fresh_mapping.metadata:
        logger.error("Could not re-fetch store mapping for refresh", store_mapping_id=str(store_mapping.id))
        return False, None
    
    # Logging for debugging (per Claude Code review)
    logger.debug(
        "Re-fetched store mapping for refresh",
        store_mapping_id=str(store_mapping.id),
        merchant_id=store_mapping.source_store_id,
        has_refresh_token=bool(fresh_mapping.metadata.get("clover_refresh_token")),
    )
    
    refresh_token = fresh_mapping.metadata.get("clover_refresh_token")
    if not refresh_token:
        logger.error("No Clover refresh token in fresh store mapping", ...)
        return False, None
    
    # Use fresh refresh_token for API call
    body = {
        "client_id": settings.clover_app_id,
        "refresh_token": refresh_token,  # Use fresh token from DB
    }
    # ... rest of refresh logic ...
```

### Fix 2: Ensure Refresh Token is Always Updated

**Problem:** If Clover doesn't return a refresh_token in response, we fall back to old token (which is now invalid).

**Fix:** If Clover doesn't return a new refresh_token, treat it as an error (don't fall back to old token).

**Location:** `app/integrations/clover/token_refresh.py` line 176

**Change:**

```python
data = response.json()
access_token = data.get("access_token")
if not access_token:
    logger.error("No access_token in Clover refresh response", ...)
    return False, None

# CRITICAL FIX: Clover refresh tokens are single-use. We MUST get a new refresh_token.
# If Clover doesn't return one, the old token is invalid and we can't continue.
new_refresh_token = data.get("refresh_token")
if not new_refresh_token:
    logger.error(
        "No refresh_token in Clover refresh response - old token is now invalid",
        store_mapping_id=str(store_mapping.id),
        merchant_id=store_mapping.source_store_id,
    )
    return False, None  # Don't fall back to old token - it's invalid!

new_token_data = {
    "access_token": access_token,
    "refresh_token": new_refresh_token,  # Always use new token from response
    "access_token_expiration": data.get("access_token_expiration"),
    "refresh_token_expiration": data.get("refresh_token_expiration"),
}
```

### Fix 3: Add Refresh Lock to Prevent Concurrent Refreshes

**Problem:** Multiple syncs can trigger refresh simultaneously, both using the same refresh_token.

**Fix:** Add a per-merchant lock to ensure only one refresh happens at a time.

**⚠️ Scaling Limitation:** `asyncio.Lock` only works **within a single process**. If Railway scales to multiple worker instances, they won't see each other's locks. For current single-instance deployments, this is sufficient. For future multi-instance scaling, consider a distributed lock (Redis or DB-based advisory lock).

**Solution Tiers Comparison:**

| Solution Tier | Concurrency Protection | Scaling Limit | When to Use |
|---------------|------------------------|---------------|-------------|
| **Current (Broken)** | None | Fails immediately on retry | ❌ Never |
| **New (Fix 3)** | `asyncio.Lock` | Perfect for 1 server / many tasks | ✅ Current single-instance deployments |
| **Future (Scaling)** | Redis / DB Advisory Lock | Works across 100+ servers | ✅ When scaling to multiple worker instances |

**Location:** `app/integrations/clover/token_refresh.py`

**Add at module level:**

```python
import asyncio
from typing import Dict

# Per-merchant refresh locks to prevent concurrent refresh attempts
_refresh_locks: Dict[str, asyncio.Lock] = {}
_refresh_locks_lock = asyncio.Lock()  # Lock for managing the locks dict

async def _get_refresh_lock(merchant_id: str) -> asyncio.Lock:
    """Get or create a lock for this merchant's refresh operations."""
    async with _refresh_locks_lock:
        if merchant_id not in _refresh_locks:
            _refresh_locks[merchant_id] = asyncio.Lock()
        return _refresh_locks[merchant_id]
```

**Modify `refresh_token_and_update()`:**

```python
async def refresh_token_and_update(self, store_mapping: StoreMapping):
    merchant_id = store_mapping.source_store_id
    
    # Acquire merchant-specific lock to prevent concurrent refreshes
    lock = await _get_refresh_lock(merchant_id)
    
    async with lock:
        # Now only one refresh can happen at a time for this merchant
        last_error: Optional[str] = None
        new_token_data: Optional[Dict[str, Any]] = None
        
        # Re-fetch store mapping to get latest refresh_token from DB
        # CRITICAL: Must re-fetch inside the lock to ensure we have the absolute latest token
        fresh_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping.id)
        if not fresh_mapping:
            logger.error("Could not fetch fresh store mapping for refresh", ...)
            return False, None
        
        # Use fresh mapping for refresh
        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            # Note: refresh_token() will also re-fetch, but we do it here too for extra safety
            success, new_token_data = await self.refresh_token(fresh_mapping)
            if success and new_token_data:
                break
            # ... retry logic ...
        
        # ... rest of update logic ...
```

### Fix 4: Update `_ensure_valid_token` to Use Fresh Mapping

**Problem:** `_ensure_valid_token` uses the passed `store_mapping` object, which might be stale.

**Fix:** After refresh succeeds, re-fetch the mapping from DB before returning the token.

**Location:** `app/integrations/clover/adapter.py`

**Change:**

```python
async def _ensure_valid_token(self, store_mapping: StoreMapping) -> Optional[str]:
    # ... existing checks ...
    
    if refresh_service.is_token_expiring_soon(...):
        logger.info("Clover token expiring soon, refreshing before API call", ...)
        success, updated_mapping = await refresh_service.refresh_token_and_update(store_mapping)
        
        if success and updated_mapping and updated_mapping.metadata:
            # CRITICAL FIX: Use the updated_mapping returned from refresh (it has fresh tokens)
            # Don't fall back to old store_mapping object
            return updated_mapping.metadata.get("clover_access_token")
        
        logger.warning("Clover token refresh failed, using existing token", ...)
    
    # Only return existing token if refresh wasn't needed or failed
    return access_token
```

---

## Implementation Priority

**Critical (must fix):**
1. ✅ **Fix 2:** Always require new refresh_token from Clover response (don't fall back to old token)
2. ✅ **Fix 1:** Re-fetch store mapping from DB before refresh to get latest refresh_token

**Important (prevents race conditions):**
3. ✅ **Fix 3:** Add per-merchant refresh lock to prevent concurrent refreshes
4. ✅ **Fix 4:** Ensure `_ensure_valid_token` uses the updated mapping returned from refresh

---

## Pre-Implementation Checklist

**Before implementing fixes, address these issues:**

1. **✅ Verify Environment Variables:**
   - Check Railway dashboard: `CLOVER_APP_SECRET` is set and correct
   - Check Railway dashboard: `CLOVER_APP_ID` is set and correct
   - Verify environment matches (sandbox vs production URLs)

2. **✅ Fix Initial OAuth Failures:**
   - Review `app/routers/clover_auth.py` callback endpoint
   - Check for redirect URI mismatches between Clover dashboard and code
   - Delete stale store mappings for merchants with failed OAuth (e.g., `YA1H3C787QSC1`)
   - Have affected merchants re-authorize through Clover App Market

3. **✅ Verify Database Update Pattern:**
   - Confirm `_update_store_mapping_metadata_sync()` uses atomic updates
   - Test that JSONB metadata updates don't have race conditions

## Testing Checklist

After implementing fixes:

1. **Single refresh test:**
   - Onboard a merchant (with valid OAuth exchange)
   - Wait for token to expire (or manually set expiration to near future)
   - Trigger sync and verify refresh succeeds
   - Verify new tokens are saved to DB

2. **Concurrent refresh test:**
   - Trigger multiple syncs simultaneously (e.g., via webhook + polling)
   - Verify only one refresh happens (others wait for lock)
   - Verify all syncs succeed after refresh completes

3. **Refresh token rotation test:**
   - Refresh token multiple times in sequence
   - Verify each refresh uses the NEW refresh_token from previous refresh
   - Verify old refresh_tokens become invalid (can't reuse them)

4. **Edge case test:**
   - If Clover response doesn't include refresh_token, verify we fail gracefully
   - Verify we don't fall back to old (invalid) refresh_token

5. **Initial OAuth test:**
   - Test complete onboarding flow from start to finish
   - Verify tokens are saved correctly after OAuth callback
   - Verify refresh works immediately after onboarding

---

## Additional Notes

### Why This Wasn't Caught Earlier

- **Development testing:** Tokens might not expire frequently enough to trigger the race condition
- **Single merchant testing:** Race condition only appears with concurrent requests or rapid successive refreshes
- **Clover documentation:** The "single-use" limitation isn't immediately obvious unless you read the docs carefully

### Related Clover Limitations

From Clover docs:
- **Token limit:** Clover limits active refresh tokens per merchant. If limit exceeded, older tokens become invalid.
- **Dynamic expiration:** Token expiration dates are Unix timestamps and vary based on generation time.

### Database Update Safety (Per Gemini Review)

**Important:** Ensure DB updates are atomic. Avoid read-modify-write patterns:

```python
# ❌ Dangerous: read-modify-write pattern
mapping = get_mapping(id)
mapping.metadata["clover_refresh_token"] = new_token
update_mapping(mapping)

# ✅ Safer: single atomic operation
supabase.table("store_mappings").update({
    "metadata": {**existing_metadata, "clover_refresh_token": new_token, ...}
}).eq("id", mapping_id).execute()
```

The current `_update_store_mapping_metadata_sync()` function uses `.update()` which should be atomic, but verify your Supabase client handles JSONB updates correctly.

### Monitoring Recommendations

After fix is deployed, monitor:
- Refresh success rate (should be ~100% after fix)
- Frequency of "Invalid refresh token" errors (should drop to near zero)
- Concurrent refresh attempts (should be serialized by lock)
- Initial OAuth exchange success rate (should catch onboarding failures early)

---

## References

- [Clover Refresh Token Documentation](https://docs.clover.com/dev/docs/refresh-access-tokens)
- [Clover OAuth and Tokens FAQs](https://docs.clover.com/dev/docs/oauth-and-tokens-faqs)
- Current implementation: `app/integrations/clover/token_refresh.py`
- Current adapter: `app/integrations/clover/adapter.py`

---

## Troubleshooting Initial OAuth Failures

If merchants are experiencing `{"detail":"Failed to exchange authorization code for tokens"}` during onboarding:

### Common Causes:

1. **Missing or Incorrect `CLOVER_APP_SECRET`:**
   - Check Railway environment variables
   - Verify secret matches the one in Clover Developer Dashboard
   - Ensure no extra spaces or quotes

2. **Environment Mismatch:**
   - Sandbox merchants must use sandbox URLs
   - Production merchants must use production URLs
   - Check `settings.clover_environment` matches merchant's Clover account type

3. **Redirect URI Mismatch:**
   - Redirect URI in code must exactly match Clover App settings
   - Check `app_base_url` in Railway matches your deployed backend URL
   - Verify `/auth/clover/callback` path is correct

4. **Authorization Code Expired:**
   - Clover authorization codes expire quickly
   - If user takes too long between authorize and callback, code becomes invalid
   - Ensure callback happens immediately after authorization

### Debug Steps:

1. Check `app/routers/clover_auth.py` callback logs for detailed error messages
2. Verify token exchange request includes correct `client_id`, `client_secret`, and `code`
3. Test OAuth flow in Clover sandbox first before production
4. Review Clover Developer Dashboard for app configuration issues

---

## Implementation Action Items

| Priority | Task | Status |
|----------|------|--------|
| **🔴 Critical** | Verify `CLOVER_APP_SECRET` and `CLOVER_APP_ID` in Railway | ⬜ |
| **🔴 Critical** | Delete stale mappings for merchants with failed OAuth | ⬜ |
| **🔴 Critical** | Implement Fix 1: Re-fetch store mapping from DB | ⬜ |
| **🔴 Critical** | Implement Fix 2: Require new refresh_token from response | ⬜ |
| **🟡 Important** | Implement Fix 3: Add per-merchant refresh lock | ⬜ |
| **🟡 Important** | Implement Fix 4: Use updated mapping after refresh | ⬜ |
| **🟡 Important** | Add debug logging to Fix 1 (per Claude Code review) | ⬜ |
| **🟢 Verify** | Test atomic DB updates (per Gemini review) | ⬜ |
| **🟢 Verify** | Have affected merchants re-authorize | ⬜ |

---

**Status:** ✅ Analysis complete. ✅ Reviewed and approved by Claude Code and Gemini. Ready for implementation.
