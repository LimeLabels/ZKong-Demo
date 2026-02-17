"""
NCR data transformation service.
Transforms normalized product data into NCR PRO Catalog API format.
"""

from typing import Any

import structlog

from app.integrations.base import NormalizedProduct
from app.integrations.ncr.models import (
    ItemIdData,
    ItemWriteData,
    MultiLanguageTextData,
    NodeIdData,
)

logger = structlog.get_logger()


class NCRTransformer:
    """Service for transforming normalized data to NCR format."""

    @staticmethod
    def normalize_to_ncr_item(
        normalized_product: NormalizedProduct,
        department_id: str = "DEFAULT",
        category_id: str = "DEFAULT",
        default_status: str = "ACTIVE",
    ) -> ItemWriteData:
        """
        Transform normalized product to NCR ItemWriteData.

        Args:
            normalized_product: Normalized product object
            department_id: Department identifier (required by NCR)
            category_id: Category node identifier (required by NCR)
            default_status: Default status for the item

        Returns:
            ItemWriteData object
        """
        # Use barcode as item_code if available, otherwise use SKU or source_id
        item_code = (
            normalized_product.barcode or normalized_product.sku or normalized_product.source_id
        )

        if not item_code:
            raise ValueError("Product must have barcode, sku, or source_id to create NCR item")

        # Ensure item_code meets NCR requirements (alphanumeric, max 100 chars)
        item_code = str(item_code)[:100]
        if not item_code.replace("-", "").replace("_", "").isalnum():
            # Clean item_code to be alphanumeric with dashes/underscores
            item_code = "".join(c for c in item_code if c.isalnum() or c in "-_")

        item_data = ItemWriteData(
            itemId=ItemIdData(itemCode=item_code),
            departmentId=department_id,
            merchandiseCategory=NodeIdData(nodeId=category_id),
            nonMerchandise=False,
            shortDescription=MultiLanguageTextData.from_single_text(
                normalized_product.title or "Product"
            ),
            status=default_status,
            sku=normalized_product.sku,
        )

        # Add barcode to package identifiers if different from item_code
        if normalized_product.barcode and normalized_product.barcode != item_code:
            item_data.packageIdentifiers = [{"type": "UPC", "value": normalized_product.barcode}]

        return item_data

    @staticmethod
    def extract_store_id_from_config(config: dict[str, Any]) -> str | None:
        """
        Extract NCR store/enterprise unit identifier from store mapping config.

        Args:
            config: Store mapping metadata/config

        Returns:
            Enterprise unit ID if found, None otherwise
        """
        if not config:
            return None

        # Check common field names
        return (
            config.get("enterprise_unit_id")
            or config.get("enterpriseUnitId")
            or config.get("ncr_enterprise_unit")
            or config.get("store_id")
        )
