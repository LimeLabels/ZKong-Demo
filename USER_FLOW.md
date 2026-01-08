# Complete User Flow - Hipoink ESL Integration

## Overview

This document describes the complete flow from app installation to running price schedules.

## 🚀 Initial Setup & Installation Flow

### 1. **Shopify App Installation**

```
User clicks "Install App" in Shopify Admin
    ↓
Shopify redirects to: /auth/shopify?shop=myshop.myshopify.com
    ↓
Backend generates OAuth state token and redirects to Shopify OAuth page
    ↓
User approves permissions (read_products, write_products, etc.)
    ↓
Shopify redirects to: /auth/shopify/callback?code=AUTH_CODE&shop=myshop.myshopify.com
    ↓
Backend exchanges authorization code for access token
    ↓
Backend checks for existing store mapping
    ├─ EXISTS: Updates with new OAuth token
    └─ NOT EXISTS: Auto-creates store mapping (without Hipoink store code)
    ↓
Backend redirects to frontend: ?shop=myshop.myshopify.com&installed=true
```

### 2. **Onboarding (First Time)**

```
Frontend detects needs_onboarding=true
    ↓
User sees Onboarding component
    ↓
User enters:
    - Hipoink Store Code (e.g., "001")
    - Store Name (optional)
    - Timezone (e.g., "America/New_York")
    ↓
Frontend calls: PUT /api/store-mappings/{id}
    ↓
Backend updates store mapping with:
    - hipoink_store_code
    - timezone in metadata
    ↓
Page reloads, user enters main app
```

## 📱 Main Application Flow

### 3. **Using the App (Authenticated)**

```
User opens app in Shopify Admin
    ↓
Frontend uses Shopify App Bridge to get shop domain
    ↓
Frontend calls: GET /api/auth/me?shop=myshop.myshopify.com
    ↓
Backend returns:
    - is_authenticated: true
    - needs_onboarding: false
    - store_mapping: { id, hipoink_store_code, timezone }
    ↓
User sees main app interface with two tabs:
    1. Create Strategy
    2. Manage Strategies
```

## 🛍️ Creating a Pricing Strategy

### 4. **Create Strategy Flow**

```
User clicks "Create Strategy" tab
    ↓
User fills out form:
    - Strategy Name
    - Start/End Dates
    - Repeat Type (none/daily/weekly/monthly)
    - Time Slots (e.g., 9:00 AM - 5:00 PM)
    - Trigger Stores (optional)
    ↓
User clicks "Select Product"
    ↓
Product Picker modal opens
    ↓
User searches for product (barcode/SKU/name)
    ↓
Frontend calls: GET /api/products/search?shop=...&q=...
    ↓
Backend:
    1. Searches local database
    2. Searches Shopify API using stored access token
    3. Returns merged results
    ↓
User selects product
    ↓
Form auto-fills:
    - Barcode
    - Original Price
    ↓
User enters:
    - Promotional Price
    - (optional) Additional products
    ↓
User clicks "Create Strategy"
    ↓
Frontend calls: POST /api/price-adjustments/create
    Body: {
        store_mapping_id: "uuid-from-auth",
        name: "...",
        products: [{ pc: "barcode", pp: "new_price", original_price: 10.99 }],
        start_date: "...",
        time_slots: [{ start_time: "09:00", end_time: "17:00" }],
        repeat_type: "daily"
    }
    ↓
Backend:
    1. Validates store mapping exists
    2. Calculates next_trigger_at time
    3. Creates schedule in database
    ↓
Frontend shows success message
    ↓
Form resets
```

## ⚙️ Background Workers (Always Running)

### 5. **Sync Worker** (Product Sync from Shopify → Hipoink)

```
Worker runs every 5 seconds (configurable)
    ↓
Checks sync_queue for pending items
    ↓
For each pending item:
    1. Gets product from database
    2. Gets store mapping
    3. Transforms to Hipoink format
    4. Calls Hipoink API to create/update product
    5. Logs result to sync_log
    6. Marks queue item as succeeded/failed
```

**Triggered by:**
- Shopify webhooks: `products/create`, `products/update`, `products/delete`, `inventory_levels/update`
- Webhook → Database → Queue → Worker → Hipoink

### 6. **Price Scheduler** (Time-Based Price Adjustments)

```
Worker runs every 60 seconds
    ↓
Checks price_adjustment_schedules for:
    - is_active = true
    - next_trigger_at <= current_time
    ↓
For each due schedule:
    1. Gets store mapping and timezone
    2. Checks if current time is in a time slot
    3. Determines if at START or END of slot
    ├─ START: Apply promotional price
    │   - Updates Hipoink via API
    │   - Updates Shopify via API (if credentials available)
    │   - Sets next_trigger_at to end of current slot
    └─ END: Restore original price
        - Updates Hipoink via API
        - Updates Shopify via API
        - Sets next_trigger_at to next occurrence
    ↓
Updates schedule with last_triggered_at and next_trigger_at
```

## 📊 Managing Strategies

### 7. **View/Delete Strategies**

```
User clicks "Manage Strategies" tab
    ↓
Frontend calls: GET /api/price-adjustments/?store_mapping_id=...
    ↓
Backend returns list of all schedules for this store
    ↓
User sees list with:
    - Strategy name
    - Order number
    - Product count
    - Time slots
    - Next trigger time
    - Active/Inactive status
    ↓
User can:
    - View details (modal)
    - Delete strategy (deactivates schedule)
```

## 🔄 Continuous Operation

### 8. **Product Sync (Ongoing)**

```
Shopify product changes
    ↓
Webhook sent to: POST /webhooks/shopify/products/update
    ↓
Backend:
    1. Verifies HMAC signature
    2. Finds store mapping for shop
    3. Transforms product data
    4. Stores in products table
    5. Adds to sync_queue
    ↓
Sync Worker picks it up (within 5 seconds)
    ↓
Product synced to Hipoink ESL system
```

### 9. **Price Schedules (Ongoing)**

```
Price Scheduler checks every minute
    ↓
Finds schedules due to trigger
    ↓
Applies or restores prices automatically
    ↓
Updates next_trigger_at for future occurrences
    ↓
Repeats for daily/weekly schedules
```

## 🔐 Authentication & Session

### 10. **Session Management**

```
User opens app
    ↓
Frontend extracts shop from URL (Shopify embedded app context)
    ↓
Calls /api/auth/me?shop=...
    ↓
Backend checks:
    - Store mapping exists?
    - OAuth token valid?
    - Hipoink store code set?
    ↓
Returns authentication state
    ↓
Frontend shows appropriate UI:
    - Onboarding (if needed)
    - Main app (if authenticated)
    - Error message (if OAuth missing)
```

## 📝 Key Data Flow Diagram

```
┌─────────────┐
│   Shopify   │
│    Store    │
└──────┬──────┘
       │
       │ 1. Install App (OAuth)
       ▼
┌──────────────────┐
│  FastAPI Backend │
│  - OAuth Handler │
│  - Store Mapping │
└──────┬───────────┘
       │
       │ 2. Onboarding
       ▼
┌──────────────────┐
│   Supabase DB    │
│  - store_mappings│
│  - products      │
│  - schedules     │
└──────┬───────────┘
       │
       │ 3. Create Strategy
       ▼
┌──────────────────┐
│  Frontend (React)│
│  - Product Picker│
│  - Calendar Form │
└──────┬───────────┘
       │
       │ 4. Schedule Created
       ▼
┌──────────────────┐
│  Price Scheduler │
│  (Background)    │
│  - Checks every  │
│    60 seconds    │
└──────┬───────────┘
       │
       │ 5. Trigger Time Reached
       ▼
┌──────────────────┐     ┌──────────────┐
│   Hipoink ESL    │     │   Shopify    │
│      API         │     │     API      │
│  (Price Update)  │     │ (Price Update)│
└──────────────────┘     └──────────────┘
```

## 🚦 Running the System

### Required Services:

1. **FastAPI Backend** (Port 8000)
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. **Background Workers** (Same process or separate)
   ```bash
   python -m app.workers
   ```
   This runs:
   - Sync Worker (checks every 5 seconds)
   - Price Scheduler (checks every 60 seconds)

3. **Frontend** (Port 3000)
   ```bash
   cd shopify-app
   npm install
   npm run dev
   ```

4. **Shopify CLI** (For development)
   ```bash
   cd shopify-app
   shopify app dev
   ```

## 🔑 Environment Variables Required

```env
# Shopify
SHOPIFY_API_KEY=your_app_api_key
SHOPIFY_API_SECRET=your_app_secret
SHOPIFY_WEBHOOK_SECRET=your_webhook_secret
APP_BASE_URL=https://your-backend-url.com

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_key

# Hipoink
HIPOINK_API_BASE_URL=http://your-hipoink-server.com
HIPOINK_USERNAME=admin
HIPOINK_PASSWORD=admin_password
HIPOINK_CLIENT_ID=default
```

## ✅ What Happens Automatically

1. **Product Sync**: Whenever products change in Shopify, they automatically sync to Hipoink (via webhooks + worker)

2. **Price Adjustments**: Scheduled price changes run automatically at specified times

3. **Token Refresh**: OAuth tokens are stored and used automatically (refresh handled by Shopify)

4. **Timezone Handling**: All times are converted to store's timezone automatically

5. **Error Retry**: Failed syncs are retried automatically (configurable retry logic)

## 🎯 Summary

**For Store Owners:**
1. Install app → Complete onboarding → Create strategies → Prices change automatically

**For Developers:**
1. OAuth handles authentication
2. Workers handle background tasks
3. Webhooks handle real-time product sync
4. Scheduler handles time-based pricing
5. Frontend provides user interface

The system runs continuously with minimal user intervention!
