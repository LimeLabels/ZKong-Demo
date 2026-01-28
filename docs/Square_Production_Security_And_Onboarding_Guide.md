# Square Production Security & Onboarding — Step-by-Step Implementation Guide

This guide explains the security fixes applied to the Square integration, how the token refresher works with your variable names, and how to ensure onboarded users don’t hit these issues.

---

## Part 1: Security Fixes Implemented

### 1.1 Missing signature = reject (no bypass)

**Issue:** If the `x-square-hmacsha256-signature` header was missing, the webhook was processed with no verification.

**Change (in `app/routers/webhooks_new.py`):**
- For Square, the handler **always** requires a non-empty signature.
- If the signature is missing or blank → respond with **401 Unauthorized** and log a warning.
- Only after that is `adapter.verify_signature(...)` called.

**What you need to do:** Nothing. The code now rejects Square webhooks when the signature header is missing.

**How to test:** Send a POST to your Square webhook URL without the `x-square-hmacsha256-signature` header. You must get **401** and body like `"Missing webhook signature"`.

---

### 1.2 No webhook secret = reject (don’t accept all)

**Issue:** When `SQUARE_WEBHOOK_SECRET` was unset, `verify_signature` returned `True`, so any POST was accepted.

**Change (in `app/integrations/square/adapter.py`, `verify_signature`):**
- If `settings.square_webhook_secret` is empty → return **False** (do not return `True`).
- So when the secret is not configured, verification fails and the webhook is rejected.

**What you need to do:**
1. In production (and in any environment that receives real Square webhooks), set:
   ```bash
   SQUARE_WEBHOOK_SECRET=<your Square Webhook Signature Key>
   ```
2. In Square Developer Dashboard → Your application → Webhooks → create or edit the subscription → copy the **Signature Key** and use it as `SQUARE_WEBHOOK_SECRET`.

**How to test:** With `SQUARE_WEBHOOK_SECRET` unset, send a Square webhook with any signature. You must get **401** and body like `"Invalid webhook signature"`.

---

### 1.3 No global `SQUARE_ACCESS_TOKEN` fallback

**Issue:** When the store’s token wasn’t available, the code used `os.getenv("SQUARE_ACCESS_TOKEN")`, which could mix merchants in multi-tenant use.

**Change (in `app/integrations/square/adapter.py`):**
- In **webhook handler** (`_handle_catalog_update`): the line `access_token = os.getenv("SQUARE_ACCESS_TOKEN")` was removed. Only the token from the store mapping (or refresh) is used.
- In **`_get_square_credentials`**: the same env fallback was removed. Only `_ensure_valid_token(store_mapping)` is used.

**What you need to do:**
1. Do **not** rely on `SQUARE_ACCESS_TOKEN` in production for multi-tenant. Each merchant must have a valid token in `store_mapping.metadata` (from OAuth + refresh).
2. Ensure the token refresh flow runs (scheduler or on-demand before API calls) so tokens stay valid.

**How to test:** Use a store mapping that has no token (or an expired one and no refresh). Webhooks for that merchant should get **401** “No access token found”, and any code path that uses `_get_square_credentials` should get `None` for that store — no “ghost” token from env.

---

## Part 2: Token Refresher — Variable Names and Flow

### 2.1 Metadata keys (must match exactly)

These are the names used in `store_mapping.metadata` and must be consistent everywhere:

| Key | Set by | Used by | Purpose |
|-----|--------|--------|---------|
| `square_access_token` | OAuth callback, token refresh | Adapter, price scheduler, sync | Current access token |
| `square_refresh_token` | OAuth callback, token refresh | Token refresh service | Refresh token from Square |
| `square_expires_at` | OAuth callback, token refresh | Token refresh service, adapter | ISO string, e.g. `"2024-06-15T12:00:00Z"` |
| `square_token_refreshed_at` | Token refresh | — | When the token was last refreshed (audit) |

**Where they are set:**
- **OAuth callback** (`app/routers/square_auth.py`):  
  `square_access_token`, `square_refresh_token`, `square_expires_at` when the user completes Square OAuth.
- **Token refresh** (`app/integrations/square/token_refresh.py`, `refresh_token_and_update`):  
  Same three keys plus `square_token_refreshed_at` when a refresh succeeds.

**Where they are read:**
- **Token refresh service** (`app/integrations/square/token_refresh.py`):  
  `square_refresh_token` to call Square’s refresh endpoint; `square_expires_at` in `is_token_expiring_soon`; `square_access_token` / `square_expires_at` in `get_access_token`.
- **Adapter** (`app/integrations/square/adapter.py`):  
  `square_expires_at` in `_ensure_valid_token`; `square_access_token` after refresh or from metadata.
- **Token refresh scheduler** (`app/workers/token_refresh_scheduler.py`):  
  `square_access_token` to decide which mappings have Square; `square_expires_at` via `is_token_expiring_soon`.

If you add new code that touches Square tokens, use exactly these keys.

### 2.2 Token refresh flow (high level)

1. **On first API use (e.g. webhook or price update)**  
   Adapter calls `_ensure_valid_token(store_mapping)`:
   - Reads `square_expires_at` from metadata.
   - If `SquareTokenRefreshService.is_token_expiring_soon(expires_at)` is True:
     - Calls `refresh_token_and_update(store_mapping)`.
     - That uses `square_refresh_token` and Square OAuth app credentials to get new tokens, then writes `square_access_token`, `square_refresh_token`, `square_expires_at`, `square_token_refreshed_at` back to metadata.
   - Returns `metadata["square_access_token"]` (possibly after refresh).

2. **Background refresh (optional)**  
   `SquareTokenRefreshScheduler` loads active Square store mappings, checks `square_expires_at` via `is_token_expiring_soon`, and refreshes those that are expiring within the threshold (default 7 days). Same `refresh_token_and_update` and same metadata keys.

So: **all token usage goes through metadata**. No env fallback. Variable names above are the single source of truth.

### 2.3 datetime.utcnow() → datetime.now(timezone.utc)

**Change (in `app/integrations/square/token_refresh.py`):**
- `is_token_expiring_soon`: uses `datetime.now(timezone.utc)` and timezone-aware `expires_utc` for “days until expiry”.
- `refresh_token_and_update`: uses `datetime.now(timezone.utc).isoformat()` for `square_token_refreshed_at`.

This avoids deprecated `utcnow()` and keeps comparisons correct. No variable names changed; only the way “now” and expiry are computed.

---

## Part 3: Making Sure Onboarded Users Don’t Hit These Issues

### 3.1 Before go-live checklist

1. **Env and Square app**
   - [ ] `SQUARE_APPLICATION_ID` and `SQUARE_APPLICATION_SECRET` set for the **production** Square application.
   - [ ] `SQUARE_WEBHOOK_SECRET` set to the **production** webhook Signature Key.
   - [ ] `SQUARE_ENVIRONMENT=production` (or omit if your default is production).
   - [ ] `APP_BASE_URL` is the exact public URL of your backend (e.g. `https://your-app.up.railway.app`), **no trailing slash**, and matches the redirect and webhook URLs configured in the Square app.

2. **Square Developer Dashboard**
   - [ ] Production application created and approved if required.
   - [ ] Redirect URL: `{APP_BASE_URL}/auth/square/callback` (must match exactly).
   - [ ] Webhooks:
     - Notification URL: `{APP_BASE_URL}/webhooks/square/catalog.version.updated` (and any other events you use).
     - Subscription includes at least `catalog.version.updated` (and `inventory.count.updated` if you use it).
     - **Signature key** from this subscription is the value of `SQUARE_WEBHOOK_SECRET`.

3. **Token refresher**
   - [ ] Token refresh scheduler is running (or that the adapter’s “refresh on first use” is sufficient for your traffic).
   - [ ] New OAuth installs store `square_refresh_token` and `square_expires_at` (current `square_auth` flow already does this).

### 3.2 Right after a merchant onboardes (OAuth)

- Store mapping is created/updated with:
  - `source_system="square"`, `source_store_id=<merchant_id>`.
  - `metadata.square_access_token`, `metadata.square_refresh_token`, `metadata.square_expires_at` (and optionally `timezone`, etc.).
- Initial product sync runs in the background and uses the new token.

So “everything works” after onboarding **only if**:
1. The redirect URL and `APP_BASE_URL` match, so OAuth completes and those metadata fields are set.
2. Webhook URL and `SQUARE_WEBHOOK_SECRET` are correct, so catalog updates are accepted and not 401’d.
3. Token refresh runs (or will run on first use) so expired tokens are updated and no one depends on a global `SQUARE_ACCESS_TOKEN`.

### 3.3 Common post-onboarding failures and what to check

| Symptom | What to check |
|--------|----------------|
| “Invalid webhook signature” / 401 on catalog webhooks | `SQUARE_WEBHOOK_SECRET` equals the Signature Key for that notification URL; `APP_BASE_URL` and the URL Square uses for signing are the same (HTTPS, no trailing slash). |
| “Missing webhook signature” | Square is actually sending `x-square-hmacsha256-signature`. If you’re behind a proxy, the proxy must forward this header. |
| “No access token found” on webhook or price updates | Store mapping has `square_access_token` (and usually `square_refresh_token`, `square_expires_at`). If it did at onboarding, token may have expired and refresh may have failed — check logs for refresh errors and that refresh is running. |
| Token refresh fails with 400 | `square_refresh_token` may have been revoked (merchant disconnected the app in Square Dashboard). They need to go through Square OAuth again to re-authorize. |
| Catalog or prices not updating after onboarding | Same as above; also confirm webhook subscription and event types in Square Dashboard, and that the worker/process that handles webhooks and price updates is running. |

---

## Part 4: Testing the Rejection Path (Claude’s addition)

After deploying these changes:

1. **Missing signature**
   - `curl -X POST https://<your-host>/webhooks/square/catalog.version.updated -H "Content-Type: application/json" -d '{}'`
   - Expect **401** and body containing “Missing webhook signature”.

2. **Invalid signature**
   - Same URL, add header:  
     `-H "x-square-hmacsha256-signature: invalid"`
   - Expect **401** and body containing “Invalid webhook signature”.

3. **Valid signature**
   - Use Square’s “Send test notification” or a real subscription, or compute a valid HMAC using your `SQUARE_WEBHOOK_SECRET` and the same `(notification_url + body)` as Square.  
   - Expect **200** and normal processing (or a non-401 error from your business logic if payload is invalid).

This confirms that the new rules (require signature, require secret, no bypass) are active.

---

## Part 5: Quick Reference — What Changed in Code

| File | Change |
|------|--------|
| `app/routers/webhooks_new.py` | For Square: require non-empty signature; if missing → 401. Always verify signature when present. |
| `app/integrations/square/adapter.py` | `verify_signature`: if `SQUARE_WEBHOOK_SECRET` is unset → return `False`. Removed all `os.getenv("SQUARE_ACCESS_TOKEN")` fallbacks; removed `import os`. |
| `app/integrations/square/token_refresh.py` | Use `datetime.now(timezone.utc)` instead of `datetime.utcnow()` in `is_token_expiring_soon` and in `refresh_token_and_update`. |

Token-related metadata keys and the way the adapter and scheduler use them are unchanged; only the security behavior and datetime usage were updated.
