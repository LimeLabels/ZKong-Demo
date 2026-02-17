"""
Pydantic models for Shopify webhook payloads.
Handles products/create, products/update, products/delete, and inventory_levels/update events.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ShopifyImage(BaseModel):
    """Shopify product image model."""

    id: int
    product_id: int
    position: int
    created_at: datetime
    updated_at: datetime
    alt: str | None = None
    width: int
    height: int
    src: str
    variant_ids: list[int] = Field(default_factory=list)


class ShopifyVariant(BaseModel):
    """Shopify product variant model."""

    id: int
    product_id: int
    title: str
    price: str
    sku: str | None = None
    position: int
    compare_at_price: str | None = None
    barcode: str | None = None
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
    body_html: str | None = None
    vendor: str | None = None
    product_type: str | None = None
    created_at: datetime
    handle: str
    updated_at: datetime
    published_at: datetime | None = None
    template_suffix: str | None = None
    status: str
    published_scope: str
    tags: str = ""
    admin_graphql_api_id: str
    variants: list[ShopifyVariant] = Field(default_factory=list)
    images: list[ShopifyImage] = Field(default_factory=list)
    options: list[dict] = Field(default_factory=list)


class ShopifyWebhookBase(BaseModel):
    """Base model for Shopify webhooks."""

    id: int
    email: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    number: int | None = None
    note: str | None = None
    token: str | None = None
    gateway: str | None = None
    test: bool | None = None
    total_price: str | None = None
    subtotal_price: str | None = None
    total_weight: int | None = None
    total_tax: str | None = None
    taxes_included: bool | None = None
    currency: str | None = None
    financial_status: str | None = None
    confirmed: bool | None = None
    total_discounts: str | None = None
    buyer_accepts_marketing: bool | None = None
    name: str | None = None
    referring_site: str | None = None
    landing_site: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    total_line_items_price: str | None = None
    total_duties: str | None = None
    billing_address: dict | None = None
    shipping_address: dict | None = None
    customer: dict | None = None
    discount_codes: list[dict] | None = None
    note_attributes: list[dict] | None = None
    payment_gateway_names: list[str] | None = None
    processing_method: str | None = None
    checkout_id: int | None = None
    source_name: str | None = None
    fulfillment_status: str | None = None
    order_adjustments: list[dict] | None = None
    line_items: list[dict] | None = None
    shipping_lines: list[dict] | None = None
    tax_lines: list[dict] | None = None
    discount_applications: list[dict] | None = None
    fulfillment: list[dict] | None = None
    refunds: list[dict] | None = None


class ProductCreateWebhook(BaseModel):
    """Webhook payload for products/create event."""

    id: int
    title: str
    body_html: str | None = None
    vendor: str | None = None
    product_type: str | None = None
    created_at: datetime
    handle: str
    updated_at: datetime
    published_at: datetime | None = None
    template_suffix: str | None = None
    status: str
    published_scope: str
    tags: str = ""
    admin_graphql_api_id: str
    variants: list[ShopifyVariant] = Field(default_factory=list)
    images: list[ShopifyImage] = Field(default_factory=list)
    options: list[dict] = Field(default_factory=list)


class ProductUpdateWebhook(ProductCreateWebhook):
    """Webhook payload for products/update event (same structure as create)."""

    pass


class ProductDeleteWebhook(BaseModel):
    """Webhook payload for products/delete event."""

    id: int
    title: str | None = None


class InventoryLevel(BaseModel):
    """Inventory level model for inventory_levels/update webhook."""

    inventory_item_id: int
    location_id: int
    available: int | None = None
    updated_at: datetime
    admin_graphql_api_id: str


class InventoryLevelsUpdateWebhook(BaseModel):
    """Webhook payload for inventory_levels/update event."""

    inventory_item_id: int
    location_id: int
    available: int | None = None
    updated_at: datetime
    admin_graphql_api_id: str
