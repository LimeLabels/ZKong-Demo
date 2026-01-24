# Square Onboarding Product Sync Guide

## 📋 Table of Contents

1. [Overview](#overview)
2. [Understanding API Calls vs Webhooks](#understanding-api-calls-vs-webhooks)
3. [Architecture & Flow](#architecture--flow)
4. [Step-by-Step Implementation Guide](#step-by-step-implementation-guide)
5. [Code Implementation Details](#code-implementation-details)
6. [Error Handling & Edge Cases](#error-handling--edge-cases)
7. [Testing Strategy](#testing-strategy)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This guide explains how to implement automatic product synchronization when a user completes Square onboarding. When a user connects their Square account (clicks "Connect to Square", authorizes, and sees the success message), the system should:

1. **Fetch all existing products** from Square's Catalog API
2. **Transform and normalize** the product data
3. **Save to our database** (Supabase)
4. **Add to sync queue** for processing
5. **Sync to Hipoink ESL dashboard** via background worker

This initial sync establishes a baseline, after which webhooks handle ongoing updates.

---

## Understanding API Calls vs Webhooks

### When to Use Each Approach

#### **Initial Sync (API Calls) - Use During Onboarding**

**Why:** When a user first connects their Square account, you need to pull ALL existing products to establish a baseline in your system.

**When:**
- ✅ User completes OAuth flow and sees success page
- ✅ First-time onboarding (no products in database yet)
- ✅ Re-authentication after token expiration
- ✅ Manual sync trigger (admin action)

**How:**
- Use Square's `GET /v2/catalog/list` API endpoint
- Implement cursor-based pagination to fetch all items
- Process in batches to handle large catalogs

**Advantages:**
- Complete control over what data you fetch
- Can handle large catalogs with pagination
- Reliable for establishing baseline
- Can filter by type (e.g., only ITEM objects)

#### **Ongoing Updates (Webhooks) - Use After Initial Sync**

**Why:** Webhooks provide real-time notifications when products change in Square, eliminating the need for constant polling.

**When:**
- ✅ Product created in Square
- ✅ Product updated (price, name, etc.)
- ✅ Product deleted
- ✅ Inventory changes

**How:**
- Square sends `catalog.version.updated` webhook events
- Your webhook handler processes the event
- Updates database and sync queue accordingly

**Advantages:**
- Real-time updates (no polling delay)
- Efficient (only processes changes)
- Reduces API rate limit usage
- Square handles event delivery

### Best Practice: Hybrid Approach

**Recommended Strategy:**
1. **Initial Sync:** Use API calls during onboarding to fetch all existing products
2. **Ongoing Sync:** Rely on webhooks for real-time updates after initial sync
3. **Fallback:** Periodically verify sync status (optional, for disaster recovery)

---

## Architecture & Flow

### Complete Onboarding Flow Diagram

```
User clicks "Connect to Square"
    ↓
User fills onboarding form (Store Code, Timezone)
    ↓
Frontend redirects to: /auth/square?hipoink_store_code=...&timezone=...
    ↓
Backend initiates Square OAuth
    ↓
User authorizes on Square's page
    ↓
Square redirects to: /auth/square/callback?code=...&state=...
    ↓
Backend exchanges code for access token
    ↓
Backend creates/updates store_mapping
    ↓
[🆕 NEW STEP] Backend triggers initial product sync
    ↓
Backend fetches all products from Square API (with pagination)
    ↓
For each product:
    - Transform to normalized format
    - Save to products table
    - Add to sync_queue
    ↓
Background sync worker processes queue
    ↓
Sync worker sends products to Hipoink ESL API
    ↓
Backend redirects to success page
    ↓
User sees "Connected to Square!" with sync status
```

### Data Flow

```
Square Catalog API
    ↓ (API Call)
Square Adapter (fetch_all_products)
    ↓ (Transform)
Square Transformer (normalize)
    ↓ (Save)
Supabase Products Table
    ↓ (Queue)
Sync Queue Table
    ↓ (Process)
Sync Worker
    ↓ (API Call)
Hipoink ESL API
    ↓ (Update)
ESL Dashboard (User sees products)
```

---

## Step-by-Step Implementation Guide

### Step 1: Create Initial Sync Function

Create a new function in `app/integrations/square/adapter.py` to handle initial product sync.

**Location:** `app/integrations/square/adapter.py`

**Function Signature:**
```python
async def sync_all_products_from_square(
    self,
    merchant_id: str,
    access_token: str,
    store_mapping_id: UUID,
    base_url: str,
) -> Dict[str, Any]:
    """ 
    Fetch all products from Square Catalog API and sync to database.
    
    This function:
    1. Fetches all ITEM objects from Square (with pagination)
    2. Fetches measurement units for weight-based products
    3. Transforms each item to normalized products
    4. Saves to database
    5. Adds to sync queue
    
    Args:
        merchant_id: Square merchant ID
        access_token: Square OAuth access token
        store_mapping_id: Store mapping UUID
        base_url: Square API base URL (sandbox or production)
    
    Returns:
        Dict with sync statistics (total_items, products_created, errors)
    """
```

### Step 2: Implement Pagination Logic

Square's Catalog API uses cursor-based pagination. You need to:

1. Make initial request without cursor
2. Check response for `cursor` field
3. Continue requesting with cursor until no cursor is returned
4. Handle rate limits (Square allows ~10 requests/second)

**Note on Image Handling:** Square's `types=ITEM` response includes an `image_ids` array in the item data, but the actual image URLs are in separate `IMAGE` objects. **Our implementation intentionally does NOT fetch images** - we set `image_url=None` in the transformer. This is safe because:
- The `image_ids` field is optional in our models (`Optional[List[str]] = None`)
- We never access `image_ids` in our code
- The Product model accepts `image_url: Optional[str] = None`
- The sync process will not break or stop if `image_ids` are present in the Square response

If you need images in the future, you would need to:
1. Request `types=ITEM,IMAGE` in the API call
2. Build an `image_id → image_url` lookup map
3. Map `image_ids` to URLs when transforming products

For now, products will have `image_url=None`, which is acceptable for our use case.

**Pagination Implementation:**
```python
all_items = []
cursor = None

async with httpx.AsyncClient() as client:
    while True:
        url = f"{base_url}/v2/catalog/list?types=ITEM"
        if cursor:
            url += f"&cursor={cursor}"
        
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            logger.error("Square API Error", status=response.status_code)
            break
        
        data = response.json()
        all_items.extend(data.get("objects", []))
        
        cursor = data.get("cursor")
        if not cursor:
            break  # No more pages
        
        # Rate limiting: wait 100ms between requests
        await asyncio.sleep(0.1)
```

### Step 3: Fetch Measurement Units

Square products with weight-based pricing require measurement unit data. Fetch these in batch:

```python
# Collect all measurement_unit_ids from items
measurement_unit_ids = set()
for item in all_items:
    item_data = item.get("item_data") or {}
    variations = item_data.get("variations") or []
    for var in variations:
        var_data = var.get("item_variation_data") or {}
        unit_id = var_data.get("measurement_unit_id")
        if unit_id:
            measurement_unit_ids.add(unit_id)

# Fetch measurement units in batch
measurement_units_cache = {}
if measurement_unit_ids:
    measurement_units_cache = await self._fetch_measurement_units(
        access_token=access_token,
        measurement_unit_ids=list(measurement_unit_ids),
        base_url=base_url,
    )
```

### Step 4: Transform and Save Products

For each item, transform to normalized products and save:

```python
processed_count = 0
error_count = 0

for item in all_items:
    try:
        catalog_object = SquareCatalogObject(**item)
        normalized_variants = self.transformer.extract_variations_from_catalog_object(
            catalog_object,
            measurement_units_cache=measurement_units_cache
        )
        
        for normalized in normalized_variants:
            # Validate product
            is_valid, errors = self.validate_normalized_product(normalized)
            
            # Create product record
            product = Product(
                source_system="square",
                source_id=normalized.source_id,
                source_variant_id=normalized.source_variant_id,
                title=normalized.title,
                barcode=normalized.barcode,
                sku=normalized.sku,
                price=normalized.price,
                currency=normalized.currency,
                image_url=normalized.image_url,
                raw_data={"item_data": item},
                normalized_data=normalized.to_dict(),
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None,
            )
            
            # Save to database
            saved = self.supabase_service.create_or_update_product(product)
            processed_count += 1
            
            # Add to sync queue if valid
            if is_valid and store_mapping_id:
                self.supabase_service.add_to_sync_queue(
                    product_id=saved.id,  # type: ignore
                    store_mapping_id=store_mapping_id,  # type: ignore
                    operation="create"  # Use "create" for initial sync
                )
                
    except Exception as e:
        logger.error("Error processing item", item_id=item.get("id"), error=str(e))
        error_count += 1
```

### Step 5: Trigger Sync from OAuth Callback

Modify `app/routers/square_auth.py` to trigger initial sync after store mapping is created/updated.

**Location:** `app/routers/square_auth.py` in `square_oauth_callback` function

**Add after store mapping is created/updated (around line 282):**

```python
# 9) Trigger initial product sync (async, non-blocking)
try:
    from app.integrations.square.adapter import SquareIntegrationAdapter
    
    adapter = SquareIntegrationAdapter()
    
    # Determine if this is a new mapping (first-time sync)
    is_new_mapping = existing_mapping is None
    
    # Trigger sync in background (don't wait for completion)
    # Use asyncio.create_task to run async function without blocking
    import asyncio
    
    async def trigger_initial_sync():
        try:
            result = await adapter.sync_all_products_from_square(
                merchant_id=merchant_id,
                access_token=access_token,
                store_mapping_id=UUID(mapping_id),  # type: ignore
                base_url=base_api_url,
            )
            logger.info(
                "Initial product sync completed",
                merchant_id=merchant_id,
                total_items=result.get("total_items", 0),
                products_created=result.get("products_created", 0),
                errors=result.get("errors", 0),
            )
        except Exception as e:
            logger.error(
                "Initial product sync failed",
                merchant_id=merchant_id,
                error=str(e),
            )
    
    # Start sync in background (fire and forget)
    asyncio.create_task(trigger_initial_sync())
    logger.info("Initial product sync triggered", merchant_id=merchant_id)
    
except Exception as e:
    # Don't fail OAuth callback if sync fails
    logger.error("Failed to trigger initial sync", error=str(e))
```

### Step 6: Update Success Page (Optional)

Update the success page to show sync status. You can:

1. Poll an endpoint to check sync status
2. Show a loading indicator while sync is in progress
3. Display sync statistics when complete

**Location:** `frontend/pages/onboarding/square/success.tsx`

**Add sync status check:**
```typescript
const [syncStatus, setSyncStatus] = useState<'pending' | 'syncing' | 'complete'>('pending');
const [syncStats, setSyncStats] = useState<{total: number; synced: number} | null>(null);

useEffect(() => {
  // Poll sync status
  const checkSyncStatus = async () => {
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/square/sync-status?merchant_id=${merchantId}`
      );
      const data = await response.json();
      setSyncStatus(data.status);
      if (data.stats) {
        setSyncStats(data.stats);
      }
    } catch (error) {
      console.error('Failed to check sync status', error);
    }
  };
  
  // Check immediately, then every 5 seconds
  checkSyncStatus();
  const interval = setInterval(checkSyncStatus, 5000);
  
  return () => clearInterval(interval);
}, [merchantId]);
```

---

## Code Implementation Details

### Complete Initial Sync Function

Here's the complete implementation for `sync_all_products_from_square`:

```python
async def sync_all_products_from_square(
    self,
    merchant_id: str,
    access_token: str,
    store_mapping_id: UUID,
    base_url: str,
) -> Dict[str, Any]:
    """
    Fetch all products from Square Catalog API and sync to database.
    
    Args:
        merchant_id: Square merchant ID
        access_token: Square OAuth access token
        store_mapping_id: Store mapping UUID
        base_url: Square API base URL
    
    Returns:
        Dict with sync statistics
    """
    logger.info(
        "Starting initial product sync from Square",
        merchant_id=merchant_id,
        store_mapping_id=str(store_mapping_id),
    )
    
    # 1. Fetch all items with pagination
    all_items = []
    cursor = None
    page_count = 0
    
    async with httpx.AsyncClient() as client:
        while True:
            page_count += 1
            url = f"{base_url}/v2/catalog/list?types=ITEM"
            if cursor:
                url += f"&cursor={cursor}"
            
            try:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
                
                if response.status_code != 200:
                    logger.error(
                        "Square API error during pagination",
                        status=response.status_code,
                        body=response.text,
                        page=page_count,
                    )
                    break
                
                data = response.json()
                items = data.get("objects", [])
                all_items.extend(items)
                
                logger.debug(
                    "Fetched page of items",
                    page=page_count,
                    items_in_page=len(items),
                    total_items_so_far=len(all_items),
                )
                
                cursor = data.get("cursor")
                if not cursor:
                    break  # No more pages
                
                # Rate limiting: wait 100ms between requests
                await asyncio.sleep(0.1)
                
            except httpx.TimeoutException:
                logger.error("Timeout fetching Square catalog page", page=page_count)
                break
            except Exception as e:
                logger.error("Error fetching Square catalog", page=page_count, error=str(e))
                break
    
    logger.info(
        "Finished fetching items from Square",
        total_items=len(all_items),
        total_pages=page_count,
    )
    
    if not all_items:
        return {
            "status": "success",
            "total_items": 0,
            "products_created": 0,
            "products_updated": 0,
            "errors": 0,
            "message": "No items found in Square catalog",
        }
    
    # 2. Collect measurement unit IDs
    measurement_unit_ids = set()
    for item in all_items:
        item_data = item.get("item_data") or {}
        variations = item_data.get("variations") or []
        for var in variations:
            var_data = var.get("item_variation_data") or {}
            unit_id = var_data.get("measurement_unit_id")
            if unit_id:
                measurement_unit_ids.add(unit_id)
    
    # 3. Fetch measurement units in batch
    measurement_units_cache = {}
    if measurement_unit_ids:
        measurement_units_cache = await self._fetch_measurement_units(
            access_token=access_token,
            measurement_unit_ids=list(measurement_unit_ids),
            base_url=base_url,
        )
        logger.info(
            "Fetched measurement units",
            unit_count=len(measurement_units_cache),
            requested_count=len(measurement_unit_ids),
        )
    
    # 4. Process each item
    products_created = 0
    products_updated = 0
    errors = 0
    queued_count = 0
    
    for item in all_items:
        item_id = item.get("id")
        
        try:
            catalog_object = SquareCatalogObject(**item)
            normalized_variants = self.transformer.extract_variations_from_catalog_object(
                catalog_object,
                measurement_units_cache=measurement_units_cache,
            )
            
            for normalized in normalized_variants:
                # Validate
                is_valid, validation_errors = self.validate_normalized_product(normalized)
                
                # Check if product already exists
                existing = self.supabase_service.get_product_by_source(
                    source_system="square",
                    source_id=normalized.source_id,
                    source_variant_id=normalized.source_variant_id,
                )
                
                # Create or update product
                product = Product(
                    source_system="square",
                    source_id=normalized.source_id,
                    source_variant_id=normalized.source_variant_id,
                    title=normalized.title,
                    barcode=normalized.barcode,
                    sku=normalized.sku,
                    price=normalized.price,
                    currency=normalized.currency,
                    image_url=normalized.image_url,
                    raw_data={"item_data": item},
                    normalized_data=normalized.to_dict(),
                    status="validated" if is_valid else "pending",
                    validation_errors={"errors": validation_errors} if validation_errors else None,
                )
                
                saved = self.supabase_service.create_or_update_product(product)
                
                if existing:
                    products_updated += 1
                else:
                    products_created += 1
                
                # Add to sync queue if valid
                if is_valid and store_mapping_id:
                    try:
                        self.supabase_service.add_to_sync_queue(
                            product_id=saved.id,  # type: ignore
                            store_mapping_id=store_mapping_id,
                            operation="create",  # Use "create" for initial sync
                        )
                        queued_count += 1
                    except Exception as e:
                        logger.error(
                            "Failed to add product to sync queue",
                            product_id=str(saved.id),
                            error=str(e),
                        )
                
        except Exception as e:
            logger.error(
                "Error processing item",
                item_id=item_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            errors += 1
    
    logger.info(
        "Initial product sync completed",
        merchant_id=merchant_id,
        total_items=len(all_items),
        products_created=products_created,
        products_updated=products_updated,
        queued_for_sync=queued_count,
        errors=errors,
    )
    
    return {
        "status": "success",
        "total_items": len(all_items),
        "products_created": products_created,
        "products_updated": products_updated,
        "queued_for_sync": queued_count,
        "errors": errors,
    }
```

### Add Missing Import

Make sure to import `asyncio` and `UUID` at the top of `square_auth.py`:

```python
import asyncio
from uuid import UUID
```

---

## Error Handling & Edge Cases

### 1. Rate Limiting

Square API has rate limits. Handle with exponential backoff:

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def fetch_with_retry(client, url, headers):
    response = await client.get(url, headers=headers, timeout=30.0)
    if response.status_code == 429:  # Rate limited
        retry_after = int(response.headers.get("Retry-After", 60))
        await asyncio.sleep(retry_after)
        raise Exception("Rate limited, retrying")
    response.raise_for_status()
    return response.json()
```

### 2. Large Catalogs

For stores with thousands of products:

- **Process in batches:** Don't load everything into memory
- **Show progress:** Log progress every N items
- **Allow cancellation:** Store sync status in database
- **Resume capability:** Track last processed cursor

### 3. Missing Data

Handle products with missing required fields:

```python
# Skip products without barcode (required for Hipoink)
if not normalized.barcode and not normalized.sku:
    logger.warning("Skipping product without barcode or SKU", item_id=item_id)
    continue

# Use SKU as fallback barcode
barcode = normalized.barcode or normalized.sku
```

**Note on Image Data:** Square items may include `image_ids` in the response, but we intentionally do not fetch or process images. The transformer sets `image_url=None`, and this will not cause any errors or break the sync process. The `image_ids` field is safely ignored, and products will sync successfully without image URLs.

### 4. Duplicate Products

The `create_or_update_product` function handles duplicates automatically using `source_system`, `source_id`, and `source_variant_id` as unique keys.

### 5. Token Expiration

If access token expires during sync:

- Store sync progress in database
- Allow manual retry
- Or refresh token and resume

### 6. Network Failures

Implement retry logic with exponential backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def fetch_with_retry(...):
    # Your fetch logic
    pass
```

---

## Testing Strategy

### 1. Unit Tests

Test individual components:

```python
# test_square_adapter.py
async def test_sync_all_products_pagination():
    """Test pagination handles multiple pages correctly."""
    # Mock Square API responses with cursor
    # Verify all pages are fetched

async def test_sync_all_products_transformation():
    """Test products are transformed correctly."""
    # Mock Square API response
    # Verify normalized products match expected format

async def test_sync_all_products_database_save():
    """Test products are saved to database."""
    # Mock database service
    # Verify create_or_update_product is called
```

### 2. Integration Tests

Test full flow:

```python
async def test_oauth_callback_triggers_sync():
    """Test OAuth callback triggers initial sync."""
    # Mock OAuth callback
    # Verify sync function is called
    # Verify products are queued

async def test_sync_to_hipoink():
    """Test products sync to Hipoink."""
    # Mock sync worker
    # Verify Hipoink API is called with correct data
```

### 3. Manual Testing

1. **Connect Square account** with test store
2. **Verify products appear** in database
3. **Check sync queue** has items
4. **Verify products appear** in Hipoink dashboard
5. **Test with large catalog** (1000+ products)
6. **Test with empty catalog** (no products)

### 4. Load Testing

Test with realistic data:

- 100 products: Should complete in < 30 seconds
- 1000 products: Should complete in < 5 minutes
- 10000 products: Should complete in < 30 minutes (with batching)

---

## Best Practices

### 1. Async Processing

**DO:** Run initial sync in background (non-blocking)
```python
# Fire and forget - don't wait
asyncio.create_task(trigger_initial_sync())
```

**DON'T:** Block OAuth callback waiting for sync
```python
# BAD - blocks user from seeing success page
await trigger_initial_sync()
```

### 2. Logging

Log important events:

```python
logger.info("Starting initial sync", merchant_id=merchant_id)
logger.debug("Fetched page", page=1, items=100)
logger.info("Sync completed", total=500, created=500)
logger.error("Sync failed", error=str(e))
```

### 3. Error Recovery

Store sync status in database:

```python
# Add to store_mapping metadata
metadata["initial_sync_status"] = "in_progress"
metadata["initial_sync_started_at"] = datetime.utcnow().isoformat()
metadata["initial_sync_completed_at"] = None
```

### 4. Progress Tracking

For large catalogs, track progress:

```python
# Update metadata periodically
if processed_count % 100 == 0:
    metadata["initial_sync_progress"] = {
        "processed": processed_count,
        "total": len(all_items),
        "percentage": (processed_count / len(all_items)) * 100,
    }
    # Update store mapping
```

### 5. Idempotency

Ensure sync can be run multiple times safely:

- Use `create_or_update_product` (handles duplicates)
- Check if sync already completed before starting
- Allow manual retry if sync fails

### 6. Webhook Setup

After initial sync, ensure webhooks are configured:

```python
# In OAuth callback, after initial sync
# Verify webhook subscription exists
# If not, create webhook subscription for catalog.version.updated
```

---

## Troubleshooting

### Issue: Sync Never Starts

**Symptoms:** Products don't appear after onboarding

**Check:**
1. Verify OAuth callback completes successfully
2. Check logs for "Initial product sync triggered"
3. Verify `asyncio.create_task` is called
4. Check for exceptions in sync function

**Solution:**
```python
# Add explicit error handling
try:
    asyncio.create_task(trigger_initial_sync())
except Exception as e:
    logger.error("Failed to create sync task", error=str(e))
```

### Issue: Sync Times Out

**Symptoms:** Sync starts but never completes

**Check:**
1. Verify Square API is accessible
2. Check rate limiting (429 errors)
3. Verify access token is valid
4. Check for network timeouts

**Solution:**
- Increase timeout values
- Add retry logic
- Process in smaller batches

### Issue: Products Missing from Hipoink

**Symptoms:** Products in database but not in ESL dashboard

**Check:**
1. Verify sync queue has items
2. Check sync worker is running
3. Verify Hipoink API credentials
4. Check sync_log for errors

**Solution:**
- Manually trigger sync worker
- Check Hipoink API response
- Verify product barcodes are valid

### Issue: Duplicate Products

**Symptoms:** Same product appears multiple times

**Check:**
1. Verify `create_or_update_product` uses correct unique keys
2. Check for duplicate source_id + source_variant_id combinations

**Solution:**
- Ensure unique constraint on (source_system, source_id, source_variant_id)
- Use database upsert logic

### Issue: Missing Measurement Units

**Symptoms:** Weight-based products have incorrect pricing

**Check:**
1. Verify `_fetch_measurement_units` is called
2. Check measurement_units_cache is passed to transformer
3. Verify measurement_unit_id exists in Square

**Solution:**
- Add fallback for missing units
- Log warnings for products without units
- Use default unit if missing

---

## Summary

This guide provides a complete implementation for syncing Square products during onboarding:

1. ✅ **Initial Sync:** Fetch all products via API during onboarding
2. ✅ **Ongoing Updates:** Use webhooks for real-time changes
3. ✅ **Background Processing:** Queue products for Hipoink sync
4. ✅ **Error Handling:** Robust error handling and retry logic
5. ✅ **Best Practices:** Async processing, logging, progress tracking

**Key Implementation Points:**

- Trigger sync in OAuth callback (non-blocking)
- Use cursor-based pagination for Square API
- Fetch measurement units in batch
- Transform and save products to database
- Queue products for Hipoink sync
- Background worker processes queue automatically

**Next Steps:**

1. Implement `sync_all_products_from_square` function
2. Add sync trigger to OAuth callback
3. Test with small catalog first
4. Monitor logs and sync queue
5. Verify products appear in Hipoink dashboard

---

## Additional Resources

- [Square Catalog API Documentation](https://developer.squareup.com/reference/square/catalog-api)
- [Square Webhooks Guide](https://developer.squareup.com/docs/webhooks/overview)
- [Square API Pagination](https://developer.squareup.com/docs/build-basics/common-api-patterns/pagination)
- [Synchronize Catalog with External Platform](https://developer.squareup.com/docs/catalog-api/sync-with-external-system)

---

**Last Updated:** January 2026
**Version:** 1.0
