# Step-by-Step Setup Guide

## ✅ Step 1: Verify Supabase Migration

1. Go to your Supabase project dashboard
2. Navigate to **Table Editor** (left sidebar)
3. Verify you can see these tables:
   - `store_mappings`
   - `products`
   - `sync_queue`
   - `sync_log`
   - `zkong_products`

If all tables are visible, the migration was successful! ✅

---

## 📝 Step 2: Get Your Supabase Credentials

1. In Supabase dashboard, go to **Settings** → **API**
2. Copy these values:
   - **Project URL** (e.g., `https://xxxxx.supabase.co`)
   - **service_role key** (under "Project API keys" → "service_role" - keep this secret!)

Save these for Step 4.

---

## 🏪 Step 3: Create Your First Store Mapping

You need to map your Shopify store to your ZKong store.

1. In Supabase, go to **SQL Editor**
2. Run this SQL (replace with your actual values):

```sql
INSERT INTO store_mappings (
    source_system,
    source_store_id,
    zkong_merchant_id,
    zkong_store_id,
    is_active
) VALUES (
    'shopify',
    'your-shop.myshopify.com',  -- Replace with your Shopify store domain (e.g., 'mystore.myshopify.com')
    'your_zkong_merchant_id',   -- Replace with your ZKong merchant ID
    'your_zkong_store_id',      -- Replace with your ZKong store ID
    true
);
```

**To find your Shopify store domain:**
- Go to your Shopify admin
- Look at the URL: `https://admin.shopify.com/store/YOUR-STORE-NAME`
- Or check Settings → Store details

**To find your ZKong credentials:**
- Check your ZKong dashboard/account settings
- Contact ZKong support if needed

---

## 🔐 Step 4: Set Up Environment Variables Locally

1. Create a `.env` file in the project root (same level as `requirements.txt`):

```bash
cd /Users/jaygadhia/Desktop/ESL\ Systems/ZKong-Demo
touch .env
```

2. Open `.env` and add these variables:

```env
# ZKong API Configuration
ZKONG_API_BASE_URL=https://api.zkong.com
ZKONG_USERNAME=your_zkong_username_here
ZKONG_PASSWORD=your_zkong_password_here
ZKONG_RSA_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----
Your RSA Public Key Here (get from ZKong API endpoint 2.1 or dashboard)
-----END PUBLIC KEY-----

# Supabase Configuration
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_from_step_2

# Shopify Configuration
SHOPIFY_WEBHOOK_SECRET=your_shopify_webhook_secret_here

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

**Important Notes:**
- **ZKONG_RSA_PUBLIC_KEY**: Keep the `-----BEGIN PUBLIC KEY-----` and `-----END PUBLIC KEY-----` lines. For newlines within the key, use `\n` or keep it as a multi-line string
- **SHOPIFY_WEBHOOK_SECRET**: You'll get this when setting up webhooks (Step 8), but you can use any secure random string for now
- Replace all placeholder values with your actual credentials

---

## 🐍 Step 5: Install Dependencies

1. Create a virtual environment (recommended):

```bash
cd /Users/jaygadhia/Desktop/ESL\ Systems/ZKong-Demo
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 🧪 Step 6: Test Locally

### 6a. Test the FastAPI Server

1. Start the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. Open your browser: `http://localhost:8000`
   - You should see: `{"service":"ZKong ESL Integration Middleware","version":"1.0.0","status":"running"}`

3. Test health endpoint: `http://localhost:8000/health`
   - Should return: `{"status":"healthy"}`

### 6b. Test the Sync Worker (in a separate terminal)

1. Open a new terminal
2. Activate the virtual environment:

```bash
cd /Users/jaygadhia/Desktop/ESL\ Systems/ZKong-Demo
source venv/bin/activate
```

3. Start the worker:

```bash
python -m app.workers
```

You should see logs like:
```
INFO     Sync worker started
INFO     Processing sync queue items count=0
```

If you see errors about missing environment variables, go back to Step 4.

---

## 🚂 Step 7: Deploy to Railway

### 7a. Prepare Your Repository

1. Initialize git (if not already done):

```bash
cd /Users/jaygadhia/Desktop/ESL\ Systems/ZKong-Demo
git init
git add .
git commit -m "Initial commit: ZKong ESL Integration Middleware"
```

2. Create a GitHub repository (or use your preferred Git hosting)

3. Push your code:

```bash
git remote add origin <your-github-repo-url>
git branch -M main
git push -u origin main
```

### 7b. Deploy on Railway

1. Go to https://railway.app and sign up/login
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Choose your repository
5. Railway will detect the `Procfile` and create two services:
   - **Web** (FastAPI server)
   - **Worker** (Sync worker)

### 7c. Configure Environment Variables in Railway

1. Click on your **Web** service
2. Go to **Variables** tab
3. Add all environment variables from Step 4 (same values)

**Important:** 
- Add variables to BOTH the Web service AND the Worker service
- Or create a shared variable group if Railway supports it
- For `ZKONG_RSA_PUBLIC_KEY`, paste the entire key (multi-line is fine in Railway)

4. After adding variables, Railway will automatically redeploy

### 7d. Get Your Railway URLs

1. Click on your **Web** service
2. Go to **Settings** → **Networking**
3. Generate a public domain (e.g., `your-app.up.railway.app`)
4. Copy this URL - you'll need it for Shopify webhooks!

---

## 🔗 Step 8: Configure Shopify Webhooks

### 8a. Create Webhook Secret

1. Generate a secure random string:

```bash
# On Mac/Linux:
openssl rand -hex 32

# Or use an online generator
```

2. Save this secret - you'll use it in both Shopify and Railway

3. Add it to Railway environment variables as `SHOPIFY_WEBHOOK_SECRET`

### 8b. Set Up Webhooks in Shopify

1. Go to your Shopify admin: `https://admin.shopify.com/store/YOUR-STORE`
2. Navigate to **Settings** → **Notifications** → **Webhooks**
3. Click **"Create webhook"**

4. For each webhook event, create:

**Webhook 1: Product Created**
- Event: `Product creation`
- Format: `JSON`
- URL: `https://your-app.up.railway.app/webhooks/shopify/products/create`
- API version: Latest
- Click **"Save webhook"**

**Webhook 2: Product Updated**
- Event: `Product update`
- Format: `JSON`
- URL: `https://your-app.up.railway.app/webhooks/shopify/products/update`
- API version: Latest
- Click **"Save webhook"**

**Webhook 3: Product Deleted**
- Event: `Product deletion`
- Format: `JSON`
- URL: `https://your-app.up.railway.app/webhooks/shopify/products/delete`
- API version: Latest
- Click **"Save webhook"**

**Webhook 4: Inventory Update** (optional)
- Event: `Inventory update`
- Format: `JSON`
- URL: `https://your-app.up.railway.app/webhooks/shopify/inventory_levels/update`
- API version: Latest
- Click **"Save webhook"**

### 8c. Get Webhook Secret from Shopify

1. After creating webhooks, Shopify generates an HMAC secret
2. Go to **Settings** → **Notifications** → **Webhooks**
3. Click on any webhook → Look for "HMAC" or "Signature secret"
4. Copy this secret and update `SHOPIFY_WEBHOOK_SECRET` in Railway

**Note:** All webhooks for the same store use the same secret.

---

## ✅ Step 9: Test the Integration

### 9a. Test Webhook Endpoint

1. Create a test product in Shopify (or update an existing one)
2. Check Railway logs:
   - Go to Railway → Your Web service → **Deployments** → Click latest → **View Logs**
   - You should see webhook received logs

3. Check Supabase:
   - Go to **Table Editor** → `products` table
   - You should see your product data
   - Check `sync_queue` table - should have a pending item

### 9b. Verify Sync Worker

1. Check Railway → Worker service → **View Logs**
2. Should see logs like:
   ```
   INFO Processing sync queue items count=1
   INFO Successfully synced product
   ```

3. Check Supabase:
   - `sync_queue` → status should change to "succeeded"
   - `sync_log` → should have a log entry
   - `zkong_products` → should have a mapping if sync succeeded

### 9c. Verify in ZKong

1. Log into your ZKong dashboard
2. Check if your product appears
3. Verify product details match Shopify

---

## 🐛 Troubleshooting

### Webhook not received?

1. **Check Railway logs** for errors
2. **Verify webhook URL** is correct (no typos)
3. **Check Shopify webhook delivery**:
   - Shopify Admin → Settings → Notifications → Webhooks
   - Click on a webhook → See delivery attempts
   - Click on a delivery to see response

### Products not syncing?

1. **Check sync_queue** in Supabase:
   ```sql
   SELECT * FROM sync_queue WHERE status = 'pending' ORDER BY created_at DESC;
   ```

2. **Check sync_log** for errors:
   ```sql
   SELECT * FROM sync_log ORDER BY created_at DESC LIMIT 10;
   ```

3. **Check Worker logs** in Railway

4. **Verify ZKong credentials** are correct

5. **Check product validation**:
   ```sql
   SELECT id, title, barcode, validation_errors FROM products WHERE status = 'pending';
   ```
   - If `validation_errors` has data, fix the product data

### Authentication errors?

1. **Verify ZKong credentials** in Railway environment variables
2. **Check RSA public key format** - must include BEGIN/END lines
3. **Check ZKong API base URL** - might be different for your region

### Worker not running?

1. **Check Railway** → Worker service → Ensure it's deployed
2. **Check environment variables** are set in Worker service too
3. **Check logs** for startup errors

---

## 📊 Monitoring

### Check Sync Status

Run this SQL in Supabase to see sync status:

```sql
-- Pending syncs
SELECT COUNT(*) FROM sync_queue WHERE status = 'pending';

-- Failed syncs
SELECT * FROM sync_queue WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 10;

-- Recent sync activity
SELECT 
    operation,
    status,
    COUNT(*) as count,
    MAX(created_at) as latest
FROM sync_log
GROUP BY operation, status
ORDER BY latest DESC;
```

---

## 🎉 You're Done!

Your integration should now be:
- ✅ Receiving Shopify webhooks
- ✅ Storing products in Supabase
- ✅ Syncing to ZKong automatically
- ✅ Logging all operations

For production:
- Set `APP_ENVIRONMENT=production` in Railway
- Monitor logs regularly
- Set up alerts for failed syncs
- Consider adding monitoring dashboards

---

## Need Help?

- Check logs in Railway
- Review Supabase tables
- Verify ZKong API documentation
- Check error messages in `sync_log` table

