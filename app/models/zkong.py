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
    source_system: Optional[str] = None  # Source system (e.g., "shopify", "amazon") for origin field


class ZKongBulkImportRequest(BaseModel):
    """Bulk product import request (section 3.1)."""
    products: List[ZKongProductImportItem] = Field(..., description="List of products to import")


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

