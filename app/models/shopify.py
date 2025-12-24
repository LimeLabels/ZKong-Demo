"""
Pydantic models for Shopify webhook payloads.
Handles products/create, products/update, products/delete, and inventory_levels/update events.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ShopifyImage(BaseModel):
    """Shopify product image model."""
    id: int
    product_id: int
    position: int
    created_at: datetime
    updated_at: datetime
    alt: Optional[str] = None
    width: int
    height: int
    src: str
    variant_ids: List[int] = Field(default_factory=list)


class ShopifyVariant(BaseModel):
    """Shopify product variant model."""
    id: int
    product_id: int
    title: str
    price: str
    sku: Optional[str] = None
    position: int
    compare_at_price: Optional[str] = None
    barcode: Optional[str] = None
    grams: int = 0
    weight: float = 0.0
    weight_unit: str = "kg"
    inventory_quantity: int = 0
    requires_shipping: bool = True
    taxable: bool = True
    created_at: datetime
    updated_at: datetime


class ShopifyProduct(BaseModel):
    """Shopify product model."""
    id: int
    title: str
    body_html: Optional[str] = None
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    created_at: datetime
    handle: str
    updated_at: datetime
    published_at: Optional[datetime] = None
    template_suffix: Optional[str] = None
    status: str
    published_scope: str
    tags: str = ""
    admin_graphql_api_id: str
    variants: List[ShopifyVariant] = Field(default_factory=list)
    images: List[ShopifyImage] = Field(default_factory=list)
    options: List[dict] = Field(default_factory=list)


class ShopifyWebhookBase(BaseModel):
    """Base model for Shopify webhooks."""
    id: int
    email: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    number: Optional[int] = None
    note: Optional[str] = None
    token: Optional[str] = None
    gateway: Optional[str] = None
    test: Optional[bool] = None
    total_price: Optional[str] = None
    subtotal_price: Optional[str] = None
    total_weight: Optional[int] = None
    total_tax: Optional[str] = None
    taxes_included: Optional[bool] = None
    currency: Optional[str] = None
    financial_status: Optional[str] = None
    confirmed: Optional[bool] = None
    total_discounts: Optional[str] = None
    buyer_accepts_marketing: Optional[bool] = None
    name: Optional[str] = None
    referring_site: Optional[str] = None
    landing_site: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    total_line_items_price: Optional[str] = None
    total_duties: Optional[str] = None
    billing_address: Optional[dict] = None
    shipping_address: Optional[dict] = None
    customer: Optional[dict] = None
    discount_codes: Optional[List[dict]] = None
    note_attributes: Optional[List[dict]] = None
    payment_gateway_names: Optional[List[str]] = None
    processing_method: Optional[str] = None
    checkout_id: Optional[int] = None
    source_name: Optional[str] = None
    fulfillment_status: Optional[str] = None
    order_adjustments: Optional[List[dict]] = None
    line_items: Optional[List[dict]] = None
    shipping_lines: Optional[List[dict]] = None
    tax_lines: Optional[List[dict]] = None
    discount_applications: Optional[List[dict]] = None
    fulfillment: Optional[List[dict]] = None
    refunds: Optional[List[dict]] = None


class ProductCreateWebhook(BaseModel):
    """Webhook payload for products/create event."""
    id: int
    title: str
    body_html: Optional[str] = None
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    created_at: datetime
    handle: str
    updated_at: datetime
    published_at: Optional[datetime] = None
    template_suffix: Optional[str] = None
    status: str
    published_scope: str
    tags: str = ""
    admin_graphql_api_id: str
    variants: List[ShopifyVariant] = Field(default_factory=list)
    images: List[ShopifyImage] = Field(default_factory=list)
    options: List[dict] = Field(default_factory=list)


class ProductUpdateWebhook(ProductCreateWebhook):
    """Webhook payload for products/update event (same structure as create)."""
    pass


class ProductDeleteWebhook(BaseModel):
    """Webhook payload for products/delete event."""
    id: int
    title: Optional[str] = None


class InventoryLevel(BaseModel):
    """Inventory level model for inventory_levels/update webhook."""
    inventory_item_id: int
    location_id: int
    available: Optional[int] = None
    updated_at: datetime
    admin_graphql_api_id: str


class InventoryLevelsUpdateWebhook(BaseModel):
    """Webhook payload for inventory_levels/update event."""
    inventory_item_id: int
    location_id: int
    available: Optional[int] = None
    updated_at: datetime
    admin_graphql_api_id: str

