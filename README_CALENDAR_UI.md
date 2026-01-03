# Calendar UI System - Setup & Usage

## Overview

The system now includes two calendar interfaces:
1. **Shopify Embedded App** - Native Shopify UI for Shopify stores
2. **Centralized Dashboard** - Web dashboard for all other integrations

Both interfaces connect to the same backend API at `/api/strategies/create`.

## Architecture

```
┌─────────────────────┐         ┌──────────────────────┐
│  Shopify App        │         │  Centralized         │
│  (Polaris UI)       │         │  Dashboard           │
│                     │         │  (Next.js)           │
└──────────┬──────────┘         └──────────┬───────────┘
           │                                │
           └────────────┬───────────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │  FastAPI Backend       │
           │  /api/strategies/*     │
           └──────────┬─────────────┘
                      │
                      ▼
           ┌────────────────────────┐
           │  ZKong API             │
           │  /zk/strategy/create   │
           └────────────────────────┘
```

## Features

### Shopify App (`shopify-app/`)
- ✅ Calendar-based strategy creation form
- ✅ Date range picker
- ✅ Repeat options (Daily, Weekly, Monthly)
- ✅ Multiple time windows
- ✅ Price override
- ✅ Promotion text
- ✅ Form validation
- ✅ Success/error notifications

### Centralized Dashboard (`dashboard/`)
- ✅ Calendar view with date selection
- ✅ Strategy listing per date
- ✅ Integration status display
- ✅ Quick stats
- ✅ Create strategy modal (placeholder)

## Setup Instructions

### 1. Backend (FastAPI)
Already running - ensure environment variables are set:
```bash
# .env
ZKONG_API_BASE_URL=https://esl-eu.zkong.com
ZKONG_USERNAME=your_username
ZKONG_PASSWORD=your_password
ZKONG_RSA_PUBLIC_KEY=your_key
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_key
```

Start server:
```bash
uvicorn app.main:app --reload
```

### 2. Shopify App
```bash
cd shopify-app
npm install
npm run dev
```

The app will be available at the URL provided by Shopify CLI.

### 3. Centralized Dashboard
```bash
cd dashboard
npm install
npm run dev
```

Dashboard will be available at `http://localhost:3000`

## API Endpoint

### POST `/api/strategies/create`

**Request Body:**
```json
{
  "store_mapping_id": "uuid",
  "name": "Strategy Name",
  "start_date": "2026-01-03T00:00:00",
  "end_date": "2026-01-03T23:59:59",
  "trigger_type": 1,
  "period_type": 1,
  "period_value": [7],
  "period_times": ["20:15:00", "20:20:00"],
  "products": [
    {
      "barcode": "32985623",
      "item_id": 7717958221914,
      "price": "9.99",
      "original_price": "1.99",
      "promotion_text": "Special Offer"
    }
  ],
  "template_attr_category": "default",
  "template_attr": "default",
  "select_field_name_num": [3, 4]
}
```

**Response:**
```json
{
  "success": true,
  "message": "操作成功",
  "strategy_id": "1218",
  "code": 10000,
  "data": {
    "strategy_id": 1218
  }
}
```

## Current Status

✅ **Completed:**
- Repository cleaned up
- ZKong client has `create_strategy()` method
- Shopify app calendar UI built
- Centralized dashboard structure created
- Backend API endpoints working

⚠️ **Needs Testing:**
- Verify products appear in ZKong dashboard after creation
- Test timezone conversion (UTC vs merchant timezone)
- Test strategy enablement workflow
- Product selection in Shopify app

## Next Steps

1. **Debug Product Issue**: Why products don't appear in ZKong dashboard
2. **Add Product Selector**: Connect Shopify app to Shopify products API
3. **Complete Dashboard**: Build full create form in dashboard
4. **Strategy Management**: Add list/edit/delete endpoints
5. **Enable Strategy**: Implement auto-enable after creation (if API supports)

## Testing

To test strategy creation:
```bash
# Start backend
uvicorn app.main:app --reload

# Test via API docs
open http://localhost:8000/docs

# Or use curl
curl -X POST http://localhost:8000/api/strategies/create \
  -H "Content-Type: application/json" \
  -d @test_payload.json
```

