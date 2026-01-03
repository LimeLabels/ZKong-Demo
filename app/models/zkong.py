"""
Pydantic models for ZKong API requests and responses.
Based on ZKong API Documentation 3.2.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ZKongProductImportItem(BaseModel):
    """Single product item for ZKong bulk import (section 3.1)."""

    barcode: str = Field(..., description="Product barcode (required)")
    merchant_id: str = Field(..., description="Merchant ID")
    store_id: str = Field(..., description="Store ID")
    product_name: str = Field(..., description="Product name")
    price: float = Field(..., description="Product price")
    currency: str = Field(default="USD", description="Currency code")
    image_url: Optional[str] = Field(None, description="Product image URL")
    # Additional fields based on API 3.1 expansion (up to 25 fields)
    external_id: Optional[str] = None
    sku: Optional[str] = Field(None, description="Product SKU")
    category: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    unit: Optional[str] = None
    specification: Optional[str] = None
    source_system: Optional[str] = (
        None  # Source system (e.g., "shopify", "amazon") for origin field
    )


class ZKongBulkImportRequest(BaseModel):
    """Bulk product import request (section 3.1)."""

    products: List[ZKongProductImportItem] = Field(
        ..., description="List of products to import"
    )


class ZKongProductImportResponse(BaseModel):
    """Response from bulk product import."""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


class ZKongAuthResponse(BaseModel):
    """Response from ZKong login (section 2.2)."""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None  # Contains token, expires, etc.


class ZKongPublicKeyResponse(BaseModel):
    """Response from RSA public key endpoint (section 2.1)."""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None  # Contains public_key


class ZKongImageUploadResponse(BaseModel):
    """Response from product image upload (section 3.3)."""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None  # Contains image_url, image_id, etc.


class ZKongProductDeleteResponse(BaseModel):
    """Response from bulk product delete (section 3.2)."""

    success: Optional[bool] = None
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None
    translate: Optional[bool] = None
    originalMessage: Optional[str] = None


# Strategy API Models (Section 8.1)


class ZKongFieldValues(BaseModel):
    """Field values for strategy item actions.
    Contains pricing and promotional information.
    """

    price: Optional[str] = Field(None, description="Activity Price")
    member_price: Optional[str] = Field(None, description="Activity Member Price")
    unit: Optional[str] = Field(None, description="Sales Unit")
    class_level: Optional[str] = Field(
        None, alias="classLevel", description="Product level"
    )
    product_area: Optional[str] = Field(None, alias="productArea", description="Origin")
    original_price: Optional[str] = Field(
        None, alias="originalPrice", description="Original Price"
    )
    promotion_text: Optional[str] = Field(
        None, alias="promotionText", description="Promotional copy"
    )
    cust_feature1: Optional[str] = Field(
        None, alias="custFeature1", description="Extension 1"
    )
    cust_feature2: Optional[str] = Field(
        None, alias="custFeature2", description="Extension 2"
    )
    cust_feature3: Optional[str] = Field(
        None, alias="custFeature3", description="Extension 3"
    )
    cust_feature4: Optional[str] = Field(
        None, alias="custFeature4", description="Extension 4"
    )
    cust_feature5: Optional[str] = Field(
        None, alias="custFeature5", description="Extension 5"
    )
    cust_feature6: Optional[str] = Field(
        None, alias="custFeature6", description="Extension 6"
    )
    cust_feature7: Optional[str] = Field(
        None, alias="custFeature7", description="Extension 7"
    )
    cust_feature8: Optional[str] = Field(
        None, alias="custFeature8", description="Extension 8"
    )
    cust_feature9: Optional[str] = Field(
        None, alias="custFeature9", description="Extension 9"
    )
    cust_feature10: Optional[str] = Field(
        None, alias="custFeature10", description="Expansion 10"
    )
    cust_feature11: Optional[str] = Field(
        None, alias="custFeature11", description="Expansion 11"
    )
    cust_feature12: Optional[str] = Field(
        None, alias="custFeature12", description="Expansion 12"
    )
    cust_feature13: Optional[str] = Field(
        None, alias="custFeature13", description="Expansion 13"
    )
    cust_feature14: Optional[str] = Field(
        None, alias="custFeature14", description="Expansion 14"
    )
    cust_feature15: Optional[str] = Field(
        None, alias="custFeature15", description="Expansion 15"
    )

    class Config:
        populate_by_name = True


class ZKongItemAction(BaseModel):
    """Item action for strategy (product pricing configuration)."""

    item_id: int = Field(..., alias="itemId", description="Product ID (ZKong itemId as integer)")
    field_values: ZKongFieldValues = Field(
        ..., alias="fieldValues", description="Product attributes"
    )
    period_times: Optional[List[str]] = Field(
        None, alias="periodTimes", description="Time windows (HH:mm:ss format)"
    )

    class Config:
        populate_by_name = True


class ZKongStrategyRequest(BaseModel):
    """Request model for creating a ZKong strategy (section 8.1)."""

    store_id: int = Field(..., alias="storeId", description="Store ID")
    name: str = Field(..., description="Policy Name")
    start_date: int = Field(
        ..., alias="startDate", description="Validity start timestamp (Unix ms)"
    )
    end_date: int = Field(
        ..., alias="endDate", description="Validity end timestamp (Unix ms)"
    )
    template_attr_category: str = Field(
        ...,
        alias="templateAttrCategory",
        description="Activity Template Classification",
    )
    template_attr: str = Field(
        ..., alias="templateAttr", description="Activity Template Properties"
    )
    trigger_type: int = Field(
        ...,
        alias="triggerType",
        description="Trigger method: 1=Fixed period, 2=Always triggered",
    )
    period_type: int = Field(
        ...,
        alias="periodType",
        description="Trigger cycle type: 0=Daily, 1=Weekly, 2=Monthly",
    )
    period_value: List[int] = Field(
        ..., alias="periodValue", description="Trigger period value (array of integers)"
    )
    period_times: List[str] = Field(
        ..., alias="periodTimes", description="Trigger period times (HH:mm:ss format)"
    )
    select_field_name_num: List[int] = Field(
        ...,
        alias="selectFieldNameNum",
        description="Optional field array (0-19), max 5 selections",
    )
    item_actions: List[ZKongItemAction] = Field(
        ..., alias="itemActions", description="Execution object list"
    )

    class Config:
        populate_by_name = True


class ZKongStrategyResponse(BaseModel):
    """Response from strategy creation."""

    code: int
    message: str
    data: Optional[Dict[str, Any] | int | str] = None  # Can be dict, strategy ID (int), or string
    success: Optional[bool] = None
    
    @classmethod
    def parse_response(cls, response_data: dict):
        """
        Parse ZKong response, handling different data formats.
        
        Args:
            response_data: Raw response dictionary from ZKong API
            
        Returns:
            ZKongStrategyResponse instance
        """
        # Handle case where data might be an integer (strategy ID) or other type
        data = response_data.get("data")
        if data is not None and not isinstance(data, dict):
            # Convert non-dict data to dict format for consistency
            response_data["data"] = {"strategy_id": data}
        
        return cls(**response_data)
