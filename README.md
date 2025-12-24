# ZKong ESL Integration Middleware

Middleware system for syncing product data from Shopify (and future integrations) to ZKong's Electronic Shelf Label (ESL) system. This system uses Supabase as a validation buffer, audit trail, and queue system before syncing to ZKong.

## Architecture Overview

```
Shopify Webhooks → FastAPI Receiver → Supabase (Validation/Queue) → Sync Worker → ZKong API
```

The system follows a hybrid approach:
- **Supabase**: Acts as a reliable buffer for validation, audit logging, and queue management
- **ZKong**: The final destination for product data (last-mile source of truth)
- **Retry Logic**: Automatic retry with exponential backoff for transient failures
- **Audit Trail**: Complete logging of all sync attempts and results

## Features

- ✅ Shopify webhook processing (products/create, products/update, products/delete, inventory/update)
- ✅ RSA-authenticated ZKong API integration
- ✅ Automatic variant extraction (each Shopify variant → separate ZKong product)
- ✅ Data validation and normalization
- ✅ Retry logic with exponential backoff
- ✅ Comprehensive audit logging
- ✅ Queue-based async processing
- ✅ Configurable store mappings (Shopify → ZKong)

## Project Structure

```
zkong-demo/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Configuration management
│   ├── models/
│   │   ├── shopify.py          # Shopify webhook models
│   │   ├── zkong.py            # ZKong API models
│   │   └── database.py         # Supabase table models
│   ├── services/
│   │   ├── shopify_service.py  # Shopify data transformation
│   │   ├── zkong_client.py     # ZKong API client
│   │   └── supabase_service.py # Supabase operations
│   ├── routers/
│   │   └── webhooks.py         # Shopify webhook endpoints
│   ├── workers/
│   │   └── sync_worker.py      # Background sync worker
│   └── utils/
│       ├── logger.py           # Logging configuration
│       └── retry.py            # Retry logic utilities
├── supabase/
│   └── migrations/
│       └── 001_initial_schema.sql  # Database schema
├── .env.example
├── requirements.txt
├── Procfile                    # Railway process definitions
├── railway.json                # Railway deployment config
└── README.md
```

## Prerequisites

- Python 3.11+
- Supabase account and project
- ZKong API credentials
- Shopify store with webhook access
- Railway account (for deployment)

## Setup

### 1. Clone and Install Dependencies

```bash
cd ZKong-Demo
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# ZKong API Configuration
ZKONG_API_BASE_URL=https://api.zkong.com
ZKONG_USERNAME=your_zkong_username
ZKONG_PASSWORD=your_zkong_password
ZKONG_RSA_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\nYour RSA Public Key Here\n-----END PUBLIC KEY-----

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Shopify Configuration
SHOPIFY_WEBHOOK_SECRET=your_shopify_webhook_secret

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

### 3. Supabase Setup

1. Create a Supabase project at https://supabase.com
2. Run the migration SQL:

```bash
# Copy the SQL from supabase/migrations/001_initial_schema.sql
# Execute it in your Supabase SQL Editor
```

3. Get your Supabase URL and service role key from project settings

### 4. Store Mapping

Create a store mapping in Supabase to connect your Shopify store to ZKong:

```sql
INSERT INTO store_mappings (
    source_system,
    source_store_id,
    zkong_merchant_id,
    zkong_store_id,
    is_active
) VALUES (
    'shopify',
    'your-shop.myshopify.com',
    'your_zkong_merchant_id',
    'your_zkong_store_id',
    true
);
```

### 5. ZKong API Configuration

1. Obtain your ZKong API credentials (username, password)
2. Get the RSA public key (from ZKong API endpoint 2.1 or your ZKong dashboard)
3. Configure merchant_id and store_id for your ZKong account

### 6. Shopify Webhook Setup

In your Shopify admin, configure webhooks pointing to your deployment:

- **URL**: `https://your-railway-app.up.railway.app/webhooks/shopify/products/create`
- **Events**: 
  - `products/create`
  - `products/update`
  - `products/delete`
  - `inventory_levels/update`
- **Format**: JSON
- **Secret**: Use the same secret in your `.env` as `SHOPIFY_WEBHOOK_SECRET`

## Running Locally

### Start the FastAPI Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

### Start the Sync Worker

In a separate terminal:

```bash
python -m app.workers.sync_worker
```

The worker polls the sync queue every 5 seconds (configurable via `SYNC_WORKER_INTERVAL_SECONDS`).

## API Endpoints

### Health Check

```
GET /health
GET /
```

### Webhook Endpoints

#### Shopify Product Create
```
POST /webhooks/shopify/products/create
Headers:
  X-Shopify-Hmac-Sha256: <signature>
  X-Shopify-Shop-Domain: <store-domain>
  X-Shopify-Topic: products/create
```

#### Shopify Product Update
```
POST /webhooks/shopify/products/update
Headers:
  X-Shopify-Hmac-Sha256: <signature>
  X-Shopify-Shop-Domain: <store-domain>
  X-Shopify-Topic: products/update
```

#### Shopify Product Delete
```
POST /webhooks/shopify/products/delete
Headers:
  X-Shopify-Hmac-Sha256: <signature>
  X-Shopify-Shop-Domain: <store-domain>
```

#### Shopify Inventory Update
```
POST /webhooks/shopify/inventory_levels/update
Headers:
  X-Shopify-Hmac-Sha256: <signature>
  X-Shopify-Shop-Domain: <store-domain>
```

## Deployment to Railway

### 1. Connect Repository

1. Create a Railway account at https://railway.app
2. Create a new project
3. Connect your Git repository

### 2. Configure Environment Variables

In Railway, add all environment variables from your `.env` file:
- Go to your service → Variables
- Add each variable from the environment configuration section

### 3. Deploy Services

Railway will detect the `Procfile` and create two services:

1. **Web Service** (FastAPI server)
   - Process type: `web`
   - Handles webhook requests

2. **Worker Service** (Sync worker)
   - Process type: `worker`
   - Processes sync queue

### 4. Run Database Migration

After deployment, run the Supabase migration SQL in your Supabase SQL Editor (see Supabase Setup above).

### 5. Configure Webhooks

Update your Shopify webhook URLs to point to your Railway deployment:
- `https://your-app.up.railway.app/webhooks/shopify/products/create`
- etc.

## Data Flow

1. **Webhook Received**: Shopify sends webhook to FastAPI endpoint
2. **Signature Verification**: HMAC signature is validated
3. **Store Mapping**: System looks up Shopify store → ZKong store mapping
4. **Data Transformation**: Shopify product variants are extracted and normalized
5. **Validation**: Product data is validated (barcode, price, title required)
6. **Storage**: Product stored in Supabase `products` table
7. **Queue**: Item added to `sync_queue` table
8. **Worker Processing**: Background worker picks up queue item
9. **ZKong Sync**: Product synced to ZKong via API
10. **Audit Log**: Result logged in `sync_log` table
11. **Status Update**: Queue item marked as succeeded/failed

## Database Schema

### Tables

- **store_mappings**: Maps Shopify stores to ZKong stores
- **products**: Normalized product data from source systems
- **sync_queue**: Queue of products pending ZKong sync
- **sync_log**: Audit trail of all sync attempts
- **zkong_products**: Maps our products to ZKong product IDs

See `supabase/migrations/001_initial_schema.sql` for full schema.

## Error Handling

- **Transient Errors**: Network issues, 5xx errors, rate limits → Automatic retry with exponential backoff
- **Permanent Errors**: 4xx validation errors, auth failures → Marked as failed, no retry
- **Max Retries**: Configurable via `MAX_RETRY_ATTEMPTS` (default: 3)
- **Error Logging**: All errors logged in `sync_log` table with details

## Monitoring

- Check sync status in Supabase `sync_log` table
- Monitor worker logs in Railway dashboard
- Use `/health` endpoint for service health checks
- Failed syncs are tracked with error messages and retry counts

## Extending to Other Integrations

The system is designed to support multiple integrations:

1. Add new integration type in `store_mappings.source_system`
2. Create transformer service (similar to `shopify_service.py`)
3. Add webhook router for new integration
4. Configure store mappings in Supabase

## Troubleshooting

### Webhooks Not Received

- Verify Shopify webhook URL is correct
- Check webhook secret matches in `.env`
- Verify HMAC signature validation logs

### Products Not Syncing

- Check `sync_queue` table for pending items
- Verify worker is running (check Railway logs)
- Check `sync_log` for error messages
- Verify ZKong API credentials and store mapping

### Authentication Failures

- Verify ZKong username/password
- Check RSA public key format (must include headers)
- Check ZKong API base URL

## License

[Add your license here]

## Support

[Add support information here]
