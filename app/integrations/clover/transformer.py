"""
Clover data transformation: Clover item API response -> NormalizedProduct.
One Clover item maps to one NormalizedProduct (no variants).
Price is converted from cents to dollars.
"""

from typing import List, Dict, Any, Tuple, Optional

from app.integrations.base import NormalizedProduct
import structlog

logger = structlog.get_logger()


class CloverTransformer:
    """Transform Clover inventory item data to normalized product format."""

    INVENTORY_OBJECT_PREFIX = "I:"

    @staticmethod
    def transform_item(raw_item: Dict[str, Any]) -> NormalizedProduct:
        """
        Convert a single Clover item to NormalizedProduct.

        Args:
            raw_item: Raw item dict from Clover API (id, name, price in cents, sku/code).

        Returns:
            Single NormalizedProduct.
        """
        item_id = raw_item.get("id") or ""
        name = raw_item.get("name") or "Untitled Product"
        price_cents = raw_item.get("price")
        if price_cents is None:
            price_cents = 0
        price_dollars = float(price_cents) / 100.0
        sku = raw_item.get("sku")
        code = raw_item.get("code")  # Clover sometimes uses code for barcode
        barcode = sku or code
        if not barcode and raw_item.get("alternateName"):
            barcode = raw_item.get("alternateName")

        return NormalizedProduct(
            source_id=item_id,
            source_variant_id=None,
            title=name,
            barcode=barcode,
            sku=sku,
            price=price_dollars,
            currency="USD",
            image_url=None,
        )

    @staticmethod
    def validate_normalized_product(
        product: NormalizedProduct,
    ) -> Tuple[bool, List[str]]:
        """
        Validate normalized product before DB write.

        Returns:
            (is_valid, list of error messages)
        """
        errors: List[str] = []
        if not product.title:
            errors.append("Title is required")
        if not product.barcode and not product.sku:
            errors.append("Barcode or SKU is required")
        if product.price is None:
            errors.append("Price is required")
        elif product.price < 0:
            errors.append("Price must be non-negative")
        if product.barcode and len(product.barcode) > 255:
            errors.append("Barcode exceeds maximum length (255 characters)")
        return (len(errors) == 0, errors)

    @staticmethod
    def parse_inventory_object_id(object_id: Optional[str]) -> Optional[str]:
        """
        Extract item ID from webhook objectId. Inventory prefix is "I:".

        Args:
            object_id: e.g. "I:ABC123" or "O:ORDER456"

        Returns:
            Item ID without prefix if inventory type, else None.
            Returns None for malformed: "I:", "", None.
        """
        if not object_id or not isinstance(object_id, str):
            return None
        s = object_id.strip()
        if not s.startswith(CloverTransformer.INVENTORY_OBJECT_PREFIX):
            return None
        item_id = s[len(CloverTransformer.INVENTORY_OBJECT_PREFIX) :].strip()
        if not item_id:
            return None
        return item_id

    @staticmethod
    def is_inventory_object(object_id: Optional[str]) -> bool:
        """Return True if objectId is an inventory item (I:...)."""
        return CloverTransformer.parse_inventory_object_id(object_id) is not None
