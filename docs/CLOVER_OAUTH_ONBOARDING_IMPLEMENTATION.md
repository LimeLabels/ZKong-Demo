# Clover OAuth & Onboarding – Step-by-Step Implementation

**Document status:** Plan reviewed against [Clover OAuth v2 docs](https://docs.clover.com/dev/docs/refresh-access-tokens); approved with one correction applied: refresh token endpoint uses only `client_id` and `refresh_token` (no `client_secret`). See §3.4.

---

## 1. Overview

This document describes how to add **Clover OAuth onboarding** to your existing flow so that:

- Users **choose Square or Clover** before starting.
- **Square** → existing Square onboarding (current UI and backend).
- **Clover** → new Clover onboarding (UI similar to Square, backend OAuth + store mapping + optional initial sync).

Clover supports **v2/OAuth** (required since Oct 2023): you get an **access_token** and **refresh_token** pair. The flow is analogous to Square: authorize → callback → exchange code for tokens → create/update store mapping → redirect to success.

**Important:** Clover has **no product variants** (one Item = one product). So `source_variant_id` stays **null** for Clover; only `source_id` (Clover item ID) is used. No change needed there.

---

## 2. Prerequisites (Clover Developer Dashboard)

Do this once before implementing.

### 2.1 Create / use a Clover app

1. Go to [Clover Global Developer Dashboard](https://www.clover.com/global-developer-home) (sandbox and/or production).
2. Create an app (or use existing). Ensure it’s a **web / REST** app that can use OAuth.
3. Note:
   - **App ID** (Client ID)
   - **App Secret** (Client Secret)

### 2.2 Configure REST / OAuth settings

1. In the dashboard, open your app → **App Settings** → **Edit REST Configuration** (or equivalent).
2. **Site URL**  
   Set to your **backend** base URL (e.g. `https://your-api.up.railway.app`).  
   This is the base for allowed redirects.
3. **Redirect URI**  
   Clover requires the OAuth callback to be a **subpath of Site URL**.  
   Use: `{Site URL}/auth/clover/callback`  
   Example: `https://your-api.up.railway.app/auth/clover/callback`
4. **Alternate Launch Path** (if you later support “open app from Clover App Market”)  
   Can be something like `/` or `/launch` on the same domain. Optional for the “connect from your website” flow.
5. **Permissions (scopes)**  
   Ensure your app has at least:
   - **Inventory / Items** (read, and write if you need it)  
   So the obtained `access_token` can call `/v3/merchants/{mId}/items` and related APIs.

### 2.3 Environment URLs (for implementation)

| Step              | Sandbox                          | Production (NA)        |
|-------------------|----------------------------------|-------------------------|
| Authorize (user)  | `https://sandbox.dev.clover.com/oauth/v2/authorize` | `https://www.clover.com/oauth/v2/authorize` |
| Token exchange    | `https://apisandbox.dev.clover.com/oauth/v2/token`  | `https://api.clover.com/oauth/v2/token`     |
| Refresh token     | `https://apisandbox.dev.clover.com/oauth/v2/refresh` | `https://api.clover.com/oauth/v2/refresh`   |

(Use EU/LA production URLs if you target those regions.)

---

## 3. Backend Implementation

### 3.1 Config

Add to `app/config.py` (if not already present):

- `clover_app_id` (App ID / Client ID)
- `clover_app_secret` (App Secret / Client Secret)
- `clover_environment`: `"sandbox"` or `"production"` (drives authorize/token/refresh base URLs)
- `app_base_url`: must be the same backend URL used as Clover “Site URL” (e.g. `https://your-api.up.railway.app`)

Ensure `app_base_url` is used when building `redirect_uri` for Clover (see below).

### 3.2 Initiate OAuth – `GET /auth/clover`

**Purpose:** Same idea as Square: collect onboarding data, then redirect to Clover’s authorize URL.

**Query parameters (from frontend):**

- `hipoink_store_code` (required)
- `store_name` (optional)
- `timezone` (required, e.g. `America/New_York`)
- `state` (optional; if not sent, backend generates one for CSRF)

**Logic:**

1. Validate that `clover_app_id` and `app_base_url` are set; else 500.
2. Build **state** (same pattern as Square):
   - JSON: `{ "token": "<random>", "hipoink_store_code": "...", "store_name": "...", "timezone": "..." }`
   - Base64-url encode and use as `state` query param.
3. Build **redirect_uri**: `{app_base_url}/auth/clover/callback`
4. Build **authorize URL**:
   - Sandbox: `https://sandbox.dev.clover.com/oauth/v2/authorize`
   - Production: `https://www.clover.com/oauth/v2/authorize`
   - Query params: `client_id`, `redirect_uri`, `response_type=code`, `state`
5. **Redirect** (302) to that URL.

**Important:** `redirect_uri` must match exactly what is configured in the Clover dashboard (including trailing slash or not).

### 3.3 Callback – `GET /auth/clover/callback`

**Query parameters (from Clover):**

- `code` – authorization code
- `merchant_id` – Clover merchant ID (use as `source_store_id`)
- `state` – same state you sent (decode to get onboarding data)

**Logic:**

1. **Decode state** (base64-url decode JSON) → get `hipoink_store_code`, `store_name`, `timezone`. If decoding fails, log and continue with empty strings.
2. **Exchange code for tokens:**
   - URL: sandbox `https://apisandbox.dev.clover.com/oauth/v2/token` or prod `https://api.clover.com/oauth/v2/token`
   - Method: **POST**
   - Body (JSON):  
     `{ "client_id": "<clover_app_id>", "client_secret": "<clover_app_secret>", "code": "<code>" }`
   - Response (success):  
     `access_token`, `access_token_expiration`, `refresh_token`, `refresh_token_expiration`
3. **Store mapping:**
   - `source_system` = `"clover"`
   - `source_store_id` = `merchant_id` from callback (Clover merchant ID)
   - `hipoink_store_code` = from state
   - `metadata`: at least  
     `clover_access_token`, `clover_refresh_token`,  
     `clover_access_token_expiration`, `clover_refresh_token_expiration`,  
     `timezone`, and optionally `store_name`, `clover_merchant_id` (= merchant_id), `clover_oauth_installed_at` (timestamp).
4. **Create or update** store mapping (by `source_system` + `source_store_id`), same pattern as Square.
5. **Optional:** Trigger initial product sync in background (e.g. call existing `sync_all_products_from_clover` or `sync_products_via_polling` once) so products appear quickly. Don’t block the redirect on it.
6. **Redirect to frontend success page** with query params, e.g.:  
   `{frontend_url}/onboarding/clover/success?merchant_id=...&hipoink_store_code=...`  
   (and optionally store name for display). Use same frontend base as Square (e.g. `frontend_url` from config).

**Error handling:** If token exchange fails (4xx/5xx or missing `access_token`), log, return 400/500 or redirect to an error page with a message; do not create a store mapping without a valid token.

### 3.4 Clover token refresh (later phase)

Clover tokens **expire**. You already have a **Square** token refresh scheduler that:

- Loads Square store mappings
- Checks `metadata.square_expires_at` (or equivalent)
- Calls Square refresh endpoint and updates `metadata` with new tokens

Add a **Clover** equivalent:

- Load store mappings with `source_system == "clover"`.
- For each, read `metadata.clover_refresh_token` and `metadata.clover_access_token_expiration` (or similar).
- If access token is expiring soon (e.g. within 24 hours), **POST** to `https://apisandbox.dev.clover.com/oauth/v2/refresh` (or production) with:
  - **Body (Clover refresh does NOT use `client_secret`):**  
    `{ "client_id": "<clover_app_id>", "refresh_token": "<stored_refresh_token>" }`
- On success, update `metadata` with new `access_token`, `refresh_token`, and their expiration timestamps.
- Run this on a schedule (e.g. daily) like the Square refresh.

You can extend the existing token refresh worker to handle both Square and Clover, or add a separate Clover refresh step in the same worker.

---

## 4. Frontend Implementation

### 4.1 Choose Square vs Clover (entry point)

Add an **entry** page or step where the user picks the POS:

- **Square** → redirect to existing `/onboarding/square` (current Square onboarding).
- **Clover** → redirect to new `/onboarding/clover` (Clover onboarding).

Exact URL and UI (cards, buttons, etc.) are up to you; the important part is that Clover path leads to the Clover onboarding form.

### 4.2 Clover onboarding page – `/onboarding/clover`

**Goal:** Mirror the Square onboarding UI, but for Clover (copy structure and styling from Square; swap copy and backend URL).

**Fields (same as Square):**

- **Store Code \*** (required) – e.g. Hipoink store code.
- **Store Name** (optional) – friendly name.
- **Timezone \*** (required) – dropdown, same list as Square (e.g. `America/New_York`, etc.).

**Submit:**

- Validate required fields.
- Build backend URL:  
  `{NEXT_PUBLIC_BACKEND_URL}/auth/clover?hipoink_store_code=...&timezone=...&store_name=...`
- **Redirect** the browser to that URL (same as Square: `window.location.href = ...`).  
  Backend will then redirect to Clover authorize and later to the callback.

**UI:**

- Reuse the same layout and styles as Square onboarding (card, logo, title, form, button, privacy text).
- Replace “Square” with “Clover” (title: “Connect to Clover”, subtitle about syncing products/pricing with ESL, button “Connect to Clover”).
- Use a Clover logo/icon if available (or a placeholder) so it feels like “Clover” instead of “Square”.

**Files to add/duplicate:**

- `frontend/pages/onboarding/clover.tsx` – Clover onboarding form (based on `square.tsx`).
- `frontend/pages/onboarding/clover.module.css` – copy of `square.module.css` (optionally adjust colors to match Clover branding).

### 4.3 Clover success page – `/onboarding/clover/success`

**Goal:** Same structure as Square success: show “Connected to Clover!”, connection details, and optional sync status.

**Query params (from backend redirect):**

- `merchant_id` – Clover merchant ID
- `hipoink_store_code`
- Optionally `store_name` or similar for display

**UI:**

- Reuse layout from Square success (icon, title, subtitle, details list).
- Show:
  - “Connected to Clover!”
  - Store code, merchant ID, optional store name.
- **Optional:** Poll a backend endpoint for “initial sync status” (e.g. `GET /api/auth/clover/sync-status?merchant_id=...`) and show “Syncing products…” / “Sync complete” similar to Square. If you don’t implement sync-status, you can skip polling and just show a generic “Products will sync via the polling worker” message.
- Buttons:
  - “Open Clover Dashboard” (link to Clover merchant dashboard or sandbox).
  - “Go to ESL Dashboard” (same as Square).

**Files:**

- `frontend/pages/onboarding/clover/success.tsx` – Clover success page (based on `square/success.tsx`).
- `frontend/pages/onboarding/clover/success.module.css` – copy of `square/success.module.css` (tweak if needed).

---

## 5. End-to-End Flow Summary

1. User opens onboarding; **chooses Clover** (new entry step).
2. User is on **Clover onboarding** page; enters Store Code, optional Store Name, Timezone; clicks “Connect to Clover”.
3. Browser redirects to **backend** `GET /auth/clover?hipoink_store_code=...&timezone=...&store_name=...`.
4. Backend builds state, redirects to **Clover** `https://sandbox.dev.clover.com/oauth/v2/authorize?...` (or production).
5. User signs in / approves app at Clover; Clover redirects to **backend** `GET /auth/clover/callback?code=...&merchant_id=...&state=...`.
6. Backend exchanges `code` for **access_token** and **refresh_token**, creates/updates **store_mapping** (source_system=clover, source_store_id=merchant_id, metadata with tokens and timezone), optionally starts initial sync.
7. Backend redirects to **frontend** `/onboarding/clover/success?merchant_id=...&hipoink_store_code=...`.
8. User sees success page; polling worker (and optional initial sync) keep products in sync. **Token refresh** (scheduler) must later refresh Clover tokens before they expire.

---

## 6. source_id and source_variant_id (recap)

- **source_id:** Filled with the **Clover item ID** from the Items API (e.g. `Z80N20C6M34F8`). Clover generates these; you do not use them for “ESL dashboard” selection—they’re for mapping our DB row to Clover’s item.
- **source_variant_id:** Clover has **no variants** (one item = one product). Leave **null** for all Clover products. No change needed.

---

## 7. Implementation Order (recommended)

1. **Backend**
   - Add Clover env vars and `redirect_uri` / URL helpers.
   - Implement `GET /auth/clover` (state build + redirect to Clover authorize).
   - Implement `GET /auth/clover/callback` (decode state, token exchange, store mapping, redirect to frontend success).
   - Optionally: endpoint for Clover initial sync status (if you want success page to show “Syncing…”).
2. **Frontend**
   - Add “Choose Square or Clover” entry (new page or existing onboarding index).
   - Add `/onboarding/clover` (form) and `/onboarding/clover/success` (success page), mirroring Square.
   - Wire “Connect to Clover” to `{backend}/auth/clover?...`.
3. **Token refresh**
   - Implement Clover token refresh (same pattern as Square) and run it in the existing token refresh worker (or a dedicated Clover refresh step).
4. **Testing**
   - Sandbox: use Clover sandbox URLs and a test merchant; go through connect → callback → DB check → success page.
   - Confirm polling worker still runs and syncs Clover products using the new OAuth-stored `clover_access_token`.

---

## 8. Clover OAuth References

- [OAuth flows in Clover](https://docs.clover.com/dev/docs/oauth-flows-in-clover)
- [Obtaining an OAuth token](https://docs.clover.com/dev/docs/obtaining-an-oauth-token)
- [Generate expiring tokens (v2 OAuth)](https://docs.clover.com/dev/docs/generate-expiring-tokens-using-v2-oauth-flow)
- [Use refresh token](https://docs.clover.com/dev/docs/refresh-access-tokens)
- [Merchant Dashboard / App Market OAuth flow](https://docs.clover.com/dev/docs/merchant-dashboard-left-navigation-oauth-flow)

Use **high-trust** flow (client_id + client_secret + code) for server-side token exchange; no PKCE needed on the backend.

---

## 9. Checklist Before Go-Live

- [ ] **Refresh token body:** Implemented with only `client_id` and `refresh_token` (no `client_secret`) per Clover docs.
- [ ] Clover app created; App ID and App Secret in config.
- [ ] Site URL and Redirect URI set in Clover dashboard to match backend (exact match, no trailing slash mismatch).
- [ ] Backend `/auth/clover` and `/auth/clover/callback` implemented and tested in sandbox.
- [ ] Frontend: choose Square/Clover → Clover onboarding → success page implemented.
- [ ] Store mapping created with `clover_access_token` and `clover_refresh_token` (and expirations).
- [ ] Clover token refresh scheduler (or step) implemented and running.
- [ ] Polling worker still runs and uses `metadata.clover_access_token` for Clover merchants (no change if you already read token from store_mapping.metadata).

Once this is done, Clover onboarding will work like Square’s: user chooses Clover, fills the form, is sent to Clover to authorize, and returns to your app with the merchant connected and tokens stored for API and polling.
