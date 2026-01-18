"""
Generic webhook router that delegates to integration adapters.
This is the new router that supports multiple integrations.
"""

from fastapi import APIRouter, Request, HTTPException, Header, status
from typing import Optional
import structlog
import json

from app.integrations.registry import integration_registry

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{integration_name}/{event_type:path}")
async def handle_webhook(
    integration_name: str,
    event_type: str,
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_square_hmacsha256_signature: Optional[str] = Header(None, alias="x-square-hmacsha256-signature"),
):
    """
    Generic webhook handler that routes to the appropriate integration adapter.

    Examples:
        POST /webhooks/shopify/products/create
        POST /webhooks/square/inventory.updated
        POST /webhooks/ncr/product/create
    """
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
        # Add other integrations' signature extraction here

        # Verify signature
        # For Square, pass request URL for signature verification (Square doesn't send it in headers)
        request_url = str(request.url) if integration_name == "square" else None
        if signature and not adapter.verify_signature(body_bytes, signature, headers, request_url=request_url):
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
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {str(e)}",
            )

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}",
        )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "available_integrations": integration_registry.list_available(),
    }
