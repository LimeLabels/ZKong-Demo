"""
Pydantic models for Hipoink API requests and responses.
Based on Hipoink ESL API documentation.
"""

from typing import Any

from pydantic import BaseModel, Field


class HipoinkProductItem(BaseModel):
    """Product item for Hipoink API."""

    product_code: str = Field(..., alias="pc", description="Product Code (barcode) - required")
    product_name: str = Field(..., alias="pn", description="Product Name - required")
    product_price: str = Field(..., alias="pp", description="Product Price - required (as string)")
    product_inner_code: str | None = Field(None, alias="pi", description="Product Inner Code")
    product_spec: str | None = Field(None, alias="ps", description="Product Spec")
    product_grade: str | None = Field(None, alias="pg", description="Product Grade")
    product_unit: str | None = Field(None, alias="pu", description="Product Unit")
    vip_price: str | None = Field(None, alias="vp", description="Product VIP Price")
    origin_price: str | None = Field(None, alias="pop", description="Product Origin Price")
    product_origin: str | None = Field(None, alias="po", description="Product Origin")
    product_manufacturer: str | None = Field(None, alias="pm", description="Product Manufacturer")
    promotion: int | None = Field(None, description="Promotion")
    product_image_url: str | None = Field(None, alias="pim", description="Product Image URL")
    product_qrcode_url: str | None = Field(None, alias="pqr", description="Product QrCode URL")

    # Optional fields f1-f16
    f1: str | None = Field(None, description="Field 1")
    f2: str | None = Field(None, description="Field 2")
    f3: str | None = Field(None, description="Field 3")
    f4: str | None = Field(None, description="Field 4")
    f5: str | None = Field(None, description="Field 5")
    f6: str | None = Field(None, description="Field 6")
    f7: str | None = Field(None, description="Field 7")
    f8: str | None = Field(None, description="Field 8")
    f9: str | None = Field(None, description="Field 9")
    f10: str | None = Field(None, description="Field 10")
    f11: str | None = Field(None, description="Field 11")
    f12: str | None = Field(None, description="Field 12")
    f13: str | None = Field(None, description="Field 13")
    f14: str | None = Field(None, description="Field 14")
    f15: str | None = Field(None, description="Field 15")
    f16: str | None = Field(None, description="Field 16")

    extend: dict[str, Any] | None = Field(None, description="Extend JSON")

    class Config:
        populate_by_name = True


class HipoinkProductCreateRequest(BaseModel):
    """Request for creating a single product."""

    store_code: str = Field(..., description="Store Code - required")
    pc: str = Field(..., description="Product Code - required")
    pn: str = Field(..., description="Product Name - required")
    pp: str = Field(..., description="Product Price - required")
    pi: str | None = None
    ps: str | None = None
    pg: str | None = None
    pu: str | None = None
    vp: str | None = None
    pop: str | None = None
    po: str | None = None
    pm: str | None = None
    promotion: int | None = None
    pim: str | None = None
    pqr: str | None = None
    f1: str | None = None
    f2: str | None = None
    f3: str | None = None
    f4: str | None = None
    f5: str | None = None
    f6: str | None = None
    f7: str | None = None
    f8: str | None = None
    f9: str | None = None
    f10: str | None = None
    f11: str | None = None
    f12: str | None = None
    f13: str | None = None
    f14: str | None = None
    f15: str | None = None
    f16: str | None = None
    extend: dict[str, Any] | None = None
    is_base64: str = Field(default="0", description="Default is '0'")
    sign: str = Field(..., description="Sign - required")


class HipoinkProductCreateMultipleRequest(BaseModel):
    """Request for creating multiple products."""

    store_code: str = Field(..., description="Store Code - required")
    fs: list[dict[str, Any]] = Field(..., description="Array of products - required")
    is_base64: str = Field(default="0", description="Default is '0'")
    sign: str = Field(..., description="Sign - required")


class HipoinkProductResponse(BaseModel):
    """Response from Hipoink product API."""

    error_code: int = Field(..., description="0=OK, 1=ERROR")
    error_msg: str | None = Field(None, description="Error Message")
