# Implementation Guide: Square Weight-Based vs Per-Item Pricing for ESL Dynamic Fields

## Overview

This guide explains how to extend the existing Square → Hipoink ESL integration to support **weight-based pricing** (sold by ounce/pound) vs **per-item pricing** (sold by each) using the ESL's dynamic fields **f1, f2, f3, f4**.

### The Goal

Display on ESL screens:
- **Weight-based items** (meat, bulk candy, deli): `$8.99/lb` or `$0.50/oz`
- **Per-item items** (batteries, cans): `$4.99/ea` or `$19.99 each`

### ESL Dynamic Fields Mapping

| Field | Purpose | Example Content |
|-------|---------|-----------------|
| `f1` | Unit quantity (for weight items) | `"1"` (1 oz), `"16"` (16 oz = 1 lb) |
| `f2` | Price per unit (for weight items) | `"$8.99/lb"`, `"$0.50/oz"` |
| `f3` | Item count (for per-item items) | `"1"`, `"12"` (12-pack) |
| `f4` | Price per item | `"$4.99/ea"`, `"$1.25/item"` |

---

## Square API Data Structure

### How Square Determines Sell Type

In Square, the **Unit** dropdown next to the price determines if an item is sold by weight or per-item:

**Location in Square Dashboard:**
```
Items & services → Items → Select item → Variations section → Unit dropdown
```

Options include:
- `ea` (each) - **per item** → Use f3/f4
- `oz` (ounce) - **by weight** → Use f1/f2
- `lb` (pound) - **by weight** → Use f1/f2
- `g` (gram) - **by weight** → Use f1/f2
- `kg` (kilogram) - **by weight** → Use f1/f2
- Custom units

### Square API Fields - Payload Difference

The webhook payload contains `CatalogItemVariation` with different structures based on sell type:

#### **Per-Item (ea) - Default Payload**

When an item is sold "by each" (per-item), the `measurement_unit_id` field is **missing or null**:

```json
{
  "item_variation_data": {
    "item_id": "ABC123",
    "name": "Regular",
    "sku": "CHAIR001",
    "price_money": { 
      "amount": 4000,        // Price in cents ($40.00)
      "currency": "USD" 
    },
    "pricing_type": "FIXED_PRICING"
    // ⚠️ NO measurement_unit_id field - this means "ea" (each)
  }
}
```

**Result:** `measurement_unit_id` is **missing/null** → Use **f3/f4** (per-item fields)

---

#### **Weight-Based (oz, lb, etc.) - Payload with measurement_unit_id**

When an item is sold by weight, the `measurement_unit_id` field is **present**:

```json
{
  "item_variation_data": {
    "item_id": "ABC123",
    "name": "Deli Meat",
    "sku": "MEAT001",
    "price_money": { 
      "amount": 899,        // Price in cents ($8.99)
      "currency": "USD" 
    },
    "pricing_type": "FIXED_PRICING",
    "measurement_unit_id": "XYZ789"  // ← THIS IS THE KEY! Present = weight-based
  }
}
```

**Result:** `measurement_unit_id` **exists** → Need to fetch `CatalogMeasurementUnit` to determine unit type → Use **f1/f2** (weight fields)

**Key Logic:**
- `measurement_unit_id` is **null or missing** → Item is sold as "each" (per-item) → Use **f3/f4**
- `measurement_unit_id` **has a value** → Need to lookup the unit type to determine if it's weight-based

### CatalogMeasurementUnit Structure

When `measurement_unit_id` exists, look up the `CatalogMeasurementUnit`:

```json
{
  "type": "MEASUREMENT_UNIT",
  "id": "XYZ789",
  "measurement_unit_data": {
    "measurement_unit": {
      "weight_unit": "IMPERIAL_WEIGHT_OUNCE"   // ← The unit type
    },
    "precision": 2
  }
}
```

**Weight unit values (from Square API):**

| Square API Value | Display Abbreviation | Use Case |
|------------------|---------------------|----------|
| `IMPERIAL_WEIGHT_OUNCE` | oz | Ounces (meat, deli) |
| `IMPERIAL_POUND` | lb | Pounds (bulk items) |
| `IMPERIAL_STONE` | stone | Stones (rarely used) |
| `METRIC_MILLIGRAM` | mg | Milligrams (pharmaceuticals) |
| `METRIC_GRAM` | g | Grams (small items) |
| `METRIC_KILOGRAM` | kg | Kilograms (large bulk) |

**Reference:** [Square API - MeasurementUnitWeight Enum](https://developer.squareup.com/reference/square/enums/MeasurementUnitWeight)

---

### The Decision Logic Flow

Here's the complete decision logic for determining sell type:

```python
def get_sell_type(item_variation_data, measurement_units_cache):
    """
    Determine if item is sold by weight or per item.
    
    Decision Flow:
    1. Check if measurement_unit_id exists
    2. If missing/null → "item" (per-item, use f3/f4)
    3. If present → Look up CatalogMeasurementUnit
    4. Check if it has weight_unit
    5. If weight_unit exists → "weight" (use f1/f2)
    6. If no weight_unit → "item" (default, use f3/f4)
    """
    measurement_unit_id = item_variation_data.get("measurement_unit_id")
    
    # Case 1: No measurement_unit_id = "ea" (each/per item)
    if not measurement_unit_id:
        return "item"  # → f3/f4
    
    # Case 2: Has measurement_unit_id - check if it's a weight unit
    unit_data = measurement_units_cache.get(measurement_unit_id, {})
    measurement_unit_data = unit_data.get("measurement_unit_data", {})
    measurement_unit = measurement_unit_data.get("measurement_unit", {})
    
    if measurement_unit.get("weight_unit"):
        return "weight"  # → f1/f2
    
    # Case 3: Has measurement_unit_id but NOT a weight (could be volume, length, etc.)
    return "item"  # → f3/f4 (default to per-item)
```

**Visual Flow:**
```
Square Item Variation
    ↓
Has measurement_unit_id?
    ├─ NO → "item" → f3/f4 ($4.99/ea)
    └─ YES → Fetch CatalogMeasurementUnit
            ↓
        Has weight_unit?
            ├─ YES → "weight" → f1/f2 ($8.99/lb)
            └─ NO → "item" → f3/f4 (default)
```

---

## Implementation Steps

### Step 1: Update Square Models (`app/integrations/square/models.py`)

Add models to capture measurement unit data:

**Add these new model classes:**

```python
class MeasurementUnit(BaseModel):
    """Square measurement unit (weight, volume, etc.)"""
    weight_unit: Optional[str] = None  # IMPERIAL_WEIGHT_OUNCE, IMPERIAL_POUND, etc.
    custom_unit: Optional[dict] = None
    
class MeasurementUnitData(BaseModel):
    """Container for measurement unit info"""
    measurement_unit: Optional[MeasurementUnit] = None
    precision: Optional[int] = None

class CatalogMeasurementUnit(BaseModel):
    """Full measurement unit catalog object"""
    type: str  # "MEASUREMENT_UNIT"
    id: str
    measurement_unit_data: Optional[MeasurementUnitData] = None
```

**Update `SquareCatalogObjectVariation` to include `measurement_unit_id`:**

```python
class SquareCatalogObjectVariation(BaseModel):
    """Square catalog object variation (like Shopify variant)."""

    id: Optional[str] = None
    type: Optional[str] = None
    item_variation_data: Optional[Dict[str, Any]] = None
    measurement_unit_id: Optional[str] = None  # ← ADD THIS FIELD

    # ... existing properties ...
```

**Note:** The `measurement_unit_id` is actually inside `item_variation_data`, but we'll extract it in the transformer.

---

### Step 2: Create Measurement Unit Helper Functions (`app/integrations/square/transformer.py`)

Add helper functions to determine sell type and calculate dynamic fields:

**Add at the top of the file (after imports):**

```python
# Unit type mapping (Square API → Display abbreviation)
WEIGHT_UNITS = {
    "IMPERIAL_WEIGHT_OUNCE": "oz",
    "IMPERIAL_POUND": "lb",
    "IMPERIAL_STONE": "stone",
    "METRIC_MILLIGRAM": "mg",
    "METRIC_GRAM": "g",
    "METRIC_KILOGRAM": "kg",
}
```

**Add these new methods to `SquareTransformer` class:**

```python
@staticmethod
def get_sell_type(
    variation_data: dict,
    measurement_units_cache: Dict[str, dict]
) -> Literal["weight", "item"]:
    """
    Determine if item is sold by weight or per item.
    
    Args:
        variation_data: The item_variation_data from Square
        measurement_units_cache: Cache of measurement_unit_id → unit data
    
    Returns:
        'weight' (use f1/f2) or 'item' (use f3/f4)
    """
    measurement_unit_id = variation_data.get("measurement_unit_id")
    
    if not measurement_unit_id:
        return "item"  # No unit = sold as "each" → f3/f4
    
    # Look up the measurement unit
    unit_data = measurement_units_cache.get(measurement_unit_id, {})
    measurement_unit_data = unit_data.get("measurement_unit_data", {})
    measurement_unit = measurement_unit_data.get("measurement_unit", {})
    
    if measurement_unit.get("weight_unit"):
        return "weight"  # Has weight unit (oz, lb) → f1/f2
    
    return "item"  # Default to per-item


@staticmethod
def get_weight_unit_abbrev(measurement_unit_id: str, cache: Dict[str, dict]) -> str:
    """Get the abbreviated unit string (oz, lb, g, kg)"""
    unit_data = cache.get(measurement_unit_id, {})
    measurement_unit_data = unit_data.get("measurement_unit_data", {})
    measurement_unit = measurement_unit_data.get("measurement_unit", {})
    weight_unit = measurement_unit.get("weight_unit", "")
    return WEIGHT_UNITS.get(weight_unit, "ea")


@staticmethod
def calculate_dynamic_fields(
    variation_data: dict,
    measurement_units_cache: Dict[str, dict]
) -> dict:
    """
    Calculate f1, f2, f3, f4 based on sell type.
    
    Returns:
        Dict with keys: sell_type, f1, f2, f3, f4
    """
    sell_type = SquareTransformer.get_sell_type(variation_data, measurement_units_cache)
    
    # Get price in dollars
    price_money = variation_data.get("price_money", {})
    price_cents = price_money.get("amount", 0)
    price_dollars = price_cents / 100
    
    result = {
        "sell_type": sell_type,
        "f1": None,
        "f2": None,
        "f3": None,
        "f4": None
    }
    
    if sell_type == "weight":
        # Weight-based: use f1 (unit qty) and f2 (price per unit)
        measurement_unit_id = variation_data.get("measurement_unit_id")
        unit_abbrev = SquareTransformer.get_weight_unit_abbrev(
            measurement_unit_id, measurement_units_cache
        )
        
        result["f1"] = "1"  # Base unit quantity
        result["f2"] = f"${price_dollars:.2f}/{unit_abbrev}"
    else:
        # Per-item: use f3 (item count) and f4 (price per item)
        result["f3"] = "1"  # Single item
        result["f4"] = f"${price_dollars:.2f}/ea"
    
    return result
```

**Update `_normalize_variation` method to include dynamic fields:**

Add this to the method (after extracting price):

```python
# Extract measurement_unit_id from variation data
measurement_unit_id = None
if variation.item_variation_data:
    measurement_unit_id = variation.item_variation_data.get("measurement_unit_id")

# Calculate dynamic fields (will be empty dict if no measurement_units_cache provided)
# This will be populated when we have the cache in webhook handler
dynamic_fields = {}
if hasattr(self, '_measurement_units_cache'):
    dynamic_fields = SquareTransformer.calculate_dynamic_fields(
        variation.item_variation_data or {},
        self._measurement_units_cache
    )
```

**Add dynamic fields to `NormalizedProduct` extra_data:**

```python
# Create normalized product
normalized = NormalizedProduct(
    source_id=str(catalog_object.id),
    source_variant_id=str(variation.id) if variation.id else None,
    title=product_title,
    barcode=barcode,
    sku=sku,
    price=price_value,
    currency=currency,
    image_url=None,
    # Add dynamic fields to extra_data
    sell_type=dynamic_fields.get("sell_type", "item"),
    f1=dynamic_fields.get("f1"),
    f2=dynamic_fields.get("f2"),
    f3=dynamic_fields.get("f3"),
    f4=dynamic_fields.get("f4"),
)
```

---

### Step 3: Add Measurement Unit Fetching to Square Adapter (`app/integrations/square/adapter.py`)

Add a method to fetch measurement units from Square API:

**Add this method to `SquareIntegrationAdapter` class:**

```python
async def _fetch_measurement_units(
    self,
    access_token: str,
    measurement_unit_ids: List[str],
    base_url: str
) -> Dict[str, dict]:
    """
    Fetch CatalogMeasurementUnit objects from Square API.
    
    Args:
        access_token: Square OAuth access token
        measurement_unit_ids: List of measurement unit IDs to fetch
        base_url: Square API base URL (sandbox or production)
    
    Returns:
        Dict mapping measurement_unit_id → unit data
    """
    if not measurement_unit_ids:
        return {}
    
    try:
        # Use Square's BatchRetrieveCatalogObjects API
        url = f"{base_url}/v2/catalog/batch-retrieve"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "object_ids": measurement_unit_ids,
                    "include_related_objects": False
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        # Build cache from response
        cache = {}
        for obj in data.get("objects", []):
            if obj.get("type") == "MEASUREMENT_UNIT":
                cache[obj.get("id")] = {
                    "measurement_unit_data": obj.get("measurement_unit_data", {})
                }
        
        logger.info(
            "Fetched measurement units from Square",
            unit_count=len(cache),
            requested_count=len(measurement_unit_ids)
        )
        
        return cache
        
    except Exception as e:
        logger.error(
            "Failed to fetch measurement units from Square",
            error=str(e),
            unit_ids=measurement_unit_ids
        )
        return {}
```

**Update `_handle_catalog_update` to fetch and cache measurement units:**

Add this logic **after fetching all items** (around line 292):

```python
# Extract all measurement_unit_ids from items
measurement_unit_ids = set()
for item in all_items:
    item_data = item.get("item_data", {})
    variations = item_data.get("variations", [])
    for variation in variations:
        variation_data = variation.get("item_variation_data", {})
        unit_id = variation_data.get("measurement_unit_id")
        if unit_id:
            measurement_unit_ids.add(unit_id)

# Fetch measurement units from Square API
measurement_units_cache = {}
if measurement_unit_ids:
    measurement_units_cache = await self._fetch_measurement_units(
        access_token=access_token,
        measurement_unit_ids=list(measurement_unit_ids),
        base_url=base_url
    )

# Store cache in transformer for use during normalization
self.transformer._measurement_units_cache = measurement_units_cache
```

**Update the processing loop to use the cache:**

The transformer will automatically use the cache when calculating dynamic fields (from Step 2).

---

### Step 4: Update Sync Worker to Use Dynamic Fields (`app/workers/sync_worker.py`)

Modify the `_build_hipoink_product` method to use Square's dynamic fields:

**Find the section where f1-f4 are calculated (around line 269-346) and add Square-specific logic:**

```python
# Check if this is a Square product with pre-calculated dynamic fields
if product.source_system == "square":
    # Square products have dynamic fields in normalized_data
    normalized = product.normalized_data or {}
    
    # Use pre-calculated fields from Square transformer
    f1 = normalized.get("f1")
    f2 = normalized.get("f2")
    f3 = normalized.get("f3")
    f4 = normalized.get("f4")
    
    # If fields are missing, try to calculate from raw_data
    if not f1 and not f2 and not f3 and not f4:
        # Fallback: extract from raw_data if available
        raw_data = product.raw_data
        if isinstance(raw_data, dict):
            item_data = raw_data.get("item_data", {})
            variations = item_data.get("variations", [])
            for variation in variations:
                variation_data = variation.get("item_variation_data", {})
                if str(variation.get("id")) == str(product.source_variant_id):
                    # Calculate dynamic fields (without cache - basic calculation)
                    measurement_unit_id = variation_data.get("measurement_unit_id")
                    price_money = variation_data.get("price_money", {})
                    price_cents = price_money.get("amount", 0)
                    price_dollars = price_cents / 100
                    
                    if measurement_unit_id:
                        # Weight-based (simplified - assumes oz/lb)
                        f1 = "1"
                        f2 = f"${price_dollars:.2f}/unit"  # Generic unit
                    else:
                        # Per-item
                        f3 = "1"
                        f4 = f"${price_dollars:.2f}/ea"
                    break
else:
    # Existing Shopify logic (keep as-is)
    # ... existing f1-f4 calculation code ...
```

**Update the HipoinkProductItem creation to include all fields:**

```python
hipoink_product = HipoinkProductItem(
    product_code=barcode,
    product_name=normalized.get("title") or product.title,
    product_price=str(round(final_price, 2)),
    product_inner_code=normalized.get("sku") or product.sku,
    product_image_url=normalized.get("image_url") or product.image_url,
    product_qrcode_url=normalized.get("image_url") or product.image_url,
    # Dynamic fields (f1-f4)
    f1=f1,
    f2=f2,
    f3=f3,
    f4=f4,
)
```

---

### Step 5: Update Webhook Handler to Include Related Objects

When fetching catalog items, request measurement units as related objects:

**In `_handle_catalog_update`, update the catalog list API call:**

```python
# When fetching catalog items, include related objects
url = f"{base_url}/v2/catalog/list?types=ITEM"
if cursor:
    url += f"&cursor={cursor}"

# Add include_related_objects parameter
# Note: Square API may include measurement units in related_objects
# if we request them, but we'll fetch them separately for reliability
```

**Alternative approach (more reliable):**

After fetching all items, extract all `measurement_unit_id` values and batch fetch them (as shown in Step 3).

---

### Step 6: Store Dynamic Fields in Database

Ensure dynamic fields are stored in `normalized_data`:

**The `NormalizedProduct.to_dict()` method already includes `extra_data`, so fields like `f1`, `f2`, `f3`, `f4`, `sell_type` will be stored automatically when creating products.**

**Verify in `adapter.py` when creating Product objects:**

```python
product = Product(
    # ... existing fields ...
    normalized_data=normalized.to_dict(),  # This includes f1-f4 from extra_data
    # ... rest of fields ...
)
```

---

## Testing Checklist

### Test Plan to Confirm Payload Structure

Before implementing, verify the payload structure in production:

#### **Test 1: Per-Item (ea) Payload Verification**

1. **Create an item in Square with unit = "ea"**
   - Go to Square Dashboard → Items & services → Items
   - Create new item: "Battery Pack"
   - Set unit dropdown to "ea" (each)
   - Set price: $4.99
   - Save item

2. **Check webhook payload**
   - Trigger webhook or check logs
   - Verify `item_variation_data` object
   - **Expected:** `measurement_unit_id` should be **missing or null**

3. **Verify result**
   - Product should use **f3/f4** fields
   - `f3="1"`, `f4="$4.99/ea"`
   - `f1=None`, `f2=None`

---

#### **Test 2: Weight-Based (oz) Payload Verification**

1. **Create an item in Square with unit = "oz"**
   - Create new item: "Deli Meat"
   - Set unit dropdown to "oz" (ounce)
   - Set price: $0.50 per ounce
   - Save item

2. **Check webhook payload**
   - Verify `item_variation_data` object
   - **Expected:** `measurement_unit_id` should be **present** (e.g., "XYZ789")

3. **Fetch CatalogMeasurementUnit**
   - Use Square API: `POST /v2/catalog/batch-retrieve` with `object_ids: ["XYZ789"]`
   - **Expected:** Response should contain `CatalogMeasurementUnit` with:
     ```json
     {
       "type": "MEASUREMENT_UNIT",
       "id": "XYZ789",
       "measurement_unit_data": {
         "measurement_unit": {
           "weight_unit": "IMPERIAL_WEIGHT_OUNCE"
         }
       }
     }
     ```

4. **Verify result**
   - Product should use **f1/f2** fields
   - `f1="1"`, `f2="$0.50/oz"`
   - `f3=None`, `f4=None`

---

#### **Test 3: Weight-Based (lb) Payload Verification**

1. **Create an item in Square with unit = "lb"**
   - Create new item: "Bulk Candy"
   - Set unit dropdown to "lb" (pound)
   - Set price: $8.99 per pound
   - Save item

2. **Check webhook payload**
   - Verify `measurement_unit_id` is present
   - Fetch the `CatalogMeasurementUnit`
   - **Expected:** `weight_unit` = `"IMPERIAL_POUND"`

3. **Verify result**
   - Product should use **f1/f2** fields
   - `f1="1"`, `f2="$8.99/lb"`
   - `f3=None`, `f4=None`

---

#### **Test 4: Webhook Update Flow**

1. **Change item from "ea" to "oz"**
   - Edit existing item in Square
   - Change unit from "ea" to "oz"
   - Update price if needed
   - Save

2. **Verify webhook triggers**
   - Check webhook logs for `catalog.version.updated` event
   - Verify payload now includes `measurement_unit_id`

3. **Verify product updates**
   - Check database: `normalized_data` should have new `f1`, `f2` values
   - Check sync queue: Product should be queued for Hipoink update
   - Verify Hipoink receives updated fields

---

#### **Test 5: Initial Sync with Mixed Items**

1. **Create multiple test items**
   - Item A: Unit = "ea", Price = $4.99
   - Item B: Unit = "oz", Price = $0.50
   - Item C: Unit = "lb", Price = $8.99
   - Item D: Unit = "g", Price = $0.25

2. **Run initial sync**
   - Trigger sync for Square store
   - Process all items

3. **Verify all items**
   - Item A: `f3="1"`, `f4="$4.99/ea"` (per-item)
   - Item B: `f1="1"`, `f2="$0.50/oz"` (weight)
   - Item C: `f1="1"`, `f2="$8.99/lb"` (weight)
   - Item D: `f1="1"`, `f2="$0.25/g"` (weight)

---

### Test Cases Summary

| Test | Square Unit | measurement_unit_id | Expected Result |
|------|-------------|-------------------|-----------------|
| 1 | ea (each) | **Missing/null** | f3="1", f4="$4.99/ea" |
| 2 | oz (ounce) | **Present** | f1="1", f2="$0.50/oz" |
| 3 | lb (pound) | **Present** | f1="1", f2="$8.99/lb" |
| 4 | g (gram) | **Present** | f1="1", f2="$0.25/g" |
| 5 | kg (kilogram) | **Present** | f1="1", f2="$12.99/kg" |

---

## API Reference

### Square API Endpoints

1. **Batch Retrieve Catalog Objects**
   - Endpoint: `POST /v2/catalog/batch-retrieve`
   - Docs: [Square API - Batch Retrieve Catalog Objects](https://developer.squareup.com/reference/square/catalog-api/batch-retrieve-catalog-objects)
   - Use to fetch measurement units by ID

2. **List Catalog**
   - Endpoint: `GET /v2/catalog/list`
   - Docs: [Square API - List Catalog](https://developer.squareup.com/reference/square/catalog-api/list-catalog)
   - Use to fetch all items (current implementation)

3. **Catalog Objects**
   - [CatalogItemVariation](https://developer.squareup.com/reference/square/objects/CatalogItemVariation)
   - [CatalogMeasurementUnit](https://developer.squareup.com/reference/square/objects/CatalogMeasurementUnit)
   - [MeasurementUnitWeight Enum](https://developer.squareup.com/reference/square/enums/MeasurementUnitWeight)

### Hipoink API

- Endpoint: `POST /api/{client_id}/product/create`
- Fields: `pc`, `pn`, `pp`, `f1`, `f2`, `f3`, `f4`, etc.
- Reference: `Cloud_API_4.0.6_English-1.pdf`

---

## Summary Table

| Square Unit | measurement_unit_id | weight_unit Value | Sell Type | ESL Fields | Display Example |
|-------------|---------------------|-------------------|-----------|------------|-----------------|
| ea (each) | **null/missing** | N/A | `item` | f3, f4 | "$4.99/ea" |
| oz (ounce) | **ID present** | `IMPERIAL_WEIGHT_OUNCE` | `weight` | f1, f2 | "$0.50/oz" |
| lb (pound) | **ID present** | `IMPERIAL_POUND` | `weight` | f1, f2 | "$8.99/lb" |
| g (gram) | **ID present** | `METRIC_GRAM` | `weight` | f1, f2 | "$0.25/g" |
| kg (kilogram) | **ID present** | `METRIC_KILOGRAM` | `weight` | f1, f2 | "$12.99/kg" |

---

## Payload Difference Reference

### Quick Reference: Per-Item vs Weight-Based

**Per-Item Payload (ea):**
```json
{
  "item_variation_data": {
    "price_money": { "amount": 499, "currency": "USD" },
    "pricing_type": "FIXED_PRICING"
    // measurement_unit_id: MISSING or null
  }
}
```
→ **Result:** Use f3/f4

**Weight-Based Payload (oz, lb, etc.):**
```json
{
  "item_variation_data": {
    "price_money": { "amount": 899, "currency": "USD" },
    "pricing_type": "FIXED_PRICING",
    "measurement_unit_id": "XYZ789"  // ← PRESENT
  }
}
```
→ **Result:** Fetch `CatalogMeasurementUnit` → Check `weight_unit` → Use f1/f2

---

## Implementation Order

1. ✅ **Step 1**: Update models to include measurement unit structures
2. ✅ **Step 2**: Add helper functions to transformer for sell type detection
3. ✅ **Step 3**: Add measurement unit fetching to adapter
4. ✅ **Step 4**: Update webhook handler to fetch and cache units
5. ✅ **Step 5**: Update sync worker to use Square dynamic fields
6. ✅ **Step 6**: Test with various Square items (oz, lb, ea)

---

## Notes

- The current sync worker has Shopify-specific f1-f4 logic (lines 269-346). Square products should use the pre-calculated fields from the transformer instead.
- Measurement units are fetched once per webhook event and cached for all variations in that batch.
- If measurement unit fetch fails, items default to "per-item" (f3/f4) to prevent errors.
- The `sell_type` field is stored in `normalized_data` for future template selection logic.

---

## Next Steps After Implementation

1. Test with real Square items (weight-based and per-item)
2. Verify ESL templates display correctly
3. Monitor logs for any measurement unit fetch failures
4. Consider adding unit conversion logic if needed (e.g., display lb price when item is in oz)
5. Add error handling for unsupported unit types
