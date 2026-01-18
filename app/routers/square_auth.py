"""
Square OAuth authentication endpoints.
Handles OAuth flow for Square POS integration.
"""

from fastapi import APIRouter, Request, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from typing import Optional
import structlog
import secrets
import httpx
from datetime import datetime
from urllib.parse import urlencode

from app.config import settings
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["square-auth"])
api_router = APIRouter(prefix="/api/auth/square", tags=["square-auth"])


@router.get("/square")
async def square_oauth_initiate(
    state: Optional[str] = Query(
        None, description="State parameter for CSRF protection"
    ),
):
    """
    Initiate Square OAuth flow.
    Redirects to Square authorization page.
    """
    square_application_id = settings.square_application_id
    if not square_application_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Square Application ID not configured",
        )

    # Generate state token for CSRF protection if not provided
    state_token = state or secrets.token_urlsafe(32)

    # Build authorization URL
    # Square OAuth scopes (added ORDERS_READ ORDERS_WRITE for future order features)
    scopes = (
        "ITEMS_READ "
        "ITEMS_WRITE "
        "INVENTORY_READ "
        "INVENTORY_WRITE "
        "MERCHANT_PROFILE_READ "
        "ORDERS_READ "
        "ORDERS_WRITE"
    )

    # Redirect URI - use app_base_url for backend callback
    redirect_uri = f"{settings.app_base_url}/auth/square/callback"

    # Determine Square API base URL based on environment
    if settings.square_environment == "sandbox":
        base_url = "https://connect.squareupsandbox.com"
    else:
        base_url = "https://connect.squareup.com"

    # Build Square OAuth URL
    params = {
        "client_id": square_application_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state_token,
    }

    auth_url = f"{base_url}/oauth2/authorize?{urlencode(params)}"

    logger.info(
        "Initiating Square OAuth",
        redirect_uri=redirect_uri,
        environment=settings.square_environment,
        auth_url=auth_url,  # Log the full Square OAuth URL for debugging
    )
    return RedirectResponse(url=auth_url, status_code=302)  # Explicit 302 redirect


@router.get("/square/callback")
async def square_oauth_callback(
    code: str = Query(..., description="Authorization code from Square"),
    state: Optional[str] = Query(None, description="State parameter"),
):
    """
    Handle Square OAuth callback.
    Exchanges authorization code for access token.
    """
    square_application_id = settings.square_application_id
    square_application_secret = settings.square_application_secret

    if not square_application_id or not square_application_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Square API credentials not configured",
        )

    logger.info("Square OAuth callback received")

    try:
        # Determine Square API base URL based on environment
        if settings.square_environment == "sandbox":
            base_api_url = "https://connect.squareupsandbox.com"
        else:
            base_api_url = "https://connect.squareup.com"

        # Exchange authorization code for access token
        token_url = f"{base_api_url}/oauth2/token"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    "client_id": square_application_id,
                    "client_secret": square_application_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        merchant_id = token_data.get("merchant_id")
        expires_at = token_data.get("expires_at")

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token in response",
            )

        logger.info(
            "Square OAuth token received",
            merchant_id=merchant_id,
            expires_at=expires_at,
        )

        # Fetch merchant locations
        locations = await _fetch_square_locations(access_token, base_api_url)

        if not locations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No locations found for this Square merchant",
            )

        # Use first location as primary (can be enhanced to allow selection)
        primary_location = locations[0]
        location_id = primary_location.get("id")
        location_name = primary_location.get("name", "Unknown")

        logger.info(
            "Square location found",
            location_id=location_id,
            location_name=location_name,
        )

        # Store access token and location in database
        supabase_service = SupabaseService()

        # Check if store mapping exists for this merchant/location
        existing_mapping = supabase_service.get_store_mapping("square", merchant_id)

        if existing_mapping:
            # Update existing mapping with access token via direct metadata update
            existing_metadata = existing_mapping.metadata or {}
            existing_metadata.update({
                "square_access_token": access_token,
                "square_merchant_id": merchant_id,
                "square_location_id": location_id,
                "square_location_name": location_name,
                "square_expires_at": expires_at,
                "square_oauth_installed_at": datetime.utcnow().isoformat(),
                "all_locations": locations,
            })

            # Update via Supabase client directly
            supabase_service.client.table("store_mappings").update({
                "metadata": existing_metadata
            }).eq("id", str(existing_mapping.id)).execute()

            logger.info(
                "Updated Square store mapping with OAuth token",
                merchant_id=merchant_id,
                mapping_id=str(existing_mapping.id),
            )
        else:
            # Auto-create store mapping with OAuth token
            from app.models.database import StoreMapping

            new_mapping = StoreMapping(
                source_system="square",
                source_store_id=merchant_id,
                hipoink_store_code="",  # Will be set during onboarding
                is_active=True,
                metadata={
                    "square_access_token": access_token,
                    "square_merchant_id": merchant_id,
                    "square_location_id": location_id,
                    "square_location_name": location_name,
                    "square_expires_at": expires_at,
                    "square_oauth_installed_at": datetime.utcnow().isoformat(),
                    "all_locations": locations,
                },
            )

            try:
                created_mapping = supabase_service.create_store_mapping(new_mapping)
                logger.info(
                    "Auto-created Square store mapping with OAuth token",
                    merchant_id=merchant_id,
                    mapping_id=str(created_mapping.id),
                )
            except Exception as e:
                logger.error(
                    "Failed to auto-create Square store mapping",
                    merchant_id=merchant_id,
                    error=str(e),
                )
                # Continue anyway - onboarding will handle it

        # Redirect to frontend with success
        frontend_url = settings.frontend_url or "http://localhost:3000"
        redirect_url = (
            f"{frontend_url}/square/success?"
            f"merchant_id={merchant_id}&"
            f"location_id={location_id}&"
            f"installed=true"
        )

        return RedirectResponse(url=redirect_url)

    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to exchange Square OAuth code for token",
            status_code=e.response.status_code,
            error=e.response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {e.response.text}",
        )
    except Exception as e:
        logger.error("Error in Square OAuth callback", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {str(e)}",
        )


async def _fetch_square_locations(access_token: str, base_api_url: str) -> list:
    """
    Fetch merchant locations from Square API.

    Args:
        access_token: Square OAuth access token
        base_api_url: Square API base URL (sandbox or production)

    Returns:
        List of location objects
    """
    locations_url = f"{base_api_url}/v2/locations"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            locations_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    return data.get("locations", [])


@api_router.get("/me")
async def get_square_auth_status(
    merchant_id: str = Query(..., description="Square merchant ID"),
):
    """
    Get current Square merchant's authentication state and store mapping.
    Returns merchant info and store mapping if available.
    """
    supabase_service = SupabaseService()

    # Get store mapping for this merchant
    store_mapping = supabase_service.get_store_mapping("square", merchant_id)

    # Check if OAuth token exists
    has_oauth_token = False
    needs_onboarding = False

    if store_mapping:
        if store_mapping.metadata and store_mapping.metadata.get(
            "square_access_token"
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
        "merchant_id": merchant_id,
        "is_authenticated": has_oauth_token,
        "needs_onboarding": needs_onboarding,
        "store_mapping": {
            "id": str(store_mapping.id) if store_mapping else None,
            "hipoink_store_code": store_mapping.hipoink_store_code
            if store_mapping
            else None,
            "location_id": store_mapping.metadata.get("square_location_id")
            if store_mapping and store_mapping.metadata
            else None,
            "location_name": store_mapping.metadata.get("square_location_name")
            if store_mapping and store_mapping.metadata
            else None,
        }
        if store_mapping
        else None,
    }


@api_router.get("/locations")
async def get_square_locations(
    merchant_id: str = Query(..., description="Square merchant ID"),
):
    """
    Get all locations for a Square merchant.
    Useful when merchant has multiple locations.
    """
    supabase_service = SupabaseService()

    store_mapping = supabase_service.get_store_mapping("square", merchant_id)

    if not store_mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store mapping not found for merchant {merchant_id}",
        )

    if not store_mapping.metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store mapping has no metadata",
        )

    locations = store_mapping.metadata.get("all_locations", [])

    return {
        "merchant_id": merchant_id,
        "locations": locations,
        "primary_location_id": store_mapping.metadata.get("square_location_id"),
    }