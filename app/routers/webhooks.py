"""
FastAPI router for Shopify webhook endpoints (legacy routes for backward compatibility).
This router delegates to the new integration adapter system.
New code should use the generic webhook router at /webhooks/{integration_name}/{event_type}
"""

import structlog
from fastapi import APIRouter, Header, Request

# Import new integration system

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Backward compatibility: Keep old endpoint structure but delegate to adapter


@router.post("/shopify/products/create")
async def shopify_product_create(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
):
    """Handle Shopify products/create webhook (legacy endpoint for backward compatibility)."""
    from app.routers.webhooks_new import handle_webhook

    return await handle_webhook(
        integration_name="shopify",
        event_type="products/create",
        request=request,
        x_shopify_hmac_sha256=x_shopify_hmac_sha256,
    )


@router.post("/shopify/products/update")
async def shopify_product_update(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
):
    """Handle Shopify products/update webhook (legacy endpoint for backward compatibility)."""
    from app.routers.webhooks_new import handle_webhook

    return await handle_webhook(
        integration_name="shopify",
        event_type="products/update",
        request=request,
        x_shopify_hmac_sha256=x_shopify_hmac_sha256,
    )


@router.post("/shopify/products/delete")
async def shopify_product_delete(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
):
    """Handle Shopify products/delete webhook (legacy endpoint for backward compatibility)."""
    from app.routers.webhooks_new import handle_webhook

    return await handle_webhook(
        integration_name="shopify",
        event_type="products/delete",
        request=request,
        x_shopify_hmac_sha256=x_shopify_hmac_sha256,
    )


@router.post("/shopify/inventory_levels/update")
async def shopify_inventory_update(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
):
    """Handle Shopify inventory_levels/update webhook (legacy endpoint for backward compatibility)."""
    from app.routers.webhooks_new import handle_webhook

    return await handle_webhook(
        integration_name="shopify",
        event_type="inventory_levels/update",
        request=request,
        x_shopify_hmac_sha256=x_shopify_hmac_sha256,
    )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
