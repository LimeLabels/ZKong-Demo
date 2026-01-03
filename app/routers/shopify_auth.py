"""
Shopify OAuth authentication endpoints for the embedded app.
Handles OAuth flow and session management.
"""

from fastapi import APIRouter, Request, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from typing import Optional
import structlog
import hashlib
import base64

from app.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["shopify-auth"])


@router.get("/shopify")
async def shopify_oauth_initiate(
    shop: str = Query(..., description="Shop domain (e.g., myshop.myshopify.com)"),
    hmac: Optional[str] = Query(
        None, alias="hmac", description="HMAC for verification"
    ),
    timestamp: Optional[str] = Query(None, description="Request timestamp"),
    state: Optional[str] = Query(
        None, description="State parameter for CSRF protection"
    ),
):
    """
    Initiate Shopify OAuth flow.
    Redirects to Shopify authorization page.
    """
    # TODO: Implement OAuth initiation
    # 1. Generate state token for CSRF protection
    # 2. Build authorization URL
    # 3. Redirect to Shopify

    shopify_api_key = getattr(settings, "shopify_api_key", None)
    if not shopify_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shopify API key not configured",
        )

    # Build authorization URL
    scopes = "read_products,write_products"
    redirect_uri = f"{settings.app_base_url}/auth/shopify/callback"
    auth_url = (
        f"https://{shop}/admin/oauth/authorize?"
        f"client_id={shopify_api_key}&"
        f"scope={scopes}&"
        f"redirect_uri={redirect_uri}&"
        f"state={state or 'default'}"
    )

    return RedirectResponse(url=auth_url)


@router.get("/shopify/callback")
async def shopify_oauth_callback(
    code: str = Query(..., description="Authorization code from Shopify"),
    shop: str = Query(..., description="Shop domain"),
    state: Optional[str] = Query(None, description="State parameter"),
    hmac: Optional[str] = Query(
        None, alias="hmac", description="HMAC for verification"
    ),
):
    """
    Handle Shopify OAuth callback.
    Exchanges authorization code for access token.
    """
    # TODO: Implement OAuth callback
    # 1. Verify HMAC
    # 2. Exchange code for access token
    # 3. Store access token (in database or session)
    # 4. Redirect to app

    logger.info("Shopify OAuth callback received", shop=shop)

    # For now, return success (implement full OAuth flow later)
    return {
        "status": "success",
        "message": "OAuth callback received. Full implementation pending.",
        "shop": shop,
    }


@router.get("/shopify/verify")
async def verify_shopify_request(
    request: Request,
    shop: str = Query(..., description="Shop domain"),
    timestamp: str = Query(..., description="Request timestamp"),
    hmac: str = Query(..., alias="hmac", description="HMAC signature"),
):
    """
    Verify Shopify request signature.
    Used for webhook verification and app proxy requests.
    """
    shopify_api_secret = getattr(settings, "shopify_api_secret", None)
    if not shopify_api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shopify API secret not configured",
        )

    # Get query parameters
    query_params = dict(request.query_params)
    received_hmac = query_params.pop("hmac", None)

    if not received_hmac:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HMAC signature missing",
        )

    # Build message string
    sorted_params = sorted(query_params.items())
    message = "&".join([f"{key}={value}" for key, value in sorted_params])

    # Calculate HMAC
    calculated_hmac = base64.b64encode(
        hmac.new(
            shopify_api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    # Compare HMACs
    if not hmac.compare_digest(calculated_hmac, received_hmac):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature",
        )

    return {"status": "verified", "shop": shop}
