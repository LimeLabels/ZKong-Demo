"""
Pydantic models for NCR PRO catalog API requests and responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LocalizedTextData(BaseModel):
    """Localized text data."""

    locale: str
    value: str


class MultiLanguageTextData(BaseModel):
    """Multi-language text data."""

    values: list[LocalizedTextData]

    @classmethod
    def from_single_text(cls, text: str, locale: str = "en-US") -> "MultiLanguageTextData":
        """Create MultiLanguageTextData from a single text string."""
        return cls(values=[LocalizedTextData(locale=locale, value=text)])

    def get_text(self, locale: str = "en-US") -> str | None:
        """Get text for a specific locale."""
        for val in self.values:
            if val.locale == locale:
                return val.value
        # Fallback to first value if locale not found
        return self.values[0].value if self.values else None


class NodeIdData(BaseModel):
    """Category node identifier."""

    nodeId: str


class ItemIdData(BaseModel):
    """Item identifier."""

    itemCode: str


class ItemPriceIdData(BaseModel):
    """Item price identifier."""

    itemCode: str
    priceCode: str
    enterpriseUnitId: str | None = None


class SourceSystemData(BaseModel):
    """Source system information."""

    sourceSystemId: str | None = None
    sourceSystemName: str | None = None


class ItemWriteData(BaseModel):
    """Data model for creating/updating an item."""

    version: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    itemId: ItemIdData
    departmentId: str
    merchandiseCategory: NodeIdData
    nonMerchandise: bool = False
    shortDescription: MultiLanguageTextData
    status: str = "ACTIVE"  # ACTIVE, INACTIVE, DISCONTINUED, SEASONAL, TO_DISCONTINUE, UNAUTHORIZED

    # Optional fields
    longDescription: MultiLanguageTextData | None = None
    sku: str | None = None
    posNumber: str | None = None
    referenceId: str | None = None
    familyCode: str | None = None
    manufacturerCode: str | None = None
    sourceSystem: SourceSystemData | None = None
    packageIdentifiers: list[dict[str, Any]] | None = None

    class Config:
        populate_by_name = True


class SaveMultipleItemsRequest(BaseModel):
    """Request model for batch item creation/update."""

    items: list[ItemWriteData]


class ItemPriceWriteData(BaseModel):
    """Data model for creating/updating an item price."""

    version: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    priceId: ItemPriceIdData
    price: float
    currency: str = "USD"
    effectiveDate: str = Field(default_factory=lambda: datetime.now().isoformat())
    promotionPriceType: str = "NON_CARD_PRICE"  # NON_CARD_PRICE or CARD_PRICE
    status: str = "ACTIVE"  # ACTIVE, INACTIVE, DISCONTINUED, etc.

    # Optional fields
    endDate: str | None = None
    basePrice: bool | None = None
    itemPriceType: str | None = None
    sourceSystem: SourceSystemData | None = None


class SaveMultipleItemPricesRequest(BaseModel):
    """Request model for batch price creation/update."""

    itemPrices: list[ItemPriceWriteData]
