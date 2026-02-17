"""
Square data transformation service.
Transforms Square catalog data into normalized format for Hipoink ESL API.
Each Square variation becomes a separate Hipoink product.
"""

from typing import Any, Literal

import structlog

from app.integrations.base import NormalizedProduct
from app.integrations.square.models import (
    SquareCatalogObject,
    SquareCatalogObjectVariation,
)

logger = structlog.get_logger()

# Unit type mapping (Square API → Display abbreviation)
WEIGHT_UNITS = {
    "IMPERIAL_WEIGHT_OUNCE": "oz",
    "IMPERIAL_POUND": "lb",
    "IMPERIAL_STONE": "stone",
    "METRIC_MILLIGRAM": "mg",
    "METRIC_GRAM": "g",
    "METRIC_KILOGRAM": "kg",
}


class SquareTransformError(Exception):
    """Raised when Square data transformation fails."""

    pass


class SquareTransformer:
    """Service for transforming Square webhook data to normalized format."""

    @staticmethod
    def get_sell_type(
        variation_data: dict, measurement_units_cache: dict[str, dict]
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
    def get_weight_unit_abbrev(measurement_unit_id: str, cache: dict[str, dict]) -> str:
        """Get the abbreviated unit string (oz, lb, g, kg)"""
        unit_data = cache.get(measurement_unit_id, {})
        measurement_unit_data = unit_data.get("measurement_unit_data", {})
        measurement_unit = measurement_unit_data.get("measurement_unit", {})
        weight_unit = measurement_unit.get("weight_unit", "")
        return WEIGHT_UNITS.get(weight_unit, "ea")

    @staticmethod
    def extract_unit_cost(variation_data: dict, catalog_object: dict | None = None) -> float | None:
        """
        Extract unit cost for Square Plus/Retail users.

        Priority order (most likely first):
        1. default_unit_cost (native Square Retail field) - stored in CENTS
        2. Direct keys in variation_data (unit_cost, cost_per_unit, etc.)
        3. Custom attributes (fallback)

        Args:
            variation_data: The item_variation_data dict from Square
            catalog_object: Optional parent catalog object dict (for custom attributes)

        Returns:
            Unit cost as float (in dollars) if found, None otherwise
        """
        # Priority 1: Check native Square Retail field (MOST LIKELY for Plus users)
        # This is stored like price_money: {"amount": 500, "currency": "USD"} or just 500 (in cents)
        if "default_unit_cost" in variation_data:
            cost_money = variation_data["default_unit_cost"]

            if isinstance(cost_money, dict):
                # Money object format: {"amount": 500, "currency": "USD"}
                amount = cost_money.get("amount")
                if amount is not None:
                    return float(amount) / 100.0  # Convert cents to dollars
            elif isinstance(cost_money, (int, float)):
                # Direct number (already in cents)
                return float(cost_money) / 100.0

        # Priority 2: Check direct keys in variation_data
        # Sometimes stored as flat fields (already in dollars)
        for key in ["unit_cost", "cost_per_unit", "unit_price", "cost"]:
            if key in variation_data:
                val = variation_data[key]
                if val is not None:
                    try:
                        # If it's a number > 1000, might be in cents, otherwise assume dollars
                        cost = float(val)
                        if cost > 1000:
                            return cost / 100.0  # Likely in cents
                        return cost  # Already in dollars
                    except (ValueError, TypeError):
                        continue

        # Priority 3: Check custom attributes (fallback - rarely used for unit cost)
        custom_attrs = variation_data.get("custom_attribute_values", {})
        if custom_attrs:
            for key, val_obj in custom_attrs.items():
                if "cost" in key.lower():
                    # Custom attribute format: {"string_value": "5.00"} or {"number_value": 5.00}
                    if isinstance(val_obj, dict):
                        val = val_obj.get("number_value") or val_obj.get("string_value")
                        if val:
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                continue

        # Check parent catalog object custom attributes (if provided)
        if catalog_object and isinstance(catalog_object, dict):
            parent_attrs = catalog_object.get("custom_attribute_values", {})
            if parent_attrs:
                for key, val_obj in parent_attrs.items():
                    if "cost" in key.lower():
                        if isinstance(val_obj, dict):
                            val = val_obj.get("number_value") or val_obj.get("string_value")
                            if val:
                                try:
                                    return float(val)
                                except (ValueError, TypeError):
                                    continue

        return None

    @staticmethod
    def normalize_unit_cost_to_ounces(
        unit_cost: float, measurement_unit_id: str | None, measurement_units_cache: dict[str, dict]
    ) -> float:
        """
        Normalize unit cost to price per ounce for weight-based items.

        If the measurement unit is pounds, converts to ounces (1 lb = 16 oz).
        If already in ounces, returns as-is.
        For non-weight items, returns the cost unchanged.

        Args:
            unit_cost: Unit cost in dollars (already extracted)
            measurement_unit_id: Square measurement unit ID
            measurement_units_cache: Cache of measurement_unit_id → unit data

        Returns:
            Unit cost normalized to price per ounce (for weight items) or original cost
        """
        if not measurement_unit_id:
            # Not a weight-based item, return as-is
            return unit_cost

        # Look up the measurement unit
        unit_data = measurement_units_cache.get(measurement_unit_id, {})
        measurement_unit_data = unit_data.get("measurement_unit_data", {})
        measurement_unit = measurement_unit_data.get("measurement_unit", {})
        weight_unit = measurement_unit.get("weight_unit", "")

        # Convert pounds to ounces (1 pound = 16 ounces)
        if weight_unit == "IMPERIAL_POUND":
            # Unit cost is per pound, convert to per ounce
            return unit_cost / 16.0
        elif weight_unit == "IMPERIAL_WEIGHT_OUNCE":
            # Already in ounces, return as-is
            return unit_cost
        else:
            # Other weight units (grams, kg, etc.) - for now, return as-is
            # Future: could add more conversions if needed
            return unit_cost

    @staticmethod
    def calculate_dynamic_fields(
        variation_data: dict,
        measurement_units_cache: dict[str, dict],
        catalog_object: dict | None = None,
    ) -> dict:
        """
        Calculate f1, f2, f3, f4 based on unit cost calculation.

        Logic:
        - pp (product_price) = Total pack price (from Square price_money)
        - For weight-based items:
          - f4 = Price per ounce (from unit cost, converts pounds to ounces if needed)
          - f3 = Total ounces (calculated: pp ÷ f4)
          - f1 and f2 = None (not used)
        - For per-item products:
          - f2 = Price per unit (from unit cost)
          - f1 = Total units (calculated: pp ÷ f2)
          - f3 and f4 = None (not used)

        Args:
            variation_data: The item_variation_data dict from Square
            measurement_units_cache: Cache of measurement_unit_id → unit data
            catalog_object: Optional parent catalog object dict (for custom attributes)

        Returns:
            Dict with keys: sell_type, f1, f2, f3, f4
        """
        sell_type = SquareTransformer.get_sell_type(variation_data, measurement_units_cache)

        # Get total price in dollars (the pack price - pp)
        price_money = variation_data.get("price_money") or {}
        price_cents = price_money.get("amount", 0) or 0
        total_price = (price_cents / 100.0) if price_cents else 0.0

        # Extract unit cost (for Plus users)
        unit_cost = SquareTransformer.extract_unit_cost(variation_data, catalog_object)

        # Initialize result
        result = {"sell_type": sell_type, "f1": None, "f2": None, "f3": None, "f4": None}

        # Calculate fields only if unit cost exists (Plus users)
        if unit_cost and unit_cost > 0 and total_price > 0:
            # For weight-based items: use f3 (total ounces) and f4 (price per ounce)
            if sell_type == "weight":
                measurement_unit_id = variation_data.get("measurement_unit_id")
                # Normalize to ounces (converts pounds to ounces if needed)
                unit_cost_per_ounce = SquareTransformer.normalize_unit_cost_to_ounces(
                    unit_cost, measurement_unit_id, measurement_units_cache
                )
                # Calculate total ounces: total_price ÷ price_per_ounce
                total_ounces = total_price / unit_cost_per_ounce

                # Format as numeric strings (no currency symbols, no units)
                ounces_str = f"{total_ounces:.2f}"
                cost_per_ounce_str = f"{unit_cost_per_ounce:.2f}"

                result["f3"] = ounces_str  # Total ounces (pp ÷ f4)
                result["f4"] = cost_per_ounce_str  # Price per ounce (numeric only)
                # f1 and f2 remain None for weight-based items
            else:
                # Per-item: use f1 (total units) and f2 (price per unit)
                # No conversion needed for per-item products
                total_units = total_price / unit_cost
                units_str = f"{total_units:.2f}"
                cost_per_unit_str = f"{unit_cost:.2f}"

                result["f1"] = units_str  # Total units (pp ÷ f2)
                result["f2"] = cost_per_unit_str  # Price per unit (numeric only)
                # f3 and f4 remain None for per-item products

        # If no unit cost (non-Plus user), fields stay None - that's OK!
        # Users can manually enter f1-f4 values in ESL dashboard if needed
        # The main price field (pp) will still show the total_price

        return result

    @staticmethod
    def extract_variations_from_catalog_object(
        catalog_object: SquareCatalogObject,
        measurement_units_cache: dict[str, dict] | None = None,
    ) -> list[NormalizedProduct]:
        """
        Extract and normalize variations from Square catalog object.
        Each variation becomes a separate normalized product.

        Args:
            catalog_object: Square catalog object
            measurement_units_cache: Optional cache of measurement_unit_id → unit data

        Returns:
            List of normalized products
        """
        normalized_products = []

        # Get item data
        item_data = catalog_object.item_data
        if not item_data:
            logger.warning(
                "Catalog object has no item_data",
                catalog_object_id=catalog_object.id,
            )
            return normalized_products

        # Get variations from item_data
        variations = item_data.variations or []

        # If no variations, create one from the item itself
        if not variations:
            logger.warning(
                "Catalog object has no variations, using item as single variation",
                catalog_object_id=catalog_object.id,
            )
            # Create a synthetic variation from the item
            synthetic_variation = SquareCatalogObjectVariation(
                id=catalog_object.id,
                type="ITEM_VARIATION",
                item_variation_data={
                    "name": item_data.name or "Default",
                    "sku": item_data.ean,
                    "price_money": None,
                },
            )
            normalized = SquareTransformer._normalize_variation(
                catalog_object, synthetic_variation, measurement_units_cache
            )
            normalized_products.append(normalized)
            return normalized_products

        # Process each variation as a separate product
        for variation_data in variations:
            try:
                variation = SquareCatalogObjectVariation(**variation_data)
                normalized = SquareTransformer._normalize_variation(
                    catalog_object, variation, measurement_units_cache
                )
                normalized_products.append(normalized)
            except Exception as e:
                logger.error(
                    "Failed to normalize variation",
                    catalog_object_id=catalog_object.id,
                    variation_data=variation_data,
                    error=str(e),
                )
                # Continue processing other variations even if one fails
                continue

        return normalized_products

    @staticmethod
    def _normalize_variation(
        catalog_object: SquareCatalogObject,
        variation: SquareCatalogObjectVariation,
        measurement_units_cache: dict[str, dict] | None = None,
    ) -> NormalizedProduct:
        """
        Normalize a single Square variation to normalized format.

        Args:
            catalog_object: Parent catalog object
            variation: Variation to normalize
            measurement_units_cache: Optional dict mapping measurement_unit_id -> unit data.
                Used for calculating weight-based pricing fields (f1-f4).
                If None, products will default to per-item pricing.

        Returns:
            Normalized product object
        """
        item_data = catalog_object.item_data

        # Build product title: Item Name - Variation Name (if different)
        item_name = item_data.name if item_data else "Untitled Product"
        variation_name = variation.name
        if variation_name and variation_name != "Regular":
            product_title = f"{item_name} - {variation_name}"
        else:
            product_title = item_name

        # Extract price - CRITICAL: Convert cents to dollars
        price_value = 0.0
        currency = "USD"
        if variation.price_money:
            price_value = variation.price_money.amount / 100.0  # cents → dollars
            currency = variation.price_money.currency

        # Determine barcode - prefer variation SKU, fallback to item EAN
        barcode = variation.sku
        if not barcode and item_data:
            barcode = item_data.ean

        # SKU from variation
        sku = variation.sku

        # Extract measurement_unit_id from variation data
        measurement_unit_id = None
        if variation.item_variation_data:
            measurement_unit_id = variation.item_variation_data.get("measurement_unit_id")

        # Calculate dynamic fields (f1-f4) based on sell type
        dynamic_fields = {}
        if variation.item_variation_data:
            # Convert catalog_object to dict if needed (for custom attributes access)
            # Note: SquareCatalogObject is a Pydantic model that may not include custom_attribute_values
            # We pass it as dict to allow access to custom attributes if they exist in raw data
            catalog_object_dict = None
            if catalog_object:
                if isinstance(catalog_object, dict):
                    # Already a dict (from raw webhook data)
                    catalog_object_dict = catalog_object
                else:
                    # It's a SquareCatalogObject model - try to get raw dict
                    # Pydantic models don't include extra fields by default, so custom attributes
                    # might not be accessible. We'll rely on variation_data for unit cost.
                    # But we still pass a dict structure for consistency
                    try:
                        # Try to get as dict (Pydantic v1 uses .dict(), v2 uses .model_dump())
                        if hasattr(catalog_object, "model_dump"):
                            catalog_object_dict = catalog_object.model_dump()
                        elif hasattr(catalog_object, "dict"):
                            catalog_object_dict = catalog_object.dict()
                        else:
                            # Fallback: create minimal dict
                            catalog_object_dict = {
                                "id": catalog_object.id if hasattr(catalog_object, "id") else None,
                                "type": catalog_object.type
                                if hasattr(catalog_object, "type")
                                else None,
                            }
                    except Exception as e:
                        logger.debug(
                            "Could not convert catalog_object to dict",
                            error=str(e),
                            catalog_object_id=getattr(catalog_object, "id", None),
                        )
                        catalog_object_dict = None

            dynamic_fields = SquareTransformer.calculate_dynamic_fields(
                variation.item_variation_data,
                measurement_units_cache or {},
                catalog_object=catalog_object_dict,  # Pass as dict for custom attributes
            )

        # Create normalized product with dynamic fields
        return NormalizedProduct(
            source_id=str(catalog_object.id),
            source_variant_id=str(variation.id) if variation.id else None,
            title=product_title,
            barcode=barcode,
            sku=sku,
            price=price_value,
            currency=currency,
            image_url=None,  # Square requires additional API call to get image URL
            # Add dynamic fields to extra_data
            sell_type=dynamic_fields.get("sell_type", "item"),
            f1=dynamic_fields.get("f1"),
            f2=dynamic_fields.get("f2"),
            f3=dynamic_fields.get("f3"),
            f4=dynamic_fields.get("f4"),
            measurement_unit_id=measurement_unit_id,  # Store for reference
        )

    @staticmethod
    def validate_normalized_product(
        product: NormalizedProduct,
    ) -> tuple[bool, list[str]]:
        """
        Validate normalized product data before syncing to Hipoink.

        Args:
            product: Normalized product object

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Required fields
        if not product.title:
            errors.append("Title is required")

        if not product.barcode and not product.sku:
            errors.append("Barcode or SKU is required")

        # Price validation
        if product.price is None:
            errors.append("Price is required")
        elif product.price < 0:
            errors.append("Price must be non-negative")

        # Barcode format validation (basic check)
        if product.barcode and len(product.barcode) > 255:
            errors.append("Barcode exceeds maximum length (255 characters)")

        return len(errors) == 0, errors

    @staticmethod
    def extract_location_id_from_webhook(
        headers: dict[str, str], payload: dict[str, Any]
    ) -> str | None:
        """
        Extract Square Location ID from webhook.

        Args:
            headers: Request headers
            payload: Webhook payload

        Returns:
            Location ID if found, None otherwise
        """
        # Try to get merchant_id from payload (Square uses this as store identifier)
        merchant_id = payload.get("merchant_id")
        if merchant_id:
            return merchant_id

        # Try to get location_id from data.object
        data = payload.get("data", {})
        obj = data.get("object", {})
        location_id = obj.get("location_id")
        if location_id:
            return location_id

        # Try present_at_location_ids from catalog object
        catalog_object = obj.get("catalog_object", {})
        location_ids = catalog_object.get("present_at_location_ids", [])
        if location_ids:
            return location_ids[0]  # Return first location

        return None
