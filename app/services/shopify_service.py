"""
Shopify data transformation service.
Transforms Shopify product data into normalized format for ZKong API.
Each Shopify variant becomes a separate ZKong product.
"""
from typing import List, Dict, Any, Optional, Tuple
from app.models.shopify import ProductCreateWebhook, ProductUpdateWebhook, ShopifyVariant
import structlog

logger = structlog.get_logger()


class ShopifyTransformError(Exception):
    """Raised when Shopify data transformation fails."""
    pass


class ShopifyService:
    """Service for transforming Shopify webhook data to normalized format."""
    
    @staticmethod
    def extract_variants_from_product(
        product: ProductCreateWebhook | ProductUpdateWebhook
    ) -> List[Dict[str, Any]]:
        """
        Extract and normalize variants from Shopify product.
        Each variant becomes a separate normalized product.
        
        Args:
            product: Shopify product webhook payload
            
        Returns:
            List of normalized product dictionaries
        """
        normalized_products = []
        
        # If product has no variants, create one from the product itself
        if not product.variants:
            logger.warning(
                "Product has no variants, using product as single variant",
                product_id=product.id
            )
            # Create a synthetic variant from the product
            variant_data = {
                "id": product.id,
                "title": product.title,
                "price": "0.00",
                "sku": None,
                "barcode": None,
            }
            normalized_products.append(
                ShopifyService._normalize_variant(product, variant_data)
            )
            return normalized_products
        
        # Process each variant as a separate product
        for variant in product.variants:
            try:
                normalized = ShopifyService._normalize_variant(product, variant)
                normalized_products.append(normalized)
            except Exception as e:
                logger.error(
                    "Failed to normalize variant",
                    product_id=product.id,
                    variant_id=variant.id,
                    error=str(e)
                )
                # Continue processing other variants even if one fails
                continue
        
        return normalized_products
    
    @staticmethod
    def _normalize_variant(
        product: ProductCreateWebhook | ProductUpdateWebhook,
        variant: ShopifyVariant | Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Normalize a single Shopify variant to ZKong-compatible format.
        
        Args:
            product: Shopify product containing the variant
            variant: Shopify variant data
            
        Returns:
            Normalized product dictionary
        """
        # Handle both Pydantic model and dict
        if isinstance(variant, dict):
            variant_id = variant.get("id")
            variant_title = variant.get("title", "")
            variant_price = variant.get("price", "0.00")
            variant_sku = variant.get("sku")
            variant_barcode = variant.get("barcode")
        else:
            variant_id = variant.id
            variant_title = variant.title
            variant_price = variant.price
            variant_sku = variant.sku
            variant_barcode = variant.barcode
        
        # Build product title: Product Title - Variant Title (if variant title differs)
        if variant_title and variant_title != "Default Title":
            product_title = f"{product.title} - {variant_title}"
        else:
            product_title = product.title
        
        # Find variant-specific image
        image_url = None
        if product.images:
            # Try to find image associated with this variant
            variant_image = next(
                (img for img in product.images if variant_id in img.variant_ids),
                None
            )
            if variant_image:
                image_url = variant_image.src
            else:
                # Fallback to first image
                image_url = product.images[0].src
        
        # Extract price (remove currency symbol if present, convert to float)
        try:
            price_value = float(str(variant_price).replace("$", "").replace(",", "").strip())
        except (ValueError, AttributeError):
            logger.warning(
                "Invalid price format, defaulting to 0.00",
                product_id=product.id,
                variant_id=variant_id,
                price=variant_price
            )
            price_value = 0.00
        
        # Determine barcode - prefer variant barcode, fallback to SKU
        barcode = variant_barcode or variant_sku
        
        # Validate required fields
        validation_errors = []
        if not barcode:
            validation_errors.append("barcode_or_sku_required")
        if not product_title:
            validation_errors.append("title_required")
        if price_value < 0:
            validation_errors.append("price_must_be_non_negative")
        
        normalized = {
            "source_id": str(product.id),
            "source_variant_id": str(variant_id),
            "title": product_title,
            "barcode": barcode,
            "sku": variant_sku,
            "price": price_value,
            "currency": "USD",  # Default to USD, can be enhanced to detect from Shopify
            "image_url": image_url,
            "validation_errors": validation_errors if validation_errors else None,
        }
        
        return normalized
    
    @staticmethod
    def validate_normalized_product(product: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate normalized product data before syncing to ZKong.
        
        Args:
            product: Normalized product dictionary
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Required fields
        if not product.get("title"):
            errors.append("Title is required")
        
        if not product.get("barcode") and not product.get("sku"):
            errors.append("Barcode or SKU is required")
        
        # Price validation
        price = product.get("price")
        if price is None:
            errors.append("Price is required")
        elif price < 0:
            errors.append("Price must be non-negative")
        
        # Barcode format validation (basic check)
        barcode = product.get("barcode")
        if barcode and len(barcode) > 255:
            errors.append("Barcode exceeds maximum length (255 characters)")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def extract_store_domain_from_webhook(headers: Dict[str, str]) -> Optional[str]:
        """
        Extract Shopify store domain from webhook headers.
        
        Args:
            headers: Request headers
            
        Returns:
            Store domain if found, None otherwise
        """
        # Shopify typically includes store domain in X-Shopify-Shop-Domain header
        shop_domain = headers.get("X-Shopify-Shop-Domain") or headers.get("x-shopify-shop-domain")
        
        if shop_domain:
            # Remove protocol if present
            shop_domain = shop_domain.replace("https://", "").replace("http://", "").strip()
        
        return shop_domain

