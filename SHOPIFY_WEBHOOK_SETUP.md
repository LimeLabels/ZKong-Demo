# How to Get Shopify Webhook Secret

## Step-by-Step Guide

### Step 1: Access Shopify Admin Webhooks

1. **Log into your Shopify admin**
   - Go to: `https://admin.shopify.com/store/jay-store-1234555555623`
   - Or use your store URL

2. **Navigate to Webhooks**
   - In the left sidebar, click **"Settings"** (bottom of sidebar, gear icon)
   - Scroll down and click **"Notifications"**
   - In the Notifications page, click on **"Webhooks"** (usually at the top)

### Step 2: Create a Webhook

1. **Click "Create webhook"** (usually a button in the top right)

2. **Fill in the webhook details:**

   **For Product Create:**
   - **Event**: Select `Product creation`
   - **Format**: Select `JSON`
   - **URL**: 
     - For local testing with ngrok: `https://your-ngrok-url.ngrok.io/webhooks/shopify/products/create`
     - For Railway deployment: `https://your-app.up.railway.app/webhooks/shopify/products/create`
   - **API version**: Select the latest version (or leave default)

3. **Click "Save webhook"**

### Step 3: Get the Webhook Secret

**Important:** Shopify doesn't show the webhook secret directly in the webhook list, but all webhooks for your store share the same secret. Here's how to get it:

#### Option A: From Webhook Settings (Easiest)

1. After creating a webhook, click on the webhook you just created
2. Look for a field called **"HMAC signature"** or **"Webhook secret"**
3. Copy that value

#### Option B: From Webhook Delivery Details

1. Click on any webhook you created
2. Scroll down to see delivery attempts
3. Click on a recent delivery
4. Look for **"HMAC signature"** or **"X-Shopify-Hmac-Sha256"** header
5. The secret is used to generate this signature

#### Option C: Check Shopify App Settings

1. Go to **Settings** → **Apps and sales channels**
2. If you have a custom app, click on it
3. Look for webhook settings there
4. The webhook secret might be displayed there

#### Option D: Generate New Secret (If needed)

If you can't find the secret, you can regenerate it:
1. Go to **Settings** → **Notifications** → **Webhooks**
2. Delete existing webhooks (if you don't need them)
3. Create new webhooks
4. The secret is auto-generated when the first webhook is created

### Step 4: Add Secret to Your .env File

Once you have the webhook secret, add it to your `.env` file:

```env
SHOPIFY_WEBHOOK_SECRET=your_webhook_secret_here
```

**Note:** The secret is usually a long random string, something like:
```
shpss_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz
```

### Step 5: Create All Required Webhooks

You need to create webhooks for all these events:

1. **Product Creation**
   - Event: `Product creation`
   - URL: `.../webhooks/shopify/products/create`

2. **Product Update**
   - Event: `Product update`
   - URL: `.../webhooks/shopify/products/update`

3. **Product Deletion** (optional)
   - Event: `Product deletion`
   - URL: `.../webhooks/shopify/products/delete`

4. **Inventory Update** (optional)
   - Event: `Inventory update`
   - URL: `.../webhooks/shopify/inventory_levels/update`

**All webhooks use the SAME secret!**

---

## Testing Locally (Without Deploying to Railway)

If you want to test webhooks locally first, you'll need to use **ngrok**:

### 1. Install ngrok

```bash
# Download from: https://ngrok.com/download
# Or install via Homebrew (Mac):
brew install ngrok
```

### 2. Start ngrok

```bash
# In a new terminal window
ngrok http 8000
```

### 3. Copy the HTTPS URL

You'll see something like:
```
Forwarding  https://abc123.ngrok.io -> http://localhost:8000
```

### 4. Use ngrok URL in Shopify Webhooks

When creating webhooks in Shopify, use:
```
https://abc123.ngrok.io/webhooks/shopify/products/create
```

**Important:** The ngrok URL changes every time you restart ngrok (unless you have a paid plan). For testing, that's fine, but for production, deploy to Railway and use the permanent URL.

---

## Testing the Webhooks

### 1. Start Your Server

```bash
cd "/Users/jaygadhia/Desktop/ESL Systems/ZKong-Demo"
python3 -m uvicorn app.main:app --reload
```

### 2. Create a Test Product in Shopify

1. Go to **Products** → **Add product**
2. Fill in:
   - **Title**: "Test Product"
   - **Price**: "$9.99"
   - **Barcode or SKU**: "TEST123" (IMPORTANT - required!)
3. Click **"Save product"**

### 3. Check Your Server Logs

You should see logs like:
```
INFO: POST /webhooks/shopify/products/create
INFO: Webhook received from shopify
INFO: Product queued for sync
```

### 4. Check Supabase

- Go to `products` table → Should see your product
- Go to `sync_queue` table → Should see pending sync item

---

## Troubleshooting

### Webhook Secret Not Found

If you can't find the webhook secret:
1. **Check Shopify Help Docs**: Sometimes the secret is shown when you first create a webhook
2. **Use a test webhook**: Create a test webhook and check its headers
3. **Contact Shopify Support**: They can help you find/regenerate the secret

### Webhook Not Arriving

1. **Check webhook URL**: Make sure it's correct
2. **Check server is running**: Your FastAPI server must be running
3. **Check ngrok** (if local): Make sure ngrok is running and URL is correct
4. **Check Shopify webhook delivery**:
   - Go to webhook settings
   - Click on the webhook
   - See "Delivery attempts" - check for errors

### "Invalid webhook signature" Error

1. **Check secret matches**: Make sure `SHOPIFY_WEBHOOK_SECRET` in `.env` matches Shopify's secret
2. **Restart server**: After changing `.env`, restart your server
3. **Check webhook format**: Must be JSON (not XML)

### ngrok URL Expired

- Free ngrok URLs expire when you restart ngrok
- Update webhook URLs in Shopify to new ngrok URL
- Or deploy to Railway for a permanent URL

---

## Quick Checklist

- [ ] Installed ngrok (for local testing)
- [ ] Started FastAPI server
- [ ] Started ngrok (if local testing)
- [ ] Created store mapping via API (`POST /api/store-mappings/`)
- [ ] Created webhook in Shopify
- [ ] Copied webhook secret to `.env` file
- [ ] Restarted server after adding secret
- [ ] Created test product in Shopify
- [ ] Verified webhook received in server logs
- [ ] Verified product in Supabase

---

## Production Deployment

For production, use Railway deployment instead of ngrok:

1. **Deploy to Railway** (follow SETUP_GUIDE.md)
2. **Get your Railway URL**: `https://your-app.up.railway.app`
3. **Update Shopify webhooks** to use Railway URL
4. **Keep webhook secret** - it doesn't change

---

## Example Webhook Secret Format

The secret usually looks like one of these formats:
```
shpss_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz
```
or
```
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
```

It's typically 32-64 characters long, alphanumeric, and may include underscores.

