# Complete .env File Template

Here's everything that needs to be in your `.env` file:

## Required Variables (App won't work without these)

```env
# Supabase Configuration - REQUIRED
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here
```

## Optional Variables (Have defaults or can use placeholders for testing)

```env
# ZKong API Configuration - Optional for testing, REQUIRED for actual ZKong sync
ZKONG_API_BASE_URL=https://api.zkong.com
ZKONG_USERNAME=your_zkong_username
ZKONG_PASSWORD=your_zkong_password
ZKONG_RSA_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----
Your RSA Public Key Here
-----END PUBLIC KEY-----

# Shopify Configuration - Optional for testing, REQUIRED for webhook verification
SHOPIFY_WEBHOOK_SECRET=your_shopify_webhook_secret

# Application Configuration - Optional (have defaults)
APP_ENVIRONMENT=development
LOG_LEVEL=INFO

# Worker Configuration - Optional (have defaults)
SYNC_WORKER_INTERVAL_SECONDS=5
MAX_RETRY_ATTEMPTS=3
RETRY_BACKOFF_MULTIPLIER=2.0
RETRY_INITIAL_DELAY_SECONDS=1.0

# Rate Limiting - Optional (has default)
ZKONG_RATE_LIMIT_PER_SECOND=10
```

---

## Complete Example .env File

```env
# ============================================
# REQUIRED - Must have these for app to start
# ============================================

# Supabase Configuration
SUPABASE_URL=https://xgohzifvcdlsxpuceriy.supabase.co
SUPABASE_SERVICE_KEY=sb_secret_p_cjF_sMRA9OD7m2Qa1Y8w_0lNRfiAx

# ============================================
# OPTIONAL - Can use placeholders for testing
# ============================================

# ZKong API Configuration
# Get these from your ZKong dashboard/account
ZKONG_API_BASE_URL=https://api.zkong.com
ZKONG_USERNAME=placeholder
ZKONG_PASSWORD=placeholder
ZKONG_RSA_PUBLIC_KEY=placeholder

# Shopify Configuration
# Get this when you set up webhooks in Shopify admin
SHOPIFY_WEBHOOK_SECRET=placeholder

# ============================================
# OPTIONAL - These have defaults, only add if you want to change them
# ============================================

# Application Configuration
APP_ENVIRONMENT=development
LOG_LEVEL=INFO

# Worker Configuration
SYNC_WORKER_INTERVAL_SECONDS=5
MAX_RETRY_ATTEMPTS=3
RETRY_BACKOFF_MULTIPLIER=2.0
RETRY_INITIAL_DELAY_SECONDS=1.0

# Rate Limiting
ZKONG_RATE_LIMIT_PER_SECOND=10
```

---

## Minimum Working .env (Just to get app started)

For testing the API endpoints without ZKong sync or webhooks, you only need:

```env
# Required
SUPABASE_URL=https://xgohzifvcdlsxpuceriy.supabase.co
SUPABASE_SERVICE_KEY=sb_secret_p_cjF_sMRA9OD7m2Qa1Y8w_0lNRfiAx

# Optional placeholders (to avoid errors)
ZKONG_USERNAME=placeholder
ZKONG_PASSWORD=placeholder
ZKONG_RSA_PUBLIC_KEY=placeholder
SHOPIFY_WEBHOOK_SECRET=placeholder
```

---

## Where to Get Each Value

### ✅ SUPABASE_URL & SUPABASE_SERVICE_KEY
- **You already have these!**
- From Supabase dashboard → Settings → API

### 🔑 ZKONG_USERNAME & ZKONG_PASSWORD
- Get from your ZKong account/dashboard
- Contact ZKong support if you don't have these yet

### 🔐 ZKONG_RSA_PUBLIC_KEY
- Get from ZKong API endpoint 2.1 (documented in their API docs)
- Or from your ZKong dashboard/account settings
- Should look like:
  ```
  -----BEGIN PUBLIC KEY-----
  MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
  -----END PUBLIC KEY-----
  ```

### 🛒 SHOPIFY_WEBHOOK_SECRET
- Created automatically when you set up webhooks in Shopify
- Go to Shopify Admin → Settings → Notifications → Webhooks
- After creating a webhook, Shopify generates a secret
- All webhooks for a store use the same secret

---

## When You Need Each Variable

| Variable | Needed For | When |
|----------|-----------|------|
| `SUPABASE_URL` | App startup | **Always** |
| `SUPABASE_SERVICE_KEY` | App startup | **Always** |
| `ZKONG_USERNAME` | ZKong API sync | When syncing products |
| `ZKONG_PASSWORD` | ZKong API sync | When syncing products |
| `ZKONG_RSA_PUBLIC_KEY` | ZKong API auth | When syncing products |
| `SHOPIFY_WEBHOOK_SECRET` | Webhook verification | When receiving webhooks |
| Everything else | Fine-tuning | Only if you want to change defaults |

---

## Your Current .env Status

✅ You have:
- `SUPABASE_URL` ✓
- `SUPABASE_SERVICE_KEY` ✓

❌ You need to add (can use placeholders for now):
- `ZKONG_USERNAME=placeholder`
- `ZKONG_PASSWORD=placeholder`
- `ZKONG_RSA_PUBLIC_KEY=placeholder`
- `SHOPIFY_WEBHOOK_SECRET=placeholder`

---

## Quick Start Checklist

- [ ] Add Supabase credentials (you already have these ✓)
- [ ] Add ZKong placeholders (just to get app running)
- [ ] Test API endpoints at `http://localhost:8000/docs`
- [ ] Create store mapping via API
- [ ] Get real ZKong credentials (when ready to sync)
- [ ] Set up Shopify webhooks (when ready to test integration)
- [ ] Add real Shopify webhook secret

