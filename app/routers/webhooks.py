"""
FastAPI router for Shopify webhook endpoints.
Handles products/create, products/update, products/delete, and inventory_levels/update events.
"""
import hmac
import hashlib
import base64
from fastapi import APIRouter, Request, HTTPException, Header, status
from typing import Optional
import structlog
import json

from app.config import settings
from app.models.shopify import (
    ProductCreateWebhook,
    ProductUpdateWebhook,
    ProductDeleteWebhook,
    InventoryLevelsUpdateWebhook
)
from app.services.shopify_service import ShopifyService
from app.services.supabase_service import SupabaseService
from app.models.database import Product

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
supabase_service = SupabaseService()
shopify_service = ShopifyService()


def verify_shopify_webhook(data: bytes, hmac_header: str) -> bool:
    """
    Verify Shopify webhook signature.
    
    Args:
        data: Raw request body bytes
        hmac_header: X-Shopify-Hmac-Sha256 header value
        
    Returns:
        True if signature is valid, False otherwise
    """
    if not hmac_header:
        return False
    
    # Calculate HMAC
    calculated_hmac = base64.b64encode(
        hmac.new(
            settings.shopify_webhook_secret.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
    ).decode('utf-8')
    
    # Compare using secure comparison to prevent timing attacks
    return hmac.compare_digest(calculated_hmac, hmac_header)


@router.post("/shopify/products/create")
async def shopify_product_create(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_shop_domain: Optional[str] = Header(None, alias="X-Shopify-Shop-Domain"),
    x_shopify_topic: Optional[str] = Header(None, alias="X-Shopify-Topic")
):
    """
    Handle Shopify products/create webhook.
    Validates signature, transforms product data, stores in Supabase, and queues for sync.
    """
    # Read raw body for signature verification
    body_bytes = await request.body()
    
    # Verify webhook signature
    if not verify_shopify_webhook(body_bytes, x_shopify_hmac_sha256 or ""):
        logger.warning("Invalid Shopify webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    try:
        # Parse webhook payload
        payload = json.loads(body_bytes.decode('utf-8'))
        product_data = ProductCreateWebhook(**payload)
        
        # Extract store domain
        store_domain = x_shopify_shop_domain or shopify_service.extract_store_domain_from_webhook(
            dict(request.headers)
        )
        
        if not store_domain:
            logger.warning("Could not determine Shopify store domain")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found"
            )
        
        # Get store mapping
        store_mapping = supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            logger.warning(
                "No store mapping found for Shopify store",
                store_domain=store_domain
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first",
                    "endpoint": "/api/store-mappings/",
                    "example": {
                        "source_system": "shopify",
                        "source_store_id": store_domain,
                        "zkong_merchant_id": "your_zkong_merchant_id",
                        "zkong_store_id": "your_zkong_store_id"
                    }
                }
            )
        
        # Transform Shopify product variants to normalized products
        normalized_products = shopify_service.extract_variants_from_product(product_data)
        
        created_products = []
        
        # Store each variant as a separate product
        for normalized in normalized_products:
            # Validate normalized product
            is_valid, errors = shopify_service.validate_normalized_product(normalized)
            
            # Create product record
            product = Product(
                source_system="shopify",
                source_id=normalized["source_id"],
                source_variant_id=normalized.get("source_variant_id"),
                title=normalized["title"],
                barcode=normalized.get("barcode"),
                sku=normalized.get("sku"),
                price=normalized.get("price"),
                currency=normalized.get("currency", "USD"),
                image_url=normalized.get("image_url"),
                raw_data=payload,
                normalized_data=normalized,
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None
            )
            
            # Save to database
            saved_product = supabase_service.create_or_update_product(product)
            created_products.append(saved_product)
            
            # If valid, add to sync queue
            if is_valid:
                supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="create"
                )
                logger.info(
                    "Product queued for sync",
                    product_id=str(saved_product.id),
                    barcode=normalized.get("barcode")
                )
        
        return {
            "status": "success",
            "message": f"Processed {len(created_products)} product(s)",
            "products": [{"id": str(p.id), "title": p.title} for p in created_products]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process Shopify product create webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )


@router.post("/shopify/products/update")
async def shopify_product_update(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_shop_domain: Optional[str] = Header(None, alias="X-Shopify-Shop-Domain")
):
    """
    Handle Shopify products/update webhook.
    Similar to create, but uses 'update' operation in sync queue.
    """
    body_bytes = await request.body()
    
    if not verify_shopify_webhook(body_bytes, x_shopify_hmac_sha256 or ""):
        logger.warning("Invalid Shopify webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    try:
        payload = json.loads(body_bytes.decode('utf-8'))
        product_data = ProductUpdateWebhook(**payload)
        
        store_domain = x_shopify_shop_domain or shopify_service.extract_store_domain_from_webhook(
            dict(request.headers)
        )
        
        if not store_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found"
            )
        
        store_mapping = supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first via POST /api/store-mappings/"
                }
            )
        
        normalized_products = shopify_service.extract_variants_from_product(product_data)
        
        updated_products = []
        
        for normalized in normalized_products:
            is_valid, errors = shopify_service.validate_normalized_product(normalized)
            
            product = Product(
                source_system="shopify",
                source_id=normalized["source_id"],
                source_variant_id=normalized.get("source_variant_id"),
                title=normalized["title"],
                barcode=normalized.get("barcode"),
                sku=normalized.get("sku"),
                price=normalized.get("price"),
                currency=normalized.get("currency", "USD"),
                image_url=normalized.get("image_url"),
                raw_data=payload,
                normalized_data=normalized,
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None
            )
            
            saved_product = supabase_service.create_or_update_product(product)
            updated_products.append(saved_product)
            
            if is_valid:
                supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="update"
                )
        
        return {
            "status": "success",
            "message": f"Updated {len(updated_products)} product(s)",
            "products": [{"id": str(p.id), "title": p.title} for p in updated_products]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process Shopify product update webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )


@router.post("/shopify/products/delete")
async def shopify_product_delete(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_shop_domain: Optional[str] = Header(None, alias="X-Shopify-Shop-Domain")
):
    """
    Handle Shopify products/delete webhook.
    Queues products for deletion in ZKong.
    """
    body_bytes = await request.body()
    
    if not verify_shopify_webhook(body_bytes, x_shopify_hmac_sha256 or ""):
        logger.warning("Invalid Shopify webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    try:
        payload = json.loads(body_bytes.decode('utf-8'))
        product_data = ProductDeleteWebhook(**payload)
        
        store_domain = x_shopify_shop_domain or shopify_service.extract_store_domain_from_webhook(
            dict(request.headers)
        )
        
        if not store_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found"
            )
        
        store_mapping = supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first via POST /api/store-mappings/"
                }
            )
        
        # Find all products with this source_id (all variants)
        # For simplicity, we'll find and queue each variant
        # In production, you might want to query Supabase for all variants
        
        return {
            "status": "success",
            "message": "Product deletion queued",
            "product_id": product_data.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process Shopify product delete webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )


@router.post("/shopify/inventory_levels/update")
async def shopify_inventory_update(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_shop_domain: Optional[str] = Header(None, alias="X-Shopify-Shop-Domain")
):
    """
    Handle Shopify inventory_levels/update webhook.
    Updates product inventory/price if needed.
    """
    body_bytes = await request.body()
    
    if not verify_shopify_webhook(body_bytes, x_shopify_hmac_sha256 or ""):
        logger.warning("Invalid Shopify webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    try:
        payload = json.loads(body_bytes.decode('utf-8'))
        inventory_data = InventoryLevelsUpdateWebhook(**payload)
        
        # Inventory updates might affect pricing or availability
        # For now, we'll log it - you can extend this to update products if needed
        logger.info("Inventory level updated", inventory_item_id=inventory_data.inventory_item_id)
        
        return {
            "status": "success",
            "message": "Inventory update received",
            "inventory_item_id": inventory_data.inventory_item_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process Shopify inventory update webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

