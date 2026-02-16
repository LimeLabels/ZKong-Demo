# Hipoink ESL Integration Middleware

Middleware system for syncing product data from Shopify (and future integrations) to Hipoink's Electronic Shelf Label (ESL) system. This system uses Supabase as a validation buffer, audit trail, and queue system before syncing to Hipoink.

## Architecture Overview

```
Shopify Webhooks → FastAPI Receiver → Supabase (Validation/Queue) → Sync Worker → Hipoink ESL API
```

The system follows a hybrid approach:
- **Supabase**: Acts as a reliable buffer for validation, audit logging, and queue management
- **Hipoink**: The final destination for product data (last-mile source of truth)
- **Retry Logic**: Automatic retry with exponential backoff for transient failures
- **Audit Trail**: Complete logging of all sync attempts and results

## Features

### Multi-Platform Integrations
- ✅ **Shopify** - Full webhook processing (products/create, products/update, products/delete, inventory/update)
- ✅ **Square POS** - OAuth onboarding, catalog sync, inventory webhooks
- ✅ **Clover POS** - OAuth onboarding, polling sync, webhook support
- ✅ **NCR POS** - Catalog management, price updates

### Core Functionality
- ✅ Hipoink ESL API integration
- ✅ Automatic variant extraction (each variant → separate ESL product)
- ✅ Data validation and normalization across all platforms
- ✅ Retry logic with exponential backoff
- ✅ Comprehensive audit logging
- ✅ Queue-based async processing
- ✅ Configurable store mappings (multi-tenant support)

### Advanced Features
- ✅ **Time-based pricing** - Schedule price changes by time of day
- ✅ **OAuth flows** - Secure merchant onboarding for Square, Clover, Shopify
- ✅ **Token management** - Automatic refresh for Square and Clover tokens
- ✅ **Multiple frontends** - Embedded Shopify app + standalone dashboard + OAuth onboarding pages
- ✅ **Slack notifications** - Error alerts for webhook failures

## Project Structure

```
ZKong-Demo/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI application entry point
│   ├── config.py                    # Configuration management
│   ├── integrations/                # Multi-platform integration adapters
│   │   ├── base.py                  # Base integration interface
│   │   ├── registry.py              # Auto-discovery integration registry
│   │   ├── shopify/                 # Shopify integration
│   │   │   ├── adapter.py           # Shopify integration adapter
│   │   │   ├── models.py            # Shopify webhook models
│   │   │   └── transformer.py       # Data transformation
│   │   ├── square/                  # Square POS integration
│   │   │   ├── adapter.py           # Square integration adapter
│   │   │   ├── api_client.py        # Square API client
│   │   │   └── models.py            # Square data models
│   │   ├── clover/                  # Clover POS integration
│   │   │   ├── adapter.py           # Clover integration adapter
│   │   │   ├── api_client.py        # Clover API client
│   │   │   └── token_encryption.py  # Token security
│   │   └── ncr/                     # NCR POS integration
│   │       ├── adapter.py           # NCR integration adapter
│   │       ├── api_client.py        # NCR API client
│   │       └── models.py            # NCR data models
│   ├── models/
│   │   ├── hipoink.py               # Hipoink ESL API models
│   │   └── database.py              # Supabase table models
│   ├── services/
│   │   ├── hipoink_client.py        # Hipoink ESL API client
│   │   ├── supabase_service.py      # Supabase operations
│   │   └── slack_service.py         # Slack notifications
│   ├── routers/
│   │   ├── webhooks.py              # Consolidated webhook router
│   │   ├── shopify_auth.py          # Shopify OAuth endpoints
│   │   ├── square_auth.py           # Square OAuth endpoints
│   │   ├── clover_auth.py           # Clover OAuth endpoints
│   │   ├── store_mappings.py        # Store mapping CRUD
│   │   ├── products.py              # Product search endpoints
│   │   ├── price_adjustments.py     # Time-based pricing schedules
│   │   ├── external_webhooks.py     # External trigger endpoints
│   │   └── auth.py                  # User authentication
│   ├── workers/
│   │   ├── __main__.py              # Worker entry point
│   │   ├── sync_worker.py           # ESL sync worker
│   │   ├── price_scheduler.py       # Time-based price updates
│   │   ├── token_refresh_scheduler.py # OAuth token refresh
│   │   └── clover_sync_worker.py    # Clover polling sync
│   └── utils/
│       ├── logger.py                # Logging configuration
│       └── retry.py                 # Retry logic utilities
├── frontend/                        # Next.js onboarding app
│   └── pages/
│       └── onboarding/
│           ├── square.tsx           # Square OAuth onboarding
│           └── clover.tsx           # Clover OAuth onboarding
├── shopify-app/                     # Embedded Shopify pricing app
│   └── src/
│       ├── App.tsx                  # Main app component
│       └── components/              # Pricing strategy UI
├── external-tool/                   # Standalone pricing dashboard
│   └── src/
│       ├── App.tsx                  # Dashboard app
│       └── components/              # Dashboard components
├── docs/                            # Additional documentation
│   ├── USER_FLOW.md                 # Complete user flow guide
│   └── TIME_BASED_PRICING.md        # Time-based pricing docs
├── .env.example
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.11+
- Supabase account and project
- Hipoink ESL server (deployed and accessible)
- Shopify store with webhook access

## Setup

### 1. Clone and Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file:

```bash
# Hipoink ESL API Configuration
HIPOINK_API_BASE_URL=http://your-hipoink-server.com
HIPOINK_USERNAME=your_admin_username
HIPOINK_PASSWORD=your_admin_password
HIPOINK_API_SECRET=your_api_secret  # Optional, for request signing
HIPOINK_CLIENT_ID=default  # Default client ID

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Shopify Configuration
SHOPIFY_WEBHOOK_SECRET=your_shopify_webhook_secret
SHOPIFY_API_KEY=your_shopify_api_key
SHOPIFY_API_SECRET=your_shopify_api_secret
APP_BASE_URL=http://localhost:8000

# Application Configuration
APP_ENVIRONMENT=development
LOG_LEVEL=INFO

# Worker Configuration
SYNC_WORKER_INTERVAL_SECONDS=5
MAX_RETRY_ATTEMPTS=3
RETRY_BACKOFF_MULTIPLIER=2.0
RETRY_INITIAL_DELAY_SECONDS=1.0

# Rate Limiting
HIPOINK_RATE_LIMIT_PER_SECOND=10
```

### 3. Supabase Setup

1. Create a Supabase project at https://supabase.com
2. Run the migration SQL from `migrations/001_remove_zkong_add_hipoink.sql`
3. Get your Supabase URL and service role key from project settings

### 4. Store Mapping

Create a store mapping via the API to connect your Shopify store to Hipoink:

```bash
POST /api/store-mappings/
{
  "source_system": "shopify",
  "source_store_id": "your-shop.myshopify.com",
  "hipoink_store_code": "001",
  "is_active": true
}
```

### 5. Hipoink ESL Server Configuration

1. Deploy Hipoink ESL server (refer to Hipoink's official documentation for setup instructions)
2. Obtain your Hipoink admin credentials
3. Get your store code from the Hipoink dashboard
4. Configure API secret if required (default sign: `80805d794841f1b4`)

### 6. Shopify Webhook Setup

In your Shopify admin, configure webhooks pointing to your deployment:

- **URL**: `https://your-deployment.com/webhooks/shopify/products/create`
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

### Store Mappings

```
POST /api/store-mappings/     # Create store mapping
GET /api/store-mappings/       # List store mappings
GET /api/store-mappings/{id}  # Get store mapping
PUT /api/store-mappings/{id}  # Update store mapping
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

## Data Flow

1. **Webhook Received**: Shopify sends webhook to FastAPI endpoint
2. **Signature Verification**: HMAC signature is validated
3. **Store Mapping**: System looks up Shopify store → Hipoink store mapping
4. **Data Transformation**: Shopify product variants are extracted and normalized
5. **Validation**: Product data is validated (barcode, price, title required)
6. **Storage**: Product stored in Supabase `products` table
7. **Queue**: Item added to `sync_queue` table
8. **Worker Processing**: Background worker picks up queue item
9. **Hipoink Sync**: Product synced to Hipoink via API
10. **Audit Log**: Result logged in `sync_log` table
11. **Status Update**: Queue item marked as succeeded/failed

## Database Schema

### Tables

- **store_mappings**: Maps Shopify stores to Hipoink stores (using `hipoink_store_code`)
- **products**: Normalized product data from source systems
- **sync_queue**: Queue of products pending Hipoink sync
- **sync_log**: Audit trail of all sync attempts
- **hipoink_products**: Maps our products to Hipoink product codes

## Hipoink API Integration

The system uses the Hipoink ESL API (Version V1.0.0):
- **Create Product**: `POST /api/{client_id}/product/create`
- **Create Multiple Products**: `POST /api/{client_id}/product/create_multiple`
- Uses `f1` parameter for product array in batch operations
- Default sign: `80805d794841f1b4`

Product fields mapped:
- `pc` (product_code) = barcode
- `pn` (product_name) = title
- `pp` (product_price) = price (as string)
- `pi` (product_inner_code) = sku
- `pim` (product_image_url) = image_url

## Error Handling

- **Transient Errors**: Network issues, 5xx errors, rate limits → Automatic retry with exponential backoff
- **Permanent Errors**: 4xx validation errors, auth failures → Marked as failed, no retry
- **Max Retries**: Configurable via `MAX_RETRY_ATTEMPTS` (default: 3)
- **Error Logging**: All errors logged in `sync_log` table with details

## Monitoring

- Check sync status in Supabase `sync_log` table
- Monitor worker logs
- Use `/health` endpoint for service health checks
- Failed syncs are tracked with error messages and retry counts

## Extending to Other Integrations

The system is designed to support multiple integrations:

1. Add new integration type in `store_mappings.source_system`
2. Create integration adapter (see `app/integrations/shopify/adapter.py` as reference)
3. Add webhook router for new integration
4. Configure store mappings via API

## Troubleshooting

### Webhooks Not Received

- Verify Shopify webhook URL is correct
- Check webhook secret matches in `.env`
- Verify HMAC signature validation logs

### Products Not Syncing

- Check `sync_queue` table for pending items
- Verify worker is running
- Check `sync_log` for error messages
- Verify Hipoink API credentials and store mapping

### Authentication Failures

- Verify Hipoink server is accessible
- Check Hipoink store code is correct
- Verify API sign generation (default: `80805d794841f1b4`)

## License

[Add your license here]

## Support

[Add support information here]
