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
