# Testing with a Real Shopify Store

This guide shows you how to test the integration using your actual Shopify store without needing SQL queries.

## Step 1: Create a Store Mapping via API

Instead of running SQL, we'll use the REST API to create store mappings.

### Option A: Using cURL

```bash
curl -X POST http://localhost:8000/api/store-mappings/ \
  -H "Content-Type: application/json" \
  -d '{
    "source_system": "shopify",
    "source_store_id": "your-shop.myshopify.com",
    "zkong_merchant_id": "your_zkong_merchant_id",
    "zkong_store_id": "your_zkong_store_id",
    "is_active": true
  }'
```

### Option B: Using the FastAPI Docs (Recommended for Testing)

1. Start your server:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Open your browser to: `http://localhost:8000/docs`

3. Find the **POST /api/store-mappings/** endpoint

4. Click "Try it out"

5. Fill in the request body:
   ```json
   {
     "source_system": "shopify",
     "source_store_id": "your-shop.myshopify.com",
     "zkong_merchant_id": "your_zkong_merchant_id",
     "zkong_store_id": "your_zkong_store_id",
     "is_active": true
   }
   ```

6. Click "Execute"

7. You should see a response with the created mapping ID!

### Option C: Using Python Requests

```python
import requests

response = requests.post(
    "http://localhost:8000/api/store-mappings/",
    json={
        "source_system": "shopify",
        "source_store_id": "your-shop.myshopify.com",
        "zkong_merchant_id": "your_zkong_merchant_id",
        "zkong_store_id": "your_zkong_store_id",
        "is_active": True
    }
)

print(response.json())
```

## Step 2: Verify Store Mapping Created

### Option A: Via API

```bash
# List all store mappings
curl http://localhost:8000/api/store-mappings/

# Or use the docs at http://localhost:8000/docs
```

### Option B: Check Supabase

1. Go to Supabase → Table Editor → `store_mappings`
2. You should see your newly created mapping!

## Step 3: Test with Real Shopify Webhook

### 3a. Deploy to Railway (or use ngrok for local testing)

**Option 1: Deploy to Railway** (Recommended)
- Follow the deployment steps in `SETUP_GUIDE.md`
- Use your Railway URL for webhooks

**Option 2: Use ngrok for Local Testing**
```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
```

### 3b. Create Shopify Webhooks

1. Go to Shopify Admin → Settings → Notifications → Webhooks

2. Create these webhooks pointing to your server:

   **Product Create:**
   - URL: `https://your-app.up.railway.app/webhooks/shopify/products/create`
     (or `https://abc123.ngrok.io/webhooks/shopify/products/create` for local)
   - Event: `Product creation`
   - Format: `JSON`

   **Product Update:**
   - URL: `https://your-app.up.railway.app/webhooks/shopify/products/update`
   - Event: `Product update`
   - Format: `JSON`

### 3c. Get Webhook Secret

After creating webhooks, Shopify generates an HMAC secret. You can find it by:
1. Clicking on a webhook
2. Or checking the webhook's details

Add it to your `.env`:
```env
SHOPIFY_WEBHOOK_SECRET=your_webhook_secret_here
```

### 3d. Test the Integration

1. **Create or update a product in Shopify**
   - Go to Products → Add product
   - Fill in:
     - Title
     - **Barcode or SKU** (required!)
     - Price
     - Variants (optional)
   - Save

2. **Check the logs:**
   - Local: Check your terminal where `uvicorn` is running
   - Railway: Check deployment logs

3. **Verify in Supabase:**
   - Go to `products` table → Should see your product
   - Go to `sync_queue` table → Should see pending sync
   - Check `sync_log` after worker processes → Should see sync result

4. **Verify in ZKong:**
   - Log into ZKong dashboard
   - Check if product appears there

## Step 4: Monitor the Sync Process

### Check Sync Status via API

```bash
# Check pending syncs (you can add this endpoint if needed)
# For now, check Supabase directly or logs
```

### Check Supabase Tables

```sql
-- See all products
SELECT id, title, barcode, status FROM products ORDER BY created_at DESC;

-- See sync queue status
SELECT id, operation, status, retry_count, error_message 
FROM sync_queue 
ORDER BY created_at DESC;

-- See sync logs
SELECT operation, status, error_message, created_at 
FROM sync_log 
ORDER BY created_at DESC 
LIMIT 10;
```

## Troubleshooting

### "Store mapping not found" Error

If you get this error when a webhook arrives:
1. Make sure you created the store mapping first (Step 1)
2. Verify `source_store_id` matches your Shopify store domain exactly
3. Check the store mapping is active: `is_active = true`

### Products Not Appearing

1. **Check webhook delivery:**
   - Shopify Admin → Settings → Notifications → Webhooks
   - Click on a webhook → See delivery attempts
   - Check if delivery succeeded

2. **Check product validation:**
   - Products must have a barcode or SKU
   - Products must have a price
   - Check `validation_errors` in `products` table

3. **Check worker is running:**
   - Local: Make sure `python -m app.workers` is running
   - Railway: Check worker service logs

### Webhook Signature Errors

1. Make sure `SHOPIFY_WEBHOOK_SECRET` matches Shopify's secret
2. Verify webhook URL is correct
3. Check webhook format is JSON (not XML)

## Next Steps

Once everything is working:

1. **Add more store mappings** via the API as needed
2. **Monitor sync logs** regularly
3. **Set up alerts** for failed syncs (can add this feature)
4. **Scale up** by adding more integrations beyond Shopify

## API Endpoints Summary

- `POST /api/store-mappings/` - Create store mapping
- `GET /api/store-mappings/` - List all mappings
- `GET /api/store-mappings/{id}` - Get specific mapping
- `PUT /api/store-mappings/{id}` - Update mapping
- `DELETE /api/store-mappings/{id}` - Deactivate mapping

- `POST /webhooks/shopify/products/create` - Shopify webhook
- `POST /webhooks/shopify/products/update` - Shopify webhook
- `POST /webhooks/shopify/products/delete` - Shopify webhook

