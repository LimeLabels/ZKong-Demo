# Square Integration Implementation Plan

## 📋 Overview

This document provides a comprehensive, step-by-step plan for integrating Square POS into the ESL middleware system, following the exact same pattern as the existing Shopify integration.

**Goal:** Build a complete Square integration that allows Square stores to sync product prices to Hipoink ESL labels, matching the functionality and architecture of the Shopify integration.

---

## 🏗️ Architecture Reference: The Shopify Pattern

The Square integration will follow the **exact same architecture** as Shopify. Before starting, review these Shopify files to understand the pattern:

### Key Files to Reference (These are your templates):

1. **`app/integrations/shopify/adapter.py`** - Main adapter class implementing `BaseIntegrationAdapter`
2. **`app/integrations/shopify/models.py`** - Pydantic models for Square webhook payloads
3. **`app/integrations/shopify/transformer.py`** - Data transformation logic (Square → Normalized)
4. **`app/integrations/shopify/webhooks.py`** - Webhook-specific handlers (if used)
5. **`app/routers/shopify_auth.py`** - OAuth authentication flow
6. **`app/integrations/base.py`** - Base interface that Square must implement
7. **`app/integrations/registry.py`** - Where Square adapter gets registered

### The Pattern to Follow:

```
Square Integration
    ↓
Adapter (app/integrations/square/adapter.py)
    ↓
Transformer (app/integrations/square/transformer.py)
    ↓
Models (app/integrations/square/models.py)
    ↓
Base Integration Interface (app/integrations/base.py)
    ↓
Registry (app/integrations/registry.py)
    ↓
Webhook Router (app/routers/webhooks_new.py) - Already generic!
    ↓
OAuth Router (app/routers/square_auth.py) - New file needed
    ↓
Database (Supabase) - Same tables, different source_system
    ↓
Background Workers - Already work for any integration!
```

---

## 📚 Prerequisites: Understanding Square API

### Square Developer Account Setup

1. **Create Square Developer Account**
   - Go to https://developer.squareup.com/
   - Create a developer account
   - Create a new application

2. **Get Square Credentials**
   - **Application ID** (like Shopify API Key)
   - **Application Secret** (like Shopify API Secret)
   - **Webhook Signature Key** (for verifying webhooks)

3. **Square OAuth Flow**
   - Square uses OAuth 2.0 (similar to Shopify)
   - Redirect URI must be registered in Square Dashboard
   - Scopes needed: `ITEMS_READ`, `ITEMS_WRITE`, `INVENTORY_READ`, `INVENTORY_WRITE`

4. **Square Webhooks**
   - Square sends webhooks for catalog events
   - Events: `catalog.version.updated`, `inventory.count.updated`
   - Webhooks are verified using HMAC SHA256 signature

### Square API Key Differences from Shopify

| Aspect | Shopify | Square |
|--------|---------|--------|
| Store Identifier | Shop domain (`myshop.myshopify.com`) | Location ID (UUID string) |
| OAuth Scopes | `read_products,write_products` | `ITEMS_READ,ITEMS_WRITE` |
| Product Structure | `products` with `variants` | `catalog_objects` with `item_data` |
| Price Format | String decimal (`"100.00"`) | Money object (`{"amount": 10000, "currency": "USD"}`) - **amount is in cents!** |
| Webhook Signature | `X-Shopify-Hmac-Sha256` header | `X-Square-Signature` header |
| Barcode Field | `barcode` on variant | `sku` on variation, or `item_data.ean` |

**⚠️ CRITICAL DIFFERENCE:** Square prices are in **cents**, not dollars. `10000` = `$100.00`

---

## 🚀 Implementation Steps

### STEP 1: Create Square Integration Directory Structure

**Action:** Create the Square integration folder structure

**Files to Create:**
```
app/integrations/square/
├── __init__.py
├── adapter.py        (Main adapter class)
├── models.py         (Pydantic models for Square webhooks)
├── transformer.py    (Square → Normalized transformation)
└── webhooks.py       (Optional: webhook-specific helpers)
```

**Instructions:**
1. Create `app/integrations/square/` directory
2. Create `__init__.py` with empty content (or just `# Square integration`)

**Reference:** Look at `app/integrations/shopify/__init__.py` for structure

---

### STEP 2: Create Square Pydantic Models

**Action:** Create Pydantic models for Square webhook payloads

**File:** `app/integrations/square/models.py`

**Reference File:** `app/integrations/shopify/models.py`

**Models to Create:**

1. **`SquareCatalogObject`** - Represents a Square catalog object (product/item)
   - Fields from Square API: `id`, `type`, `catalog_v1_id`, `present_at_all_locations`, `item_data`, `category_data`, etc.
   - Use Square's API documentation: https://developer.squareup.com/reference/square/catalog-api

2. **`SquareItemData`** - Represents item data within a catalog object
   - Fields: `name`, `description`, `variations`, `product_type`, `tax_ids`, etc.

3. **`SquareCatalogObjectVariation`** - Represents a variation (like Shopify variant)
   - Fields: `id`, `item_variation_data` (which contains `name`, `price_money`, `sku`, `track_inventory`, etc.)

4. **`SquareMoney`** - Represents money object (amount in cents)
   - Fields: `amount` (integer in cents), `currency` (string like "USD")

5. **`CatalogVersionUpdatedWebhook`** - Webhook payload for catalog.version.updated
   - Fields: `merchant_id`, `type`, `event_id`, `created_at`, `data` (contains `type`, `id`, `catalog_object`)

6. **`InventoryCountUpdatedWebhook`** - Webhook payload for inventory.count.updated
   - Fields: Similar structure to catalog webhook

**Key Differences from Shopify Models:**
- Square uses `catalog_object` with nested `item_data` and `variations`
- Square prices are in `price_money.amount` (cents), not `price` (dollars)
- Square uses `location_id` instead of store domain
- Square has `type` field indicating object type: `"ITEM"`, `"ITEM_VARIATION"`, etc.

**Square API Documentation:**
- Catalog Objects: https://developer.squareup.com/reference/square/catalog-api
- Webhooks: https://developer.squareup.com/docs/webhooks/overview

**Pattern to Follow:**
```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class SquareMoney(BaseModel):
    """Square money object (amount in cents)."""
    amount: int  # Amount in smallest currency unit (cents)
    currency: str = "USD"

class SquareCatalogObjectVariation(BaseModel):
    """Square catalog object variation (like Shopify variant)."""
    id: Optional[str] = None
    item_variation_data: Optional[Dict[str, Any]] = None
    
    # Extract commonly used fields
    @property
    def sku(self) -> Optional[str]:
        return self.item_variation_data.get("sku") if self.item_variation_data else None
    
    @property
    def price_money(self) -> Optional[SquareMoney]:
        price_data = self.item_variation_data.get("price_money") if self.item_variation_data else None
        return SquareMoney(**price_data) if price_data else None

# ... continue with other models
```

---

### STEP 3: Create Square Transformer

**Action:** Create transformer to convert Square data → Normalized format

**File:** `app/integrations/square/transformer.py`

**Reference File:** `app/integrations/shopify/transformer.py`

**Methods to Implement:**

1. **`extract_variations_from_catalog_object(catalog_object: SquareCatalogObject) -> List[NormalizedProduct]`**
   - Similar to Shopify's `extract_variants_from_product`
   - Takes Square catalog object, extracts all variations
   - Returns list of `NormalizedProduct` (one per variation)
   - **CRITICAL:** Convert price from cents to dollars: `amount / 100.0`

2. **`extract_store_location_from_webhook(headers: Dict[str, str], payload: Dict[str, Any]) -> Optional[str]`**
   - Extracts Square Location ID from webhook
   - Square webhooks may include `location_id` in payload or headers
   - Returns Location ID string (UUID format)

3. **`_normalize_variation(catalog_object: SquareCatalogObject, variation: SquareCatalogObjectVariation) -> NormalizedProduct`**
   - Private helper method
   - Converts a single Square variation → `NormalizedProduct`
   - Handles price conversion (cents → dollars)
   - Maps Square fields to normalized fields:
     - `variation.id` → `source_variant_id`
     - `catalog_object.id` → `source_id`
     - `item_data.name` → `title`
     - `variation.sku` or `item_data.ean` → `barcode`
     - `variation.sku` → `sku`
     - `variation.price_money.amount / 100.0` → `price` (convert cents to dollars!)
     - `item_data.image_ids[0]` → `image_url` (may need additional API call to get full URL)

**Pattern to Follow:**
```python
from typing import List, Dict, Any, Optional
from app.integrations.base import NormalizedProduct
from app.integrations.square.models import SquareCatalogObject, SquareCatalogObjectVariation

class SquareTransformer:
    @staticmethod
    def extract_variations_from_catalog_object(
        catalog_object: SquareCatalogObject
    ) -> List[NormalizedProduct]:
        """Extract and normalize variations from Square catalog object."""
        normalized_products = []
        
        # Get item data
        item_data = catalog_object.item_data
        if not item_data:
            return normalized_products
        
        # Get variations
        variations = item_data.get("variations", [])
        
        # If no variations, create one from the item itself
        if not variations:
            # Create synthetic variation...
            pass
        
        # Process each variation
        for variation_data in variations:
            variation = SquareCatalogObjectVariation(**variation_data)
            normalized = SquareTransformer._normalize_variation(catalog_object, variation)
            normalized_products.append(normalized)
        
        return normalized_products
    
    @staticmethod
    def _normalize_variation(
        catalog_object: SquareCatalogObject,
        variation: SquareCatalogObjectVariation
    ) -> NormalizedProduct:
        """Normalize a single Square variation."""
        item_data = catalog_object.item_data or {}
        
        # CRITICAL: Convert price from cents to dollars
        price = 0.0
        if variation.price_money:
            price = variation.price_money.amount / 100.0
        
        # Get barcode (could be in variation SKU or item_data.ean)
        barcode = variation.sku or item_data.get("ean") or None
        
        return NormalizedProduct(
            source_id=catalog_object.id,
            source_variant_id=variation.id,
            title=item_data.get("name", ""),
            barcode=barcode,
            sku=variation.sku,
            price=price,
            currency=variation.price_money.currency if variation.price_money else "USD",
            image_url=None,  # May need to fetch from image_ids
        )
```

---

### STEP 4: Create Square Adapter

**Action:** Create main Square adapter implementing `BaseIntegrationAdapter`

**File:** `app/integrations/square/adapter.py`

**Reference File:** `app/integrations/shopify/adapter.py` (Follow this EXACT pattern!)

**Class to Create:** `SquareIntegrationAdapter(BaseIntegrationAdapter)`

**Methods to Implement (from BaseIntegrationAdapter):**

1. **`get_name() -> str`**
   - Return `"square"`

2. **`verify_signature(payload: bytes, signature: str, headers: Dict[str, str]) -> bool`**
   - Verify Square webhook signature using HMAC SHA256
   - Square uses `X-Square-Signature` header
   - Signature is base64-encoded HMAC of request body + webhook URL
   - Use `settings.square_webhook_secret` (to be added to config)
   - **Reference:** Square webhook verification: https://developer.squareup.com/docs/webhooks/step4validate

3. **`extract_store_id(headers: Dict[str, str], payload: Dict[str, Any]) -> Optional[str]`**
   - Extract Square Location ID from webhook
   - May be in payload `data.object.location_id` or headers
   - Use `SquareTransformer.extract_store_location_from_webhook`

4. **`transform_product(raw_data: Dict[str, Any]) -> List[NormalizedProduct]`**
   - Transform Square catalog object → List of normalized products
   - Parse as `CatalogVersionUpdatedWebhook`
   - Extract `catalog_object` from payload
   - Use `SquareTransformer.extract_variations_from_catalog_object`

5. **`transform_inventory(raw_data: Dict[str, Any]) -> Optional[NormalizedInventory]`**
   - Transform Square inventory webhook → NormalizedInventory
   - Square inventory webhooks have `location_id`, `catalog_object_id`, `quantity`

6. **`get_supported_events() -> List[str]`**
   - Return: `["catalog.version.updated", "inventory.count.updated"]`
   - Or Square's actual event type format

7. **`async handle_webhook(...) -> Dict[str, Any]`**
   - Route to appropriate handler based on event type:
     - `catalog.version.updated` → `_handle_catalog_update`
     - `inventory.count.updated` → `_handle_inventory_update`

**Private Handler Methods (similar to Shopify):**

1. **`async _handle_catalog_update(headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]`**
   - Similar to Shopify's `_handle_product_create` and `_handle_product_update`
   - Extract location_id from payload
   - Get store_mapping by `source_system="square"` and `source_store_id=location_id`
   - Transform Square catalog object to normalized products
   - Save to database (create or update)
   - Add to sync_queue if valid

2. **`async _handle_inventory_update(headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]`**
   - Similar to Shopify's `_handle_inventory_update`
   - Log inventory changes
   - May trigger product updates if needed

**Pattern to Follow:**
```python
from app.integrations.base import BaseIntegrationAdapter, NormalizedProduct, NormalizedInventory
from app.integrations.square.models import CatalogVersionUpdatedWebhook, InventoryCountUpdatedWebhook
from app.integrations.square.transformer import SquareTransformer
from app.config import settings
from app.services.supabase_service import SupabaseService
from app.models.database import Product

class SquareIntegrationAdapter(BaseIntegrationAdapter):
    def __init__(self):
        self.transformer = SquareTransformer()
        self.supabase_service = SupabaseService()
    
    def get_name(self) -> str:
        return "square"
    
    def verify_signature(self, payload: bytes, signature: str, headers: Dict[str, str]) -> bool:
        """Verify Square webhook signature."""
        if not signature:
            return False
        
        # Square signature verification logic
        # Use settings.square_webhook_secret
        # Calculate HMAC SHA256 of payload + webhook URL
        # Compare with signature header
        pass
    
    # ... implement other methods following Shopify pattern exactly
```

---

### STEP 5: Update Configuration for Square

**Action:** Add Square credentials to configuration

**File:** `app/config.py`

**Reference:** Look at how Shopify credentials are added

**Changes to Make:**

Add to `Settings` class:
```python
# Square Configuration
square_webhook_secret: str = ""  # Webhook signature key from Square
square_application_id: str = ""  # Square Application ID (like Shopify API Key)
square_application_secret: str = ""  # Square Application Secret (like Shopify API Secret)
square_environment: str = "sandbox"  # "sandbox" or "production"
square_api_base_url: str = "https://connect.squareup.com"  # Square API base URL
```

**Environment Variables to Add:**
In Railway (or `.env` file):
```
SQUARE_WEBHOOK_SECRET=your_webhook_secret_from_square
SQUARE_APPLICATION_ID=your_application_id
SQUARE_APPLICATION_SECRET=your_application_secret
SQUARE_ENVIRONMENT=sandbox  # or production
```

---

### STEP 6: Create Square OAuth Router

**Action:** Create OAuth authentication flow for Square

**File:** `app/routers/square_auth.py`

**Reference File:** `app/routers/shopify_auth.py` (Follow this pattern, but adapt for Square!)

**Endpoints to Create:**

1. **`GET /auth/square`** - Initiate Square OAuth flow
   - Similar to `shopify_oauth_initiate`
   - Redirect to Square OAuth authorization page
   - Include `client_id`, `scope`, `redirect_uri`, `state`
   - Square OAuth URL format: `https://squareup.com/oauth2/authorize?client_id=...&scope=...&redirect_uri=...&state=...`

2. **`GET /auth/square/callback`** - Handle OAuth callback
   - Similar to `shopify_oauth_callback`
   - Receive authorization code from Square
   - Exchange code for access token
   - Save access token to `store_mappings.metadata['square_access_token']`
   - Also save `location_id` (from Square API call)
   - Create or update store_mapping with `source_system="square"` and `source_store_id=location_id`

3. **`GET /api/auth/me`** - Update to support Square (may already be generic)

**Square OAuth Differences:**

- Square requires you to fetch merchant locations after OAuth
- You need to call `GET /v2/locations` to get `location_id`
- Square tokens are per-application, not per-location (but you still need location_id for store mapping)
- Square may have multiple locations per merchant

**Pattern to Follow:**
```python
@router.get("/square")
async def square_oauth_initiate(
    state: Optional[str] = Query(None, description="State parameter for CSRF protection"),
):
    """Initiate Square OAuth flow."""
    square_app_id = settings.square_application_id
    if not square_app_id:
        raise HTTPException(...)
    
    # Build Square OAuth URL
    scopes = "ITEMS_READ ITEMS_WRITE INVENTORY_READ INVENTORY_WRITE"
    redirect_uri = f"{frontend_url}/auth/square/callback"
    auth_url = (
        f"https://squareup.com/oauth2/authorize?"
        f"client_id={square_app_id}&"
        f"scope={scopes}&"
        f"redirect_uri={redirect_uri}&"
        f"state={state_token}"
    )
    return RedirectResponse(url=auth_url)

@router.get("/square/callback")
async def square_oauth_callback(
    code: str = Query(...),
    state: Optional[str] = Query(None),
):
    """Handle Square OAuth callback."""
    # Exchange code for access token
    token_url = "https://connect.squareup.com/oauth2/token"
    # POST with client_id, client_secret, code
    
    # Get access_token from response
    
    # Fetch merchant locations
    locations_url = "https://connect.squareup.com/v2/locations"
    # GET with Authorization: Bearer {access_token}
    
    # Get location_id from locations response
    
    # Save to store_mappings
    # source_system="square"
    # source_store_id=location_id
    # metadata['square_access_token'] = access_token
```

---

### STEP 7: Register Square Adapter

**Action:** Register Square adapter in integration registry

**File:** `app/integrations/registry.py`

**Changes to Make:**

Uncomment and update the Square integration loading:

```python
def _load_integrations(self):
    # ... existing Shopify loading ...
    
    # Load Square integration
    try:
        from app.integrations.square.adapter import SquareIntegrationAdapter
        
        square_adapter = SquareIntegrationAdapter()
        self.register(square_adapter)
        logger.info(
            "Loaded Square integration", 
            adapter_name=square_adapter.get_name()
        )
    except ImportError as e:
        logger.warning("Could not load Square integration", error=str(e))
    except Exception as e:
        logger.error("Error loading Square integration", error=str(e))
```

---

### STEP 8: Update Webhook Router for Square Signatures

**Action:** Update generic webhook router to handle Square signature extraction

**File:** `app/routers/webhooks_new.py`

**Changes to Make:**

Add Square signature extraction (similar to Shopify):

```python
# Extract signature (integration-specific)
signature = None
if integration_name == "shopify":
    signature = (
        x_shopify_hmac_sha256
        or headers.get("X-Shopify-Hmac-Sha256")
        or headers.get("x-shopify-hmac-sha256")
    )
elif integration_name == "square":
    signature = (
        headers.get("X-Square-Signature")
        or headers.get("x-square-signature")
    )
```

---

### STEP 9: Register Square Router in Main App

**Action:** Add Square auth router to main FastAPI app

**File:** `app/main.py`

**Changes to Make:**

Import and include Square auth router:

```python
from app.routers import square_auth

app.include_router(square_auth.router)
app.include_router(square_auth.api_router)
```

**Reference:** Look for how `shopify_auth` router is included

---

### STEP 10: Update Store Mappings for Square

**Action:** Ensure store_mappings table supports Square location IDs

**Database:** No changes needed! `store_mappings` table already supports any `source_system` and `source_store_id`.

**Just ensure:**
- `source_system = "square"`
- `source_store_id = Square Location ID (UUID string)`
- `metadata` contains `square_access_token` and `location_id`

---

## 🧪 Testing Checklist

### Step-by-Step Testing Plan:

1. **Unit Tests (Optional but Recommended)**
   - Test `SquareTransformer` methods
   - Test price conversion (cents → dollars)
   - Test variation extraction

2. **OAuth Flow Test**
   - Start OAuth flow: `GET /auth/square`
   - Complete OAuth in Square dashboard
   - Verify callback receives code
   - Verify access token is saved to database
   - Verify store_mapping is created with correct location_id

3. **Webhook Test**
   - Create test webhook payload (or use Square webhook simulator)
   - Send POST to `/webhooks/square/catalog.version.updated`
   - Verify signature validation works
   - Verify product is saved to database
   - Verify item is added to sync_queue

4. **Integration Test**
   - Create Square catalog object via Square API
   - Trigger webhook (or manually call webhook endpoint)
   - Verify product appears in Supabase `products` table
   - Verify product appears in `sync_queue` with status="pending"
   - Wait for sync worker (or manually trigger)
   - Verify product is sent to Hipoink API

5. **Price Update Test**
   - Update price in Square
   - Verify webhook is received
   - Verify price is updated in database
   - Verify sync_queue has update operation
   - Verify Hipoink receives updated price

---

## 🔍 Key Implementation Details

### Price Conversion (CRITICAL!)

**Shopify:** Price is a string decimal: `"100.00"` → `100.00`

**Square:** Price is in cents: `{"amount": 10000, "currency": "USD"}` → `100.00`

**Conversion Code:**
```python
# In transformer.py
if variation.price_money:
    price = variation.price_money.amount / 100.0  # Convert cents to dollars
```

### Location ID vs Store Domain

**Shopify:** Uses shop domain as store ID: `"myshop.myshopify.com"`

**Square:** Uses Location ID (UUID): `"18YC4JDH91E1H"`

**Storage:**
- `source_system = "square"`
- `source_store_id = location_id` (the UUID string)
- Also store `location_id` in `metadata` for reference

### Webhook Event Types

**Shopify:** `products/create`, `products/update`, `products/delete`

**Square:** `catalog.version.updated`, `inventory.count.updated`

- Square's `catalog.version.updated` fires for both creates and updates
- Check `catalog_object.is_deleted` to detect deletes

### Barcode/SKU Mapping

**Shopify:** `barcode` field on variant

**Square:** 
- `sku` on variation (item_variation_data.sku)
- `ean` on item_data (item_data.ean)
- Use `sku` first, fallback to `ean`, or use `sku` as barcode if both exist

---

## 📝 Environment Variables Checklist

Add these to Railway (or `.env` for local development):

```bash
# Square Configuration
SQUARE_APPLICATION_ID=your_square_application_id
SQUARE_APPLICATION_SECRET=your_square_application_secret
SQUARE_WEBHOOK_SECRET=your_square_webhook_signature_key
SQUARE_ENVIRONMENT=sandbox  # or production
SQUARE_API_BASE_URL=https://connect.squareup.com
```

---

## 🎯 Success Criteria

The Square integration is complete when:

1. ✅ Square OAuth flow works end-to-end
2. ✅ Square store can be mapped (location_id → hipoink_store_code)
3. ✅ Square webhooks are received and validated
4. ✅ Square products are transformed and saved to database
5. ✅ Square products sync to Hipoink ESL system
6. ✅ Price updates from Square update ESL labels
7. ✅ All Square webhook events are handled (catalog updates, inventory updates)

---

## 🚨 Common Pitfalls to Avoid

1. **Price Conversion:** Always convert Square prices from cents to dollars
2. **Location ID:** Square uses Location ID (UUID), not store domain
3. **Webhook Signature:** Square signature verification may differ from Shopify
4. **Multiple Locations:** Square merchants can have multiple locations; handle location selection
5. **Catalog Objects:** Square uses `catalog_object` with nested `item_data`, not flat `product` structure
6. **Event Types:** Square event types are different (`catalog.version.updated` vs `products/create`)

---

## 📚 Resources

### Square API Documentation:
- Square OAuth: https://developer.squareup.com/docs/oauth-api/overview
- Square Catalog API: https://developer.squareup.com/reference/square/catalog-api
- Square Webhooks: https://developer.squareup.com/docs/webhooks/overview
- Square Webhook Verification: https://developer.squareup.com/docs/webhooks/step4validate
- Square Locations API: https://developer.squareup.com/reference/square/locations-api

### Reference Code:
- `app/integrations/shopify/` - Follow this pattern exactly
- `app/routers/shopify_auth.py` - OAuth pattern to follow
- `app/integrations/base.py` - Interface to implement

---

## ✅ Final Checklist Before Deployment

- [ ] All Square integration files created
- [ ] Square adapter registered in registry
- [ ] Square OAuth router added to main app
- [ ] Configuration updated with Square credentials
- [ ] Webhook router updated for Square signatures
- [ ] OAuth flow tested end-to-end
- [ ] Webhook receiving and validation tested
- [ ] Product transformation tested (price conversion!)
- [ ] Integration tested with real Square store
- [ ] Products syncing to Hipoink successfully
- [ ] Environment variables set in Railway
- [ ] Documentation updated

---

## 🎓 Learning Path for Implementation

If you're using Claude Code or another AI assistant:

1. **Start with Models:** Create `square/models.py` first - it's the foundation
2. **Then Transformer:** Create `transformer.py` - test price conversion logic
3. **Then Adapter:** Create `adapter.py` - wire everything together
4. **Then OAuth:** Create `square_auth.py` - test authentication flow
5. **Finally Integration:** Register and test end-to-end

**Remember:** Test each step before moving to the next. Don't build everything at once!

---

**Good luck! 🚀 You've got this!**
