"""
Pydantic models for Square webhook payloads.
Handles catalog.version.updated and inventory.count.updated events.
"""

from typing import Any

from pydantic import BaseModel


class SquareMoney(BaseModel):
    """Square Money object - amount is in CENTS (smallest currency unit)."""

    amount: int  # Amount in cents (e.g., 10000 = $100.00)
    currency: str = "USD"


class MeasurementUnit(BaseModel):
    """Square measurement unit (weight, volume, etc.)"""

    weight_unit: str | None = None  # IMPERIAL_WEIGHT_OUNCE, IMPERIAL_POUND, etc.
    custom_unit: dict | None = None


class MeasurementUnitData(BaseModel):
    """Container for measurement unit info"""

    measurement_unit: MeasurementUnit | None = None
    precision: int | None = None


class CatalogMeasurementUnit(BaseModel):
    """Full measurement unit catalog object"""

    type: str  # "MEASUREMENT_UNIT"
    id: str
    measurement_unit_data: MeasurementUnitData | None = None


class SquareItemData(BaseModel):
    """Square item data within a catalog object."""

    name: str | None = None
    description: str | None = None
    variations: list[dict[str, Any]] | None = None
    product_type: str | None = None
    ean: str | None = None  # Barcode (EAN-13 format)
    image_ids: list[str] | None = None


class SquareCatalogObjectVariation(BaseModel):
    """Square catalog object variation (like Shopify variant)."""

    id: str | None = None
    type: str | None = None
    item_variation_data: dict[str, Any] | None = None

    @property
    def sku(self) -> str | None:
        """Extract SKU from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("sku")

    @property
    def name(self) -> str | None:
        """Extract name from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("name")

    @property
    def price_money(self) -> SquareMoney | None:
        """Extract price_money from item_variation_data."""
        if not self.item_variation_data:
            return None
        price_data = self.item_variation_data.get("price_money")
        return SquareMoney(**price_data) if price_data else None

    @property
    def measurement_unit_id(self) -> str | None:
        """Extract measurement_unit_id from item_variation_data."""
        if not self.item_variation_data:
            return None
        return self.item_variation_data.get("measurement_unit_id")


class SquareCatalogObject(BaseModel):
    """Square catalog object (product/item)."""

    id: str | None = None
    type: str | None = None  # "ITEM", "ITEM_VARIATION", etc.
    catalog_v1_id: str | None = None
    present_at_all_locations: bool | None = None
    present_at_location_ids: list[str] | None = None
    item_data: SquareItemData | None = None
    is_deleted: bool | None = None


class CatalogVersionUpdatedWebhook(BaseModel):
    """Webhook payload for catalog.version.updated event."""

    merchant_id: str | None = None
    type: str | None = None
    event_id: str | None = None
    created_at: str | None = None
    data: dict[str, Any] | None = None  # Contains catalog_object


class InventoryCountUpdatedWebhook(BaseModel):
    """Webhook payload for inventory.count.updated event."""

    merchant_id: str | None = None
    type: str | None = None
    event_id: str | None = None
    created_at: str | None = None
    data: dict[str, Any] | None = None
