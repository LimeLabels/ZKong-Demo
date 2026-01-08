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
import secrets
import httpx
from datetime import datetime

from app.config import settings
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["shopify-auth"])
api_router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/shopify")
async def shopify_oauth_initiate(
    shop: str = Query(..., description="Shop domain (e.g., myshop.myshopify.com)"),
    hmac_param: Optional[str] = Query(
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
    shopify_api_key = getattr(settings, "shopify_api_key", None)
    if not shopify_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shopify API key not configured",
        )

    # Generate state token for CSRF protection if not provided
    state_token = state or secrets.token_urlsafe(32)

    # Build authorization URL
    # redirect_uri must match the App URL domain (frontend URL)
    # Frontend proxies /auth to backend, so use frontend URL
    scopes = "read_products,write_products,read_inventory,write_inventory"
    frontend_url = getattr(settings, "frontend_url", None) or getattr(settings, "app_base_url", "http://localhost:3000")
    # If app_base_url looks like backend (port 8000), use frontend default
    if frontend_url.startswith("http://localhost:8000") or ":8000" in frontend_url:
        frontend_url = "http://localhost:3000"
    redirect_uri = f"{frontend_url}/auth/shopify/callback"
    auth_url = (
        f"https://{shop}/admin/oauth/authorize?"
        f"client_id={shopify_api_key}&"
        f"scope={scopes}&"
        f"redirect_uri={redirect_uri}&"
        f"state={state_token}"
    )

    logger.info("Initiating Shopify OAuth", shop=shop)
    return RedirectResponse(url=auth_url)


@router.get("/shopify/callback")
async def shopify_oauth_callback(
    code: str = Query(..., description="Authorization code from Shopify"),
    shop: str = Query(..., description="Shop domain"),
    state: Optional[str] = Query(None, description="State parameter"),
    hmac_param: Optional[str] = Query(
        None, alias="hmac", description="HMAC for verification"
    ),
):
    """
    Handle Shopify OAuth callback.
    Exchanges authorization code for access token.
    """
    shopify_api_key = getattr(settings, "shopify_api_key", None)
    shopify_api_secret = getattr(settings, "shopify_api_secret", None)

    if not shopify_api_key or not shopify_api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shopify API credentials not configured",
        )

    logger.info("Shopify OAuth callback received", shop=shop)

    try:
        # Exchange authorization code for access token
        token_url = f"https://{shop}/admin/oauth/access_token"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    "client_id": shopify_api_key,
                    "client_secret": shopify_api_secret,
                    "code": code,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token in response",
            )

        # Store access token in database
        supabase_service = SupabaseService()

        # Check if store mapping exists by shop domain or source_store_id
        existing_mapping = supabase_service.get_store_mapping("shopify", shop)
        if not existing_mapping:
            existing_mapping = supabase_service.get_store_mapping_by_shop_domain(shop)

        if existing_mapping:
            # Update existing mapping with access token
            updated = supabase_service.update_store_mapping_oauth_token(
                existing_mapping.id,  # type: ignore
                shop,
                access_token,
            )

            if updated:
                logger.info(
                    "Updated store mapping with OAuth token",
                    shop=shop,
                    mapping_id=str(existing_mapping.id),
                )
            else:
                logger.warning(
                    "Failed to update store mapping with OAuth token", shop=shop
                )
        else:
            # Auto-create store mapping with OAuth token
            # Hipoink store code will be set during onboarding
            from app.models.database import StoreMapping

            new_mapping = StoreMapping(
                source_system="shopify",
                source_store_id=shop,
                hipoink_store_code="",  # Will be set during onboarding
                is_active=True,
                metadata={
                    "shopify_shop_domain": shop,
                    "shopify_access_token": access_token,
                    "shopify_oauth_installed_at": datetime.utcnow().isoformat(),
                },
            )

            try:
                created_mapping = supabase_service.create_store_mapping(new_mapping)
                logger.info(
                    "Auto-created store mapping with OAuth token",
                    shop=shop,
                    mapping_id=str(created_mapping.id),
                )
            except Exception as e:
                logger.error(
                    "Failed to auto-create store mapping", shop=shop, error=str(e)
                )
                # Continue anyway - onboarding will handle it

        # Redirect to frontend app
        frontend_url = getattr(settings, "app_base_url", "http://localhost:3000")
        if frontend_url.startswith("http://localhost:8000"):
            # If backend URL, assume frontend is on port 3000
            frontend_url = "http://localhost:3000"

        redirect_url = f"{frontend_url}?shop={shop}&installed=true"
        return RedirectResponse(url=redirect_url)

    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to exchange OAuth code for token",
            shop=shop,
            status_code=e.response.status_code,
            error=e.response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {e.response.text}",
        )
    except Exception as e:
        logger.error("Error in OAuth callback", shop=shop, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {str(e)}",
        )


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


@api_router.get("/me")
async def get_current_auth(shop: str = Query(..., description="Shop domain")):
    """
    Get current shop's authentication state and store mapping.
    Returns shop info and store mapping if available.
    """
    supabase_service = SupabaseService()

    # Get store mapping for this shop
    store_mapping = supabase_service.get_store_mapping("shopify", shop)
    if not store_mapping:
        store_mapping = supabase_service.get_store_mapping_by_shop_domain(shop)

    # Check if OAuth token exists
    has_oauth_token = False
    needs_onboarding = False

    if store_mapping:
        if store_mapping.metadata and store_mapping.metadata.get(
            "shopify_access_token"
        ):
            has_oauth_token = True
        # Check if Hipoink store code is set (indicates onboarding complete)
        if (
            not store_mapping.hipoink_store_code
            or store_mapping.hipoink_store_code == ""
        ):
            needs_onboarding = True
    else:
        needs_onboarding = True

    return {
        "shop": shop,
        "is_authenticated": has_oauth_token,
        "needs_onboarding": needs_onboarding,
        "store_mapping": {
            "id": str(store_mapping.id) if store_mapping else None,
            "hipoink_store_code": store_mapping.hipoink_store_code
            if store_mapping
            else None,
            "timezone": store_mapping.metadata.get("timezone")
            if store_mapping and store_mapping.metadata
            else None,
        }
        if store_mapping
        else None,
    }
