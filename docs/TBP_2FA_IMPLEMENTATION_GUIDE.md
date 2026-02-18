# 2FA for Time-Based Pricing — Enhanced Implementation Guide

This guide describes how to implement **two-factor authentication (2FA)** for the time-based pricing UI in the external-tool dashboard. The flow uses **email OTP** (one-time password) for verification, with an optional **"Remember Me"** feature that skips 2FA for 30 days on trusted devices.

---

## Critical: Why NOT Supabase OTP

**Do NOT use Supabase's `signInWithOtp` / `verifyOtp`** for this flow. When an already-authenticated user (logged in via email/password) calls those methods, Supabase creates a **new auth session** and overwrites the existing one. This causes token conflicts, unexpected logouts, and broken API calls.

Instead, we use a **custom OTP flow through FastAPI** while keeping Supabase only for the primary email/password login.

---

## Overview

| Requirement        | Implementation                                                                 |
|--------------------|---------------------------------------------------------------------------------|
| 2FA flow           | User enters email → Backend generates OTP → Email sent → User enters code → Verify |
| OTP expiry         | 30 minutes                                                                     |
| Remember Me        | HttpOnly cookie + `tbp_2fa_remember` table; valid for 30 days                  |
| Scope              | Applied to time-based pricing UI (Create Schedule, Manage Schedules)           |
| OTP storage        | Custom `tbp_otp_codes` table — NOT Supabase Auth                               |

---

## Revised Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Frontend (React + Polaris)                                                 │
│                                                                             │
│  [Login (Supabase Auth)] → [2FA Gate] → [Main App: Pricing UI]             │
│                                │                                            │
│                                ├── Check remember-me cookie → skip 2FA?     │
│                                └── Show email → Send OTP → Enter code       │
│                                     └── Optional: "Remember Me" checkbox    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI) — Handles ALL 2FA logic                                  │
│                                                                             │
│  POST /api/auth/tbp-2fa/send-otp     → Generate code, hash, store, email   │
│  POST /api/auth/tbp-2fa/verify-otp   → Check code, set remember cookie     │
│  GET  /api/auth/tbp-2fa/check-remember → Validate remember-me cookie       │
│  POST /api/auth/tbp-2fa/forget       → Revoke remember-me                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Supabase (Login only — do NOT use for 2FA OTP)                             │
│  - auth.users (existing email/password login)                               │
│  - tbp_otp_codes (new — custom OTP storage)                                 │
│  - tbp_2fa_remember (new — 30-day device trust)                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Database Migration

Run this migration in Supabase. Both tables are new.

```sql
-- ============================================================
-- Table 1: tbp_otp_codes (short-lived OTP codes)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.tbp_otp_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER DEFAULT 0,
  max_attempts INTEGER DEFAULT 5,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_tbp_otp_codes_user
  ON public.tbp_otp_codes(user_id);

CREATE INDEX idx_tbp_otp_codes_expires
  ON public.tbp_otp_codes(expires_at);

ALTER TABLE public.tbp_otp_codes ENABLE ROW LEVEL SECURITY;

-- Only the backend (service role) should access this table.
-- No direct client access — all operations go through FastAPI.
-- Service role bypasses RLS by default in Supabase.

-- ============================================================
-- Table 2: tbp_2fa_remember (30-day device trust)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.tbp_2fa_remember (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  device_id TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_tbp_2fa_remember_user
  ON public.tbp_2fa_remember(user_id);

CREATE INDEX idx_tbp_2fa_remember_expires
  ON public.tbp_2fa_remember(expires_at);

ALTER TABLE public.tbp_2fa_remember ENABLE ROW LEVEL SECURITY;

-- Same as above: service-role-only access via FastAPI.
```

**Key design decisions:**
- `attempts` and `max_attempts` on `tbp_otp_codes` enable brute-force protection at the DB level.
- No RLS policies for frontend access — these tables are backend-only (service role).
- `ON DELETE CASCADE` ensures cleanup when a user is deleted.
- `device_id` is a UUID generated client-side and stored in localStorage (not a browser fingerprint).

---

## Step 2: Backend — FastAPI Endpoints

Create `app/routers/tbp_2fa.py` and `app/services/tbp_2fa_service.py`.

### 2.1 Authentication Requirement

The `send-otp` and `verify-otp` endpoints should require the user to be **already authenticated** (valid Supabase JWT). This ensures only logged-in users can request 2FA codes. Use the existing `verify_token` dependency from `app/routers/auth.py` and confirm the authenticated user's email matches the email in the request.

### 2.2 OTP Generation (Security-Critical)

```python
import secrets

def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP."""
    code = secrets.randbelow(1000000)
    return f"{code:06d}"  # Zero-pad to 6 digits
```

- **MUST** use `secrets` module, NOT `random`. This is a security requirement.
- Hash the code with **bcrypt** (preferred) or SHA-256 + salt before storing in `tbp_otp_codes`.

### 2.3 Rate Limiting

- Max **3–5 OTP send requests** per user per 15 minutes.
- Max **5 verification attempts** per code (tracked in `attempts` column).
- After 5 failed attempts, invalidate that code (delete the row).
- Implement rate limiting in FastAPI middleware or per-endpoint with a decorator.

### 2.4 Email Enumeration Protection

- Always return a generic success message: `{"message": "If the email is valid, a code has been sent."}` regardless of whether the user exists or the email was actually sent.
- Log email delivery failures server-side for debugging.

### 2.5 Endpoint Specifications

#### `POST /api/auth/tbp-2fa/send-otp`

**Request:**
```json
{ "email": "user@example.com" }
```

**Response:**
```json
{ "message": "If the email is valid, a code has been sent." }
```

**Logic:**
1. Require authentication (Supabase JWT). Verify authenticated user's email matches request email.
2. Rate limit check: if user has >= 5 OTP requests in last 15 min, reject with 429.
3. Delete any existing OTP rows for this user (only one active code at a time).
4. Generate 6-digit code with `secrets.randbelow(1000000)`.
5. Hash the code with bcrypt.
6. Insert into `tbp_otp_codes`: `user_id`, `code_hash`, `expires_at = now() + 30 min`.
7. Send email with the plain-text code via your email provider (Resend / SendGrid / SES).
8. Return generic success message regardless of outcome.

#### `POST /api/auth/tbp-2fa/verify-otp`

**Request:**
```json
{
  "email": "user@example.com",
  "code": "123456",
  "remember_me": true,
  "device_id": "uuid-from-client"
}
```

**Response (success):**
```json
{ "verified": true }
```

**Response (error):**
```json
{ "error": "Invalid or expired code" }
```

**Logic:**
1. Require authentication. Verify authenticated user's email matches request email.
2. Fetch the active OTP row for this user where `expires_at > now()`.
3. If no row found, return error (code expired or not requested).
4. If `row.attempts >= row.max_attempts`, delete row, return error (too many attempts).
5. Increment `attempts`.
6. Verify submitted code against `code_hash` using bcrypt.
7. If mismatch, return error.
8. If match:
   - Delete the OTP row (consumed).
   - If `remember_me` is true:
     - Generate random remember token with `secrets.token_urlsafe(32)`.
     - Hash it with bcrypt.
     - Insert into `tbp_2fa_remember`: `user_id`, `token_hash`, `device_id`, `expires_at = now() + 30 days`.
     - Set an HttpOnly cookie on the response with the raw remember token.
   - Return `{ "verified": true }`.

#### `GET /api/auth/tbp-2fa/check-remember`

**Request:** `Authorization: Bearer <supabase_jwt>`, `Cookie: tbp_remember_token=<raw_token>`

**Response:**
```json
{ "remembered": true }
```
or
```json
{ "remembered": false }
```

**Logic:**
1. Require authentication (Supabase JWT) to identify the user.
2. Read `tbp_remember_token` from the HttpOnly cookie.
3. If no cookie, return `{ "remembered": false }`.
4. Fetch non-expired `tbp_2fa_remember` rows for this user only.
5. Verify the cookie token against each row's `token_hash` using bcrypt.
6. If match found and `expires_at > now()`, return `{ "remembered": true }`.
7. Otherwise return `{ "remembered": false }`.

#### `POST /api/auth/tbp-2fa/forget`

**Request:** Authenticated user, cookie present

**Response:**
```json
{ "success": true }
```

**Logic:**
1. Delete matching `tbp_2fa_remember` row(s) for this user.
2. Clear the `tbp_remember_token` cookie.

### 2.6 Remember-Me Cookie Settings

When setting the HttpOnly cookie in FastAPI:

```python
response.set_cookie(
    key="tbp_remember_token",
    value=raw_token,
    httponly=True,       # JavaScript cannot access this
    secure=True,         # HTTPS only (use False for localhost dev)
    samesite="lax",      # Or "strict" if frontend and API are same-origin
    path="/api/auth/tbp-2fa",  # Only sent on 2FA-related requests
    max_age=30 * 24 * 60 * 60,  # 30 days in seconds
)
```

For cross-origin setups (e.g., frontend on different domain), ensure CORS allows `credentials: "include"` and that the backend sets `Access-Control-Allow-Credentials: true`.

### 2.7 Email Template

Use your email provider (Resend, SendGrid, SES) to send:

**Subject:** `Your verification code for Time-Based Pricing`

**Body:**
```
Your 6-digit code is: {code}

This code expires in 30 minutes. If you didn't request this, you can safely ignore this email.
```

---

## Step 3: Frontend — 2FA Gate

### 3.1 Do NOT Add Supabase OTP to auth.ts

**Do NOT add `sendTbpOtp` or `verifyTbpOtp` using Supabase's `signInWithOtp` / `verifyOtp`** to `auth.ts`. Those functions will overwrite the existing login session. All OTP logic goes through FastAPI endpoints.

### 3.2 Frontend API Service (`external-tool/src/services/tbp2fa.ts`)

Create a new service that calls the FastAPI backend. Use the existing `apiClient` (which attaches the Supabase JWT and sets `withCredentials` for cookies) so the backend receives both the Bearer token and the remember-me cookie:

```typescript
import { apiClient } from './api'

const BASE = '/api/auth/tbp-2fa'

export const sendOtp = async (email: string): Promise<void> => {
  await apiClient.post(`${BASE}/send-otp`, { email })
}

export const verifyOtp = async (
  email: string,
  code: string,
  rememberMe: boolean,
  deviceId: string
): Promise<{ verified: boolean }> => {
  const { data } = await apiClient.post<{ verified: boolean }>(`${BASE}/verify-otp`, {
    email,
    code,
    remember_me: rememberMe,
    device_id: deviceId,
  })
  return data
}

export const checkRemember = async (): Promise<boolean> => {
  try {
    const { data } = await apiClient.get<{ remembered: boolean }>(`${BASE}/check-remember`)
    return data.remembered === true
  } catch {
    return false
  }
}

export const forgetDevice = async (): Promise<void> => {
  await apiClient.post(`${BASE}/forget`)
}
```

**Important:** Ensure `apiClient` is configured with `withCredentials: true` (or equivalent) so cookies are sent. If using Axios, set `axios.defaults.withCredentials = true` or per-request. The apiClient already attaches the Supabase JWT via an interceptor.

### 3.3 Device ID Generation

Generate a stable device ID once and store in localStorage:

```typescript
export const getDeviceId = (): string => {
  const key = 'tbp_device_id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}
```

This is an identifier for the remember-me record, not a security token. Security comes from the HttpOnly cookie.

### 3.4 `Tbp2FAGate` Component (`external-tool/src/components/Tbp2FAGate.tsx`)

**States:** `idle` → `sending` → `code_sent` → `verifying` → `verified` (or `error` at any step)

**UI flow:**
1. Show user's email (read-only, pre-filled from session).
2. "Send Verification Code" button → calls `sendOtp(email)`.
3. After send: show 6-digit code input + "Verify" button + "Remember this device for 30 days" checkbox.
4. On verify: calls `verifyOtp(email, code, rememberMe, getDeviceId())`.
5. On success: call `onVerified()` callback to parent.
6. On error: show error message, allow retry.

**Props:**
```typescript
interface Tbp2FAGateProps {
  userEmail: string
  onVerified: () => void
}
```

### 3.5 Integration in `App.tsx`

```tsx
const [tbp2faVerified, setTbp2faVerified] = useState(false)
const [checkingRemember, setCheckingRemember] = useState(true)

useEffect(() => {
  if (!isAuthenticated || !user) return
  checkRemember()
    .then((valid) => {
      setTbp2faVerified(valid)
    })
    .finally(() => {
      setCheckingRemember(false)
    })
}, [isAuthenticated, user])

// Before rendering ScheduleCalendar / ScheduleList:
if (hasStore && !checkingRemember && !tbp2faVerified) {
  return (
    <Tbp2FAGate
      userEmail={user.email}
      onVerified={() => setTbp2faVerified(true)}
    />
  )
}

// On logout: reset tbp2faVerified to false
```

---

## Step 4: Security Checklist

| Concern                | Implementation                                                              |
|------------------------|-----------------------------------------------------------------------------|
| OTP brute force        | Max 5 attempts per code (tracked in DB). Lock out after 5 failures.         |
| OTP spam               | Max 3–5 send requests per user per 15 minutes.                             |
| Session conflict       | **Resolved:** Custom OTP; no Supabase `signInWithOtp` on logged-in users.   |
| Remember token theft   | Raw token in HttpOnly + Secure + SameSite cookie. Not in localStorage.      |
| Email enumeration      | Generic response for all send-otp requests regardless of email validity.    |
| Code generation        | `secrets.randbelow()` — cryptographically secure. NOT `random.randint()`.   |
| Code storage           | Bcrypt hash in DB. Raw code only in memory and in the email.                |
| HTTPS                  | Required in production. `Secure=True` on cookie enforces this.              |
| Expired data cleanup   | Cron job or pg_cron to delete expired rows from both tables.                |

---

## Step 5: Cleanup Cron Job

```sql
-- Run daily via pg_cron or external scheduler
DELETE FROM public.tbp_otp_codes WHERE expires_at < now();
DELETE FROM public.tbp_2fa_remember WHERE expires_at < now();
```

---

## Step 6: Testing Checklist

- [ ] Sending OTP delivers a 6-digit code to the user's email
- [ ] Correct code grants access to time-based pricing UI
- [ ] Wrong code shows error and increments attempt counter
- [ ] After 5 wrong attempts, code is invalidated; user must request a new one
- [ ] Code expires after 30 minutes and cannot be used
- [ ] Rate limit: user cannot request more than 5 codes in 15 minutes
- [ ] "Remember Me" sets HttpOnly cookie and skips 2FA on next visit
- [ ] Remember-me expires after 30 days
- [ ] Clearing cookies forces re-verification
- [ ] Logout resets 2FA state in the frontend
- [ ] Generic response on send-otp regardless of email validity
- [ ] Existing Supabase auth session is NOT affected by the 2FA flow

---

## Files to Create/Modify

| File                                      | Action                                                   |
|-------------------------------------------|----------------------------------------------------------|
| Supabase migration                        | Create `tbp_otp_codes` and `tbp_2fa_remember` tables     |
| `app/routers/tbp_2fa.py`                  | New: 4 FastAPI endpoints                                 |
| `app/services/tbp_2fa_service.py`         | New: OTP generation, hashing, DB, email                  |
| `app/config.py`                           | Add email provider config (e.g. Resend API key)          |
| `external-tool/src/services/tbp2fa.ts`    | New: Frontend API calls to FastAPI                       |
| `external-tool/src/components/Tbp2FAGate.tsx` | New: 2FA gate UI component                           |
| `external-tool/src/App.tsx`               | Modify: Integrate 2FA gate before pricing UI             |
| `external-tool/src/services/auth.ts`      | **Do NOT add Supabase OTP calls here**                   |

---

## References

- [Python `secrets` module](https://docs.python.org/3/library/secrets.html)
- [bcrypt hashing](https://pypi.org/project/bcrypt/)
- [Supabase Auth (login only)](https://supabase.com/docs/guides/auth)
