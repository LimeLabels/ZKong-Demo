"""
Square data transformation service.
Transforms Square catalog data into normalized format for Hipoink ESL API.
Each Square variation becomes a separate Hipoink product.
"""

from typing import List, Dict, Any, Optional, Tuple
from app.integrations.square.models import (
    SquareCatalogObject,
    SquareCatalogObjectVariation,
    SquareItemData,
)
from app.integrations.base import NormalizedProduct
import structlog

logger = structlog.get_logger()


class SquareTransformError(Exception):
    """Raised when Square data transformation fails."""

    pass


class SquareTransformer:
    """Service for transforming Square webhook data to normalized format."""

    @staticmethod
    def extract_variations_from_catalog_object(
        catalog_object: SquareCatalogObject,
    ) -> List[NormalizedProduct]:
        """
        Extract and normalize variations from Square catalog object.
        Each variation becomes a separate normalized product.

        Args:
            catalog_object: Square catalog object

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
                catalog_object, synthetic_variation
            )
            normalized_products.append(normalized)
            return normalized_products

        # Process each variation as a separate product
        for variation_data in variations:
            try:
                variation = SquareCatalogObjectVariation(**variation_data)
                normalized = SquareTransformer._normalize_variation(
                    catalog_object, variation
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
    ) -> NormalizedProduct:
        """
        Normalize a single Square variation to normalized format.

        Args:
            catalog_object: Parent catalog object
            variation: Variation to normalize

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

        # Create normalized product
        return NormalizedProduct(
            source_id=str(catalog_object.id),
            source_variant_id=str(variation.id) if variation.id else None,
            title=product_title,
            barcode=barcode,
            sku=sku,
            price=price_value,
            currency=currency,
            image_url=None,  # Square requires additional API call to get image URL
        )

    @staticmethod
    def validate_normalized_product(
        product: NormalizedProduct,
    ) -> Tuple[bool, List[str]]:
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
        headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Optional[str]:
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