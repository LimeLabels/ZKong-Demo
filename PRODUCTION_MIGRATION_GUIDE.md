# Production Migration Guide

Complete step-by-step guide for migrating from your environment to production Railway environment.

---

## 📋 Table of Contents

1. [Pre-Migration Checklist](#pre-migration-checklist)
2. [Environment Variables Migration](#environment-variables-migration)
3. [Railway Configuration](#railway-configuration)
4. [Square OAuth & Webhook Configuration](#square-oauth--webhook-configuration)
5. [Git Workflow for Testing & Deployment](#git-workflow-for-testing--deployment)
6. [Post-Migration Verification](#post-migration-verification)

---

## 1. Pre-Migration Checklist

Before starting, ensure you have:
- ✅ Access to your friend's Railway production project
- ✅ Access to Square Developer Dashboard
- ✅ Your production Railway URLs (backend and frontend)
- ✅ All environment variable values from your current environment
- ✅ Git access to the repository

---

## 2. Environment Variables Migration

### 2.1 Backend Web Server Variables (Railway)

Navigate to your Railway project → **Web Server Service** → **Variables** tab.

Add/Update these variables:

```bash
# Application URLs (CRITICAL - Update with your production URLs)
APP_BASE_URL=https://your-backend-service.up.railway.app
FRONTEND_URL=https://your-frontend-service.up.railway.app

# Hipoink ESL API Configuration
HIPOINK_API_BASE_URL=http://43.153.107.21
HIPOINK_USERNAME=your_hipoink_username
HIPOINK_PASSWORD=your_hipoink_password
HIPOINK_API_SECRET=your_hipoink_api_secret
HIPOINK_CLIENT_ID=default

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Shopify Configuration (if using Shopify)
SHOPIFY_API_KEY=your_shopify_api_key
SHOPIFY_API_SECRET=your_shopify_api_secret
SHOPIFY_WEBHOOK_SECRET=your_shopify_webhook_secret

# Square Configuration (CRITICAL for Square integration)
SQUARE_APPLICATION_ID=your_square_application_id
SQUARE_APPLICATION_SECRET=your_square_application_secret
SQUARE_WEBHOOK_SECRET=your_square_webhook_secret
SQUARE_ENVIRONMENT=production

# Slack Configuration (Optional)
SLACK_WEBHOOK_URL=your_slack_webhook_url
SLACK_ALERTS_ENABLED=true

# Application Configuration
APP_ENVIRONMENT=production
LOG_LEVEL=INFO

# Worker Configuration (Optional - defaults are fine)
SYNC_WORKER_INTERVAL_SECONDS=5
MAX_RETRY_ATTEMPTS=3
RETRY_BACKOFF_MULTIPLIER=2.0
RETRY_INITIAL_DELAY_SECONDS=1.0

# Rate Limiting
HIPOINK_RATE_LIMIT_PER_SECOND=10
```

**Important Notes:**
- Replace `your-backend-service.up.railway.app` with your actual Railway backend URL
- Replace `your-frontend-service.up.railway.app` with your actual Railway frontend URL
- `APP_BASE_URL` and `FRONTEND_URL` must match your actual Railway deployment URLs
- `SQUARE_ENVIRONMENT` should be `production` (not `sandbox`)

### 2.2 Worker Service Variables (Railway)

Navigate to your Railway project → **Worker Service** → **Variables** tab.

**Use the SAME variables as the Web Server** (Railway supports shared variables).

Alternatively, you can create **Shared Variables** in Railway:
1. Go to **Project Settings** → **Variables**
2. Create shared variables that both services can use
3. This keeps variables in sync automatically

### 2.3 Frontend Variables (Railway - if separate service)

If you have a separate frontend service on Railway:

```bash
NEXT_PUBLIC_BACKEND_URL=https://your-backend-service.up.railway.app
NEXT_PUBLIC_ESL_DASHBOARD_LINK=http://43.153.107.21/admin/auth/login
NODE_ENV=production
PORT=3000
```

---

## 3. Railway Configuration

### 3.1 Web Server Service

**Service Settings:**
- **Root Directory:** Leave empty (or set to repository root)
- **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Healthcheck Path:** `/` (or `/health` if you have a health endpoint)

**Deployment Settings:**
- **Branch:** `main` (or your production branch)
- **Auto Deploy:** Enabled (recommended)

### 3.2 Worker Service

**Service Settings:**
- **Root Directory:** Leave empty (or set to repository root)
- **Start Command:** `python -m app.workers`
- **Healthcheck Path:** None (workers don't need health checks)

**Deployment Settings:**
- **Branch:** `main` (or your production branch)
- **Auto Deploy:** Enabled (recommended)

### 3.3 Verify Services Are Running

After deployment, check Railway logs:
1. **Web Server:** Should show "Hipoink ESL Integration Middleware started"
2. **Worker:** Should show "Sync worker started", "Price scheduler started", "Square token refresh scheduler started"

---

## 4. Square OAuth & Webhook Configuration

### 4.1 Square Developer Dashboard - OAuth Configuration

1. **Go to Square Developer Dashboard:**
   - Visit: https://developer.squareup.com/apps
   - Select your Square application

2. **Configure OAuth Redirect URI:**
   - Navigate to **OAuth** section
   - Add redirect URI:
     ```
     https://your-backend-service.up.railway.app/auth/square/callback
     ```
   - Replace with your actual Railway backend URL
   - **Important:** Must match exactly (including `https://` and no trailing slash)

3. **Verify Application Credentials:**
   - **Application ID:** Copy this to `SQUARE_APPLICATION_ID` in Railway
   - **Application Secret:** Copy this to `SQUARE_APPLICATION_SECRET` in Railway
   - **Environment:** Should be `Production` (not Sandbox)

### 4.2 Square Developer Dashboard - Webhook Configuration

1. **Go to Webhooks Section:**
   - In your Square application dashboard
   - Navigate to **Webhooks**

2. **Subscribe to Required Events:**
   - `catalog.version.updated` - For product changes
   - `inventory.count.updated` - For inventory changes (if needed)
   - Any other events your integration uses

3. **Configure Webhook URL:**
   - **Webhook URL:** 
     ```
     https://your-backend-service.up.railway.app/webhooks/square/catalog.version.updated
     ```
   - Replace with your actual Railway backend URL
   - **Note:** The path format is `/webhooks/{integration_name}/{event_type}`

4. **Get Webhook Signature Key:**
   - After creating the webhook subscription
   - Copy the **Webhook Signature Key**
   - Add to Railway as `SQUARE_WEBHOOK_SECRET`

5. **Test Webhook:**
   - Use Square's webhook testing tool
   - Or manually trigger a product update in Square
   - Check Railway logs to verify webhook is received

### 4.3 Verify OAuth Flow

1. **Test OAuth Initiation:**
   ```
   https://your-frontend-service.up.railway.app/onboarding/square
   ```
   - Fill out the form
   - Click "Connect Square"
   - Should redirect to Square OAuth page

2. **Test OAuth Callback:**
   - After authorizing in Square
   - Should redirect back to your frontend success page
   - Check Railway logs for "Square OAuth callback received"
   - Verify store mapping is created in Supabase

---

## 5. Git Workflow for Testing & Deployment

### 5.1 Initial Setup (One-time)

```bash
# Navigate to your project directory
cd /Users/mac/ZKong-Demo

# Check current branch
git branch

# If you're on a feature branch, switch to main first
git checkout main

# Pull latest code from main
git pull origin main

# Create a new branch for your changes (soft deletion fix)
git checkout -b fix/soft-delete-products
```

### 5.2 Testing Your Changes Locally

```bash
# Make sure you're on your feature branch
git checkout fix/soft-delete-products

# Test your changes locally
# 1. Start backend
uvicorn app.main:app --reload --port 8000

# 2. Start workers (in another terminal)
python -m app.workers

# 3. Test the deletion flow
# - Create a product in Square
# - Delete it in Square
# - Verify it's marked as "deleted" in database (not removed)
# - Check logs to ensure soft delete is working
```

### 5.3 Fetching Latest Code from Main

**Before pushing your changes, always fetch and test with latest main:**

```bash
# 1. Commit your current changes (if any)
git add .
git commit -m "Fix: Use soft delete instead of hard delete for products"

# 2. Switch to main branch
git checkout main

# 3. Pull latest changes from main
git pull origin main

# 4. Switch back to your feature branch
git checkout fix/soft-delete-products

# 5. Merge latest main into your branch
git merge main

# 6. Resolve any conflicts if they occur
# (If conflicts occur, fix them manually, then:)
git add .
git commit -m "Merge main into feature branch"

# 7. Test again with merged code
# Run your local tests to ensure nothing broke
```

### 5.4 Testing Workflow After Merge

```bash
# 1. Test locally with merged code
uvicorn app.main:app --reload --port 8000
python -m app.workers

# 2. Test the complete flow:
#    - Onboarding a new Square store
#    - Creating products
#    - Updating products
#    - Deleting products (verify soft delete)
#    - Price adjustments
#    - Webhook handling

# 3. Check logs for any errors
# 4. Verify database changes are correct
```

### 5.5 Pushing to Main

**Once everything is tested and working:**

```bash
# 1. Make sure you're on your feature branch
git checkout fix/soft-delete-products

# 2. Ensure all changes are committed
git status

# 3. Push your branch to remote (for backup/review)
git push origin fix/soft-delete-products

# 4. Switch to main
git checkout main

# 5. Merge your feature branch into main
git merge fix/soft-delete-products

# 6. Push to main (this will trigger Railway auto-deploy)
git push origin main

# 7. Monitor Railway deployment
# - Check Railway dashboard for deployment status
# - Watch logs for any startup errors
# - Verify services are running
```

### 5.6 Post-Deployment Testing

After pushing to main and Railway auto-deploys:

```bash
# 1. Check Railway logs
# - Web Server: Should start without errors
# - Worker: Should start without errors

# 2. Test production endpoints
curl https://your-backend-service.up.railway.app/

# 3. Test onboarding flow
# - Visit: https://your-frontend-service.up.railway.app/onboarding/square
# - Complete OAuth flow
# - Verify store mapping is created

# 4. Test product sync
# - Create a product in Square
# - Verify it syncs to Hipoink
# - Check database for product record

# 5. Test deletion (your fix)
# - Delete a product in Square
# - Verify it's marked as "deleted" in database (not removed)
# - Check logs for "Marked product as deleted" message
```

### 5.7 Cleanup (Optional)

After successful deployment:

```bash
# Delete local feature branch (optional)
git branch -d fix/soft-delete-products

# Delete remote feature branch (optional)
git push origin --delete fix/soft-delete-products
```

---

## 6. Post-Migration Verification

### 6.1 Service Health Checks

**Backend Health:**
```bash
curl https://your-backend-service.up.railway.app/
```
Expected response:
```json
{
  "service": "Hipoink ESL Integration Middleware",
  "version": "1.1.0",
  "status": "running",
  "integrations": ["shopify", "square", "ncr"]
}
```

**Worker Health:**
- Check Railway logs for:
  - `[info] Sync worker started`
  - `[info] Price scheduler started`
  - `[info] Square token refresh scheduler started`

### 6.2 Integration Tests

1. **Square OAuth Test:**
   - Visit onboarding page
   - Complete OAuth flow
   - Verify store mapping created

2. **Product Sync Test:**
   - Create product in Square
   - Verify sync to Hipoink
   - Check database record

3. **Product Deletion Test (Your Fix):**
   - Delete product in Square
   - Verify status = "deleted" in database
   - Verify product still exists in database (not removed)

4. **Webhook Test:**
   - Update product in Square
   - Check Railway logs for webhook received
   - Verify product updated in Hipoink

5. **Price Adjustment Test:**
   - Create a price schedule
   - Wait for scheduled time
   - Verify prices updated in Hipoink

### 6.3 Database Verification

Check Supabase for:
- Store mappings are created correctly
- Products have correct status (not hard-deleted)
- Sync queue is processing
- Hipoink product mappings exist

### 6.4 Monitoring

Set up monitoring for:
- Railway service uptime
- Error rates in logs
- Sync queue processing times
- Webhook delivery success rates

---

## 7. Troubleshooting

### 7.1 Common Issues

**Issue: OAuth redirect fails**
- Check `APP_BASE_URL` matches Railway backend URL
- Verify redirect URI in Square dashboard matches exactly
- Check Railway logs for OAuth errors

**Issue: Webhooks not received**
- Verify `SQUARE_WEBHOOK_SECRET` is set correctly
- Check webhook URL in Square dashboard
- Verify webhook events are subscribed
- Check Railway logs for webhook errors

**Issue: Products not syncing**
- Check worker service is running
- Verify `HIPOINK_STORE_CODE` is correct
- Check sync queue in Supabase
- Review worker logs for errors

**Issue: Products being hard-deleted**
- Verify your soft delete fix is deployed
- Check `sync_worker.py` line 496 uses `update_product_status`
- Restart worker service if needed

### 7.2 Rollback Procedure

If something goes wrong:

```bash
# 1. Revert the commit in main
git revert HEAD
git push origin main

# 2. Railway will auto-deploy the revert
# 3. Monitor logs to ensure rollback succeeded
```

---

## 8. Quick Reference Checklist

### Pre-Deployment
- [ ] All environment variables set in Railway
- [ ] Square OAuth redirect URI configured
- [ ] Square webhook URL configured
- [ ] Latest code pulled from main
- [ ] Changes tested locally
- [ ] Merged with latest main
- [ ] Tested with merged code

### Deployment
- [ ] Pushed to main branch
- [ ] Railway auto-deploy triggered
- [ ] Web server deployed successfully
- [ ] Worker service deployed successfully
- [ ] No errors in Railway logs

### Post-Deployment
- [ ] Health check passes
- [ ] OAuth flow works
- [ ] Product sync works
- [ ] Product deletion uses soft delete
- [ ] Webhooks received
- [ ] Price adjustments work

---

## 9. Environment Variable Quick Copy List

Copy this list and fill in your values:

```
APP_BASE_URL=
FRONTEND_URL=
HIPOINK_API_BASE_URL=http://43.153.107.21
HIPOINK_USERNAME=
HIPOINK_PASSWORD=
HIPOINK_API_SECRET=
HIPOINK_CLIENT_ID=default
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SHOPIFY_API_KEY=
SHOPIFY_API_SECRET=
SHOPIFY_WEBHOOK_SECRET=
SQUARE_APPLICATION_ID=
SQUARE_APPLICATION_SECRET=
SQUARE_WEBHOOK_SECRET=
SQUARE_ENVIRONMENT=production
SLACK_WEBHOOK_URL=
SLACK_ALERTS_ENABLED=true
APP_ENVIRONMENT=production
LOG_LEVEL=INFO
```

---

## 10. Support

If you encounter issues:
1. Check Railway logs first
2. Verify all environment variables are set
3. Test endpoints manually with curl
4. Check Square Developer Dashboard for configuration
5. Review Supabase database for data issues

---

**Last Updated:** After soft delete fix implementation
**Version:** 1.0
