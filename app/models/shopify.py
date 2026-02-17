"""
Pydantic models for Shopify webhook payloads (backward compatibility).
This module re-exports from the new integrations structure.
"""

# Re-export from new location for backward compatibility
from app.integrations.shopify.models import (
    InventoryLevel,
    InventoryLevelsUpdateWebhook,
    ProductCreateWebhook,
    ProductDeleteWebhook,
    ProductUpdateWebhook,
    ShopifyImage,
    ShopifyProduct,
    ShopifyVariant,
    ShopifyWebhookBase,
)

__all__ = [
    "ShopifyImage",
    "ShopifyVariant",
    "ShopifyProduct",
    "ShopifyWebhookBase",
    "ProductCreateWebhook",
    "ProductUpdateWebhook",
    "ProductDeleteWebhook",
    "InventoryLevel",
    "InventoryLevelsUpdateWebhook",
]
