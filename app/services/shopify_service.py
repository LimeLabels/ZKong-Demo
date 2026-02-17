"""
Shopify data transformation service (backward compatibility).
This module re-exports from the new integrations structure.
"""

from app.integrations.shopify.transformer import ShopifyTransformer, ShopifyTransformError

# Maintain backward compatibility by making it work like the old service
# The old code expected static methods, so we expose them


class ShopifyServiceCompat:
    """Compatibility wrapper for old ShopifyService interface."""

    @staticmethod
    def extract_variants_from_product(product):
        """Extract and normalize variants from Shopify product."""
        transformer = ShopifyTransformer()
        normalized = transformer.extract_variants_from_product(product)
        # Convert NormalizedProduct objects to dicts for backward compatibility
        return [n.to_dict() for n in normalized]

    @staticmethod
    def validate_normalized_product(product):
        """Validate normalized product data."""
        transformer = ShopifyTransformer()
        # Convert dict to NormalizedProduct if needed
        if isinstance(product, dict):
            from app.integrations.base import NormalizedProduct

            normalized = NormalizedProduct(**product)
        else:
            normalized = product
        return transformer.validate_normalized_product(normalized)

    @staticmethod
    def extract_store_domain_from_webhook(headers):
        """Extract Shopify store domain from webhook headers."""
        transformer = ShopifyTransformer()
        return transformer.extract_store_domain_from_webhook(headers)


# Export the compatibility class as ShopifyService
ShopifyService = ShopifyServiceCompat

__all__ = ["ShopifyService", "ShopifyTransformError"]
