"""
Pydantic models for Square webhook payloads.
Handles catalog.version.updated and inventory.count.updated events.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class SquareMoney(BaseModel):
    """Square Money object - amount is in CENTS (smallest currency unit)."""

    amount: int  # Amount in cents (e.g., 10000 = $100.00)
    currency: str = "USD"


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


class SquareItemData(BaseModel):
    """Square item data within a catalog object."""

    name: Optional[str] = None
    description: Optional[str] = None
    variations: Optional[List[Dict[str, Any]]] = None
    product_type: Optional[str] = None
    ean: Optional[str] = None  # Barcode (EAN-13 format)
    image_ids: Optional[List[str]] = None


class SquareCatalogObjectVariation(BaseModel):
    """Square catalog object variation (like Shopify variant)."""

    id: Optional[str] = None
    type: Optional[str] = None
    item_variation_data: Optional[Dict[str, Any]] = None

    @property
    def sku(self) -> Optional[str]:
        """Extract SKU from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("sku")

    @property
    def name(self) -> Optional[str]:
        """Extract name from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("name")

    @property
    def price_money(self) -> Optional[SquareMoney]:
        """Extract price_money from item_variation_data."""
        if not self.item_variation_data:
            return None
        price_data = self.item_variation_data.get("price_money")
        return SquareMoney(**price_data) if price_data else None

    @property
    def measurement_unit_id(self) -> Optional[str]:
        """Extract measurement_unit_id from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("measurement_unit_id")


class SquareCatalogObject(BaseModel):
    """Square catalog object (product/item)."""

    id: Optional[str] = None
    type: Optional[str] = None  # "ITEM", "ITEM_VARIATION", etc.
    catalog_v1_id: Optional[str] = None
    present_at_all_locations: Optional[bool] = None
    present_at_location_ids: Optional[List[str]] = None
    item_data: Optional[SquareItemData] = None
    is_deleted: Optional[bool] = None


class CatalogVersionUpdatedWebhook(BaseModel):
    """Webhook payload for catalog.version.updated event."""

    merchant_id: Optional[str] = None
    type: Optional[str] = None
    event_id: Optional[str] = None
    created_at: Optional[str] = None
    data: Optional[Dict[str, Any]] = None  # Contains catalog_object


class InventoryCountUpdatedWebhook(BaseModel):
    """Webhook payload for inventory.count.updated event."""

    merchant_id: Optional[str] = None
    type: Optional[str] = None
    event_id: Optional[str] = None
    created_at: Optional[str] = None
    data: Optional[Dict[str, Any]] = None