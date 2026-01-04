"""
Pydantic models for Hipoink API requests and responses.
Based on Hipoink ESL API documentation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class HipoinkProductItem(BaseModel):
    """Product item for Hipoink API."""
    
    product_code: str = Field(..., alias="pc", description="Product Code (barcode) - required")
    product_name: str = Field(..., alias="pn", description="Product Name - required")
    product_price: str = Field(..., alias="pp", description="Product Price - required (as string)")
    product_inner_code: Optional[str] = Field(None, alias="pi", description="Product Inner Code")
    product_spec: Optional[str] = Field(None, alias="ps", description="Product Spec")
    product_grade: Optional[str] = Field(None, alias="pg", description="Product Grade")
    product_unit: Optional[str] = Field(None, alias="pu", description="Product Unit")
    vip_price: Optional[str] = Field(None, alias="vp", description="Product VIP Price")
    origin_price: Optional[str] = Field(None, alias="pop", description="Product Origin Price")
    product_origin: Optional[str] = Field(None, alias="po", description="Product Origin")
    product_manufacturer: Optional[str] = Field(None, alias="pm", description="Product Manufacturer")
    promotion: Optional[int] = Field(None, description="Promotion")
    product_image_url: Optional[str] = Field(None, alias="pim", description="Product Image URL")
    product_qrcode_url: Optional[str] = Field(None, alias="pqr", description="Product QrCode URL")
    
    # Optional fields f1-f16
    f1: Optional[str] = Field(None, description="Field 1")
    f2: Optional[str] = Field(None, description="Field 2")
    f3: Optional[str] = Field(None, description="Field 3")
    f4: Optional[str] = Field(None, description="Field 4")
    f5: Optional[str] = Field(None, description="Field 5")
    f6: Optional[str] = Field(None, description="Field 6")
    f7: Optional[str] = Field(None, description="Field 7")
    f8: Optional[str] = Field(None, description="Field 8")
    f9: Optional[str] = Field(None, description="Field 9")
    f10: Optional[str] = Field(None, description="Field 10")
    f11: Optional[str] = Field(None, description="Field 11")
    f12: Optional[str] = Field(None, description="Field 12")
    f13: Optional[str] = Field(None, description="Field 13")
    f14: Optional[str] = Field(None, description="Field 14")
    f15: Optional[str] = Field(None, description="Field 15")
    f16: Optional[str] = Field(None, description="Field 16")
    
    extend: Optional[Dict[str, Any]] = Field(None, description="Extend JSON")
    
    class Config:
        populate_by_name = True


class HipoinkProductCreateRequest(BaseModel):
    """Request for creating a single product."""
    
    store_code: str = Field(..., description="Store Code - required")
    pc: str = Field(..., description="Product Code - required")
    pn: str = Field(..., description="Product Name - required")
    pp: str = Field(..., description="Product Price - required")
    pi: Optional[str] = None
    ps: Optional[str] = None
    pg: Optional[str] = None
    pu: Optional[str] = None
    vp: Optional[str] = None
    pop: Optional[str] = None
    po: Optional[str] = None
    pm: Optional[str] = None
    promotion: Optional[int] = None
    pim: Optional[str] = None
    pqr: Optional[str] = None
    f1: Optional[str] = None
    f2: Optional[str] = None
    f3: Optional[str] = None
    f4: Optional[str] = None
    f5: Optional[str] = None
    f6: Optional[str] = None
    f7: Optional[str] = None
    f8: Optional[str] = None
    f9: Optional[str] = None
    f10: Optional[str] = None
    f11: Optional[str] = None
    f12: Optional[str] = None
    f13: Optional[str] = None
    f14: Optional[str] = None
    f15: Optional[str] = None
    f16: Optional[str] = None
    extend: Optional[Dict[str, Any]] = None
    is_base64: str = Field(default="0", description="Default is '0'")
    sign: str = Field(..., description="Sign - required")


class HipoinkProductCreateMultipleRequest(BaseModel):
    """Request for creating multiple products."""
    
    store_code: str = Field(..., description="Store Code - required")
    fs: List[Dict[str, Any]] = Field(..., description="Array of products - required")
    is_base64: str = Field(default="0", description="Default is '0'")
    sign: str = Field(..., description="Sign - required")


class HipoinkProductResponse(BaseModel):
    """Response from Hipoink product API."""
    
    error_code: int = Field(..., description="0=OK, 1=ERROR")
    error_msg: Optional[str] = Field(None, description="Error Message")

