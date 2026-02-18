"""
Consolidated webhook router for all integrations.
Handles both legacy Shopify-specific endpoints and generic integration webhooks.
"""

import json

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.integrations.registry import integration_registry
from app.services.slack_service import get_slack_service

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ============================================================================
# LEGACY SHOPIFY ENDPOINTS (must come BEFORE generic route for proper routing)
# ============================================================================


@router.post("/shopify/products/create")
async def shopify_product_create(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
):
    """Handle Shopify products/create webhook (legacy endpoint for backward compatibility)."""
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
    return await handle_webhook(
        integration_name="shopify",
        event_type="inventory_levels/update",
        request=request,
        x_shopify_hmac_sha256=x_shopify_hmac_sha256,
    )


# ============================================================================
# GENERIC WEBHOOK HANDLER (must come AFTER specific routes)
# ============================================================================


@router.post("/{integration_name}/{event_type:path}")
async def handle_webhook(
    integration_name: str,
    event_type: str,
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_square_hmacsha256_signature: str | None = Header(None, alias="x-square-hmacsha256-signature"),
):
    """
    Generic webhook handler that routes to the appropriate integration adapter.

    Examples:
        POST /webhooks/shopify/products/create
        POST /webhooks/square/inventory.updated
        POST /webhooks/ncr/product/create
    """
    payload = None  # Initialize payload variable for exception handler
    merchant_id = None  # Initialize merchant_id for exception handler

    try:
        # Get the integration adapter
        adapter = integration_registry.get_adapter(integration_name)

        if not adapter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration '{integration_name}' not found. Available integrations: {integration_registry.list_available()}",
            )

        # Check if event type is supported
        supported_events = adapter.get_supported_events()
        if event_type not in supported_events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Event type '{event_type}' not supported by {integration_name}. Supported events: {supported_events}",
            )

        # Read raw body for signature verification
        body_bytes = await request.body()

        # Get headers as dict
        headers = dict(request.headers)

        # Extract signature (integration-specific)
        signature = None
        if integration_name == "shopify":
            signature = (
                x_shopify_hmac_sha256
                or headers.get("X-Shopify-Hmac-Sha256")
                or headers.get("x-shopify-hmac-sha256")
            )
        elif integration_name == "square":
            signature = (
                x_square_hmacsha256_signature
                or headers.get("X-Square-HmacSha256-Signature")
                or headers.get("x-square-hmacsha256-signature")
            )
        elif integration_name == "clover":
            # X-Clover-Auth is a static auth code (not HMAC of body)
            signature = headers.get("X-Clover-Auth") or headers.get("x-clover-auth")

        # Verify signature
        # Square: always require signature presence and validity (no bypass when header missing)
        if integration_name == "square":
            if not (signature and str(signature).strip()):
                logger.warning(
                    "Square webhook rejected: missing signature header",
                    event_type=event_type,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing webhook signature",
                )
            request_url = str(request.url)
            is_valid = adapter.verify_signature(
                body_bytes, signature, headers, request_url=request_url
            )
            if not is_valid:
                logger.warning(
                    "Invalid Square webhook signature",
                    event_type=event_type,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature",
                )
        elif integration_name == "clover":
            # Clover sends a one-time verification POST with only {"verificationCode": "..."}
            # BEFORE the auth code exists. Allow that specific request through without X-Clover-Auth.
            if b"verificationCode" in body_bytes and b"merchants" not in body_bytes:
                # Verification code is logged in adapter when we return the response
                pass
            else:
                if not (signature and str(signature).strip()):
                    logger.warning(
                        "Clover webhook rejected: missing X-Clover-Auth header",
                        event_type=event_type,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Missing X-Clover-Auth header",
                    )
                is_valid = adapter.verify_signature(body_bytes, signature, headers)
                if not is_valid:
                    logger.warning(
                        "Invalid Clover webhook auth",
                        event_type=event_type,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid webhook signature",
                    )
        elif signature:
            # Shopify, NCR, etc. don't accept request_url parameter
            is_valid = adapter.verify_signature(body_bytes, signature, headers)
            if not is_valid:
                logger.warning(
                    "Invalid webhook signature",
                    integration=integration_name,
                    event_type=event_type,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature",
                )

        # Parse payload
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
            # Try to extract merchant_id from payload (for error reporting)
            merchant_id = payload.get("merchant_id") or payload.get("shop")
            if merchant_id is None and integration_name == "clover":
                merchants = payload.get("merchants") or {}
                if merchants:
                    merchant_id = next(iter(merchants), None)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {str(e)}",
            ) from e

        logger.info(
            "Processing webhook",
            integration=integration_name,
            event_type=event_type,
        )

        # Let the adapter handle the webhook
        result = await adapter.handle_webhook(
            event_type=event_type, request=request, headers=headers, payload=payload
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to process webhook",
            integration=integration_name,
            event_type=event_type,
            error=str(e),
        )

        # Send Slack alert for webhook errors
        try:
            slack_service = get_slack_service()
            await slack_service.send_webhook_error_alert(
                error_message=str(e),
                integration=integration_name,
                event_type=event_type,
                merchant_id=merchant_id,
            )
        except Exception as slack_error:
            logger.warning("Failed to send Slack alert", error=str(slack_error))

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}",
        ) from e
