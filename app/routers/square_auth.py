"""
Square OAuth authentication endpoints.
Handles OAuth flow for Square POS integration.
"""

from fastapi import APIRouter, Request, HTTPException, status, Query, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Optional, Dict
import structlog
import secrets
import httpx
import json
import base64
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote
from uuid import UUID

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.routers.auth import verify_token

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["square-auth"])
api_router = APIRouter(prefix="/api/auth/square", tags=["square-auth"])

# Rate limiting for manual sync (in-memory cache)
# Key: (merchant_id, user_id), Value: last_sync_timestamp
_manual_sync_rate_limit: Dict[tuple, datetime] = {}
_rate_limit_window = timedelta(minutes=1)  # 1 sync per minute per merchant per user


@router.get("/square")
async def square_oauth_initiate(
    hipoink_store_code: Optional[str] = Query(
        None, description="Hipoink store code from onboarding form"
    ),
    store_name: Optional[str] = Query(
        None, description="Store name from onboarding form"
    ),
    timezone: Optional[str] = Query(
        None, description="Timezone from onboarding form (e.g., America/New_York)"
    ),
    state: Optional[str] = Query(
        None, description="State parameter for CSRF protection (optional)"
    ),
):
    """
    Initiate Square OAuth flow.
    Accepts Hipoink code, store name, timezone from onboarding page.
    Encodes them into state parameter for retrieval in callback.
    Redirects to Square authorization page.
    """
    square_application_id = settings.square_application_id
    if not square_application_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Square Application ID not configured",
        )

    # Build state payload (CSRF + onboarding data)
    # This data will survive the OAuth redirect and come back in the callback
    state_data = {
        "token": state or secrets.token_urlsafe(32),  # CSRF protection token
        "hipoink_store_code": (hipoink_store_code or "").strip(),
        "store_name": (store_name or "").strip(),
        "timezone": (timezone or "").strip(),
    }
    
    # Encode state as base64 JSON for safe URL transmission
    state_token = base64.urlsafe_b64encode(
        json.dumps(state_data).encode()
    ).decode()

    # Build authorization URL
    # Square OAuth scopes for catalog, inventory, and merchant profile
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
        "Initiating Square OAuth with onboarding data",
        redirect_uri=redirect_uri,
        environment=settings.square_environment,
        has_hipoink_code=bool(hipoink_store_code),
        has_store_name=bool(store_name),
        timezone=timezone,
        auth_url=auth_url[:100] + "...",  # Log truncated URL for security
    )
    return RedirectResponse(url=auth_url, status_code=302)  # Explicit 302 redirect


@router.get("/square/callback")
async def square_oauth_callback(
    code: str = Query(..., description="Authorization code from Square"),
    state: Optional[str] = Query(None, description="State parameter"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Handle Square OAuth callback.
    Exchanges authorization code for access token.
    Decodes state to retrieve onboarding data.
    Creates/updates store mapping with all data.
    """
    square_application_id = settings.square_application_id
    square_application_secret = settings.square_application_secret
    if not square_application_id or not square_application_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Square API credentials not configured",
        )
    
    logger.info("Square OAuth callback received")
    
    # 1) Decode state to extract onboarding data
    hipoink_store_code = ""
    store_name = ""
    timezone = ""
    
    if state:
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            hipoink_store_code = (state_data.get("hipoink_store_code") or "").strip()
            store_name = (state_data.get("store_name") or "").strip()
            timezone = (state_data.get("timezone") or "").strip()
            logger.info(
                "Decoded Square OAuth state",
                hipoink_store_code=hipoink_store_code,
                store_name=store_name,
                timezone=timezone,
            )
        except Exception as e:
            logger.warning("Failed to decode Square state", error=str(e))
    
    try:
        # 2) Determine Square API base URL
        if settings.square_environment == "sandbox":
            base_api_url = "https://connect.squareupsandbox.com"
        else:
            base_api_url = "https://connect.squareup.com"
        
        # 3) Exchange authorization code for access token
        redirect_uri = f"{settings.app_base_url}/auth/square/callback"
        token_url = f"{base_api_url}/oauth2/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    "client_id": square_application_id,
                    "client_secret": square_application_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            token_data = response.json()
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")  # Also store refresh token
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
        
        # 4) Fetch merchant locations
        locations = await _fetch_square_locations(access_token, base_api_url)
        
        if not locations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No locations found for this Square merchant",
            )
        
        # Use first location as primary
        primary_location = locations[0]
        location_id = primary_location.get("id")
        location_name = primary_location.get("name", "Unknown")
        square_timezone = primary_location.get("timezone", "UTC")
        
        logger.info(
            "Square location found",
            merchant_id=merchant_id,
            location_id=location_id,
            location_name=location_name,
            square_timezone=square_timezone,
        )
        
        # 5) Determine final timezone (user selection wins, then Square's, then UTC)
        final_timezone = timezone or square_timezone or "UTC"
        
        # 6) Build metadata
        metadata = {
            "square_access_token": access_token,
            "square_refresh_token": refresh_token,  # Store for token refresh later
            "square_merchant_id": merchant_id,
            "square_location_id": location_id,
            "square_location_name": location_name,
            "square_expires_at": expires_at,
            "square_oauth_installed_at": datetime.utcnow().isoformat(),
            "all_locations": locations,
            "timezone": final_timezone,
        }
        
        # Add store_name to metadata if provided
        if store_name:
            metadata["store_name"] = store_name
        
        # 7) Create or update store mapping
        supabase_service = SupabaseService()
        existing_mapping = supabase_service.get_store_mapping("square", merchant_id)
        mapping_id = None
        
        if existing_mapping:
            # Update existing mapping
            existing_metadata = existing_mapping.metadata or {}
            existing_metadata.update(metadata)
            
            supabase_service.client.table("store_mappings").update(
                {
                    "metadata": existing_metadata,
                    "hipoink_store_code": hipoink_store_code or existing_mapping.hipoink_store_code,
                    "is_active": True,
                }
            ).eq("id", str(existing_mapping.id)).execute()
            
            mapping_id = str(existing_mapping.id)
            logger.info(
                "Updated Square store mapping with OAuth token",
                merchant_id=merchant_id,
                mapping_id=mapping_id,
                hipoink_store_code=hipoink_store_code or existing_mapping.hipoink_store_code,
            )
        else:
            # Create new mapping
            from app.models.database import StoreMapping
            
            new_mapping = StoreMapping(
                source_system="square",
                source_store_id=merchant_id,
                hipoink_store_code=hipoink_store_code,
                is_active=True,
                metadata=metadata,
            )
            
            created = supabase_service.create_store_mapping(new_mapping)
            mapping_id = str(created.id) if created.id else None
            logger.info(
                "Created Square store mapping with OAuth token",
                merchant_id=merchant_id,
                mapping_id=mapping_id,
                hipoink_store_code=hipoink_store_code,
            )
        
        # 8) Trigger initial product sync in background (non-blocking)
        if mapping_id:
            try:
                background_tasks.add_task(
                    trigger_initial_product_sync,
                    merchant_id=merchant_id,
                    access_token=access_token,
                    store_mapping_id=UUID(mapping_id),
                    base_url=base_api_url,
                )
                logger.info(
                    "Initial product sync scheduled",
                    merchant_id=merchant_id,
                    mapping_id=mapping_id,
                )
            except Exception as e:
                # Don't fail OAuth callback if sync scheduling fails
                logger.error(
                    "Failed to schedule initial product sync",
                    merchant_id=merchant_id,
                    error=str(e),
                )
        
        # 9) Redirect to frontend success page with URL-encoded parameters
        frontend_url = getattr(settings, "frontend_url", None) or "http://localhost:3000"
        if frontend_url.startswith("http://localhost:8000") or ":8000" in frontend_url:
            frontend_url = "http://localhost:3000"
        
        # URL-encode parameters to handle spaces and special characters
        redirect_url = (
            f"{frontend_url}/onboarding/square/success"
            f"?merchant_id={merchant_id}"
            f"&hipoink_store_code={quote(hipoink_store_code or 'none', safe='')}"
            f"&location_name={quote(location_name, safe='')}"
        )
        
        logger.info("Redirecting to success page", redirect_url=redirect_url)
        return RedirectResponse(url=redirect_url, status_code=302)
        
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


async def trigger_initial_product_sync(
    merchant_id: str,
    access_token: str,
    store_mapping_id: UUID,
    base_url: str,
):
    """
    Background task to sync all products from Square after OAuth completion.
    
    This function runs asynchronously after the OAuth callback response is sent,
    ensuring the user sees the success page immediately while products sync in the background.
    
    Args:
        merchant_id: Square merchant ID
        access_token: Square OAuth access token
        store_mapping_id: Store mapping UUID
        base_url: Square API base URL (sandbox or production)
    """
    supabase_service = SupabaseService()
    
    try:
        # Update metadata to indicate sync started
        store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
        if store_mapping:
            metadata = store_mapping.metadata or {}
            metadata["initial_sync_status"] = "in_progress"
            metadata["initial_sync_started_at"] = datetime.utcnow().isoformat()
            
            supabase_service.client.table("store_mappings").update(
                {"metadata": metadata}
            ).eq("id", str(store_mapping_id)).execute()
        
        from app.integrations.square.adapter import SquareIntegrationAdapter
        
        adapter = SquareIntegrationAdapter()
        result = await adapter.sync_all_products_from_square(
            merchant_id=merchant_id,
            access_token=access_token,
            store_mapping_id=store_mapping_id,
            base_url=base_url,
        )
        
        # Update metadata to indicate sync completed
        # Re-fetch store mapping to ensure we have latest data
        store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
        if store_mapping:
            metadata = store_mapping.metadata or {}
            metadata["initial_sync_status"] = "completed"
            metadata["initial_sync_completed_at"] = datetime.utcnow().isoformat()
            metadata["initial_sync_stats"] = {
                "total_items": result.get("total_items", 0),
                "products_created": result.get("products_created", 0),
                "products_updated": result.get("products_updated", 0),
                "queued_for_sync": result.get("queued_for_sync", 0),
                "errors": result.get("errors", 0),
            }
            
            supabase_service.client.table("store_mappings").update(
                {"metadata": metadata}
            ).eq("id", str(store_mapping_id)).execute()
        
        logger.info(
            "Initial product sync completed",
            merchant_id=merchant_id,
            store_mapping_id=str(store_mapping_id),
            total_items=result.get("total_items", 0),
            products_created=result.get("products_created", 0),
            products_updated=result.get("products_updated", 0),
            queued_for_sync=result.get("queued_for_sync", 0),
            errors=result.get("errors", 0),
        )
    except Exception as e:
        # Update metadata to indicate sync failed
        try:
            store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
            if store_mapping:
                metadata = store_mapping.metadata or {}
                metadata["initial_sync_status"] = "failed"
                metadata["initial_sync_error"] = str(e)
                
                supabase_service.client.table("store_mappings").update(
                    {"metadata": metadata}
                ).eq("id", str(store_mapping_id)).execute()
        except Exception as update_error:
            logger.error("Failed to update sync status", error=str(update_error))
        
        logger.error(
            "Initial product sync failed",
            merchant_id=merchant_id,
            store_mapping_id=str(store_mapping_id),
            error=str(e),
            error_type=type(e).__name__,
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


@api_router.get("/sync-status")
async def get_square_sync_status(
    merchant_id: str = Query(..., description="Square merchant ID"),
):
    """
    Get the current sync status for a Square merchant.
    Returns sync progress, product counts, and queue status.
    """
    supabase_service = SupabaseService()

    # Get store mapping
    store_mapping = supabase_service.get_store_mapping("square", merchant_id)

    if not store_mapping:
        return {
            "status": "not_found",
            "message": "Store mapping not found",
            "stats": None,
        }

    # Check metadata for sync status
    metadata = store_mapping.metadata or {}
    sync_status = metadata.get("initial_sync_status", "pending")
    sync_started_at = metadata.get("initial_sync_started_at")
    sync_completed_at = metadata.get("initial_sync_completed_at")
    sync_stats = metadata.get("initial_sync_stats")

    # Count products in database for this merchant
    # Note: We can't directly filter by merchant_id in products table,
    # but we can count all Square products and pending queue items
    all_square_products = supabase_service.get_products_by_system("square")
    total_products = len(all_square_products)

    # Count products in sync queue for this store mapping
    try:
        pending_queue_items = supabase_service.get_pending_sync_queue_items(limit=1000)
        queued_count = sum(
            1
            for item in pending_queue_items
            if str(item.store_mapping_id) == str(store_mapping.id)
        )
    except Exception as e:
        logger.warning("Failed to get queue count", error=str(e))
        queued_count = 0

    # Determine overall status
    if sync_status == "in_progress":
        status = "syncing"
    elif sync_status == "completed":
        status = "complete"
    elif sync_status == "failed":
        status = "failed"
    elif sync_completed_at:
        # If sync was completed but status not set, assume complete
        status = "complete"
    else:
        # Default to pending if no sync has started
        status = "pending"

    return {
        "status": status,
        "merchant_id": merchant_id,
        "store_mapping_id": str(store_mapping.id),
        "stats": {
            "total_products": total_products,
            "queued_for_sync": queued_count,
            "sync_started_at": sync_started_at,
            "sync_completed_at": sync_completed_at,
            **(
                sync_stats
                if sync_stats
                else {
                    "total_items": 0,
                    "products_created": 0,
                    "products_updated": 0,
                    "queued_for_sync": queued_count,
                    "errors": 0,
                }
            ),
        },
    }


@api_router.post("/manual-sync")
async def manual_sync_square_products(
    merchant_id: str = Query(..., description="Square merchant ID"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user_data: dict = Depends(verify_token),  # Require authentication
):
    """
    Manually trigger a full product sync from Square.
    
    This endpoint allows authenticated users to manually sync products when:
    - Unit cost changes don't trigger webhooks
    - Products need to be refreshed
    - Initial sync needs to be re-run
    
    **Rate Limited**: 1 sync per minute per merchant per user
    
    **Authentication Required**: Bearer token in Authorization header
    
    Args:
        merchant_id: Square merchant ID
        background_tasks: FastAPI background tasks for async processing
        user_data: Authenticated user data (from token)
    
    Returns:
        Status response with sync job information
    
    Raises:
        HTTPException: If rate limited, unauthorized, or sync fails
    """
    user_id = user_data.get("user_id")
    
    # Rate limiting: Check if user has synced this merchant recently
    rate_limit_key = (merchant_id, user_id)
    now = datetime.utcnow()
    
    if rate_limit_key in _manual_sync_rate_limit:
        last_sync = _manual_sync_rate_limit[rate_limit_key]
        time_since_last_sync = now - last_sync
        
        if time_since_last_sync < _rate_limit_window:
            remaining_seconds = int((_rate_limit_window - time_since_last_sync).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please wait {remaining_seconds} seconds before syncing again.",
                headers={"Retry-After": str(remaining_seconds)},
            )
    
    # Update rate limit cache
    _manual_sync_rate_limit[rate_limit_key] = now
    
    # Clean up old entries (keep cache size manageable)
    if len(_manual_sync_rate_limit) > 1000:
        # Remove entries older than 1 hour
        cutoff = now - timedelta(hours=1)
        _manual_sync_rate_limit.clear()  # Simple cleanup - in production, use a proper cache
    
    supabase_service = SupabaseService()
    
    # Get store mapping
    store_mapping = supabase_service.get_store_mapping("square", merchant_id)
    
    if not store_mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store mapping not found for merchant_id: {merchant_id}",
        )
    
    # Get access token
    from app.integrations.square.adapter import SquareIntegrationAdapter
    from app.integrations.square.token_refresh import ensure_valid_square_token
    
    adapter = SquareIntegrationAdapter()
    
    try:
        # Ensure we have a valid access token
        access_token = await adapter._ensure_valid_token(store_mapping)
        
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No valid access token found. Please reconnect your Square account.",
            )
        
        # Determine base URL (sandbox or production)
        base_url = (
            "https://connect.squareupsandbox.com"
            if settings.square_environment == "sandbox"
            else "https://connect.squareup.com"
        )
        
        # Trigger sync in background
        background_tasks.add_task(
            trigger_initial_product_sync,
            merchant_id=merchant_id,
            access_token=access_token,
            store_mapping_id=store_mapping.id,
            base_url=base_url,
        )
        
        logger.info(
            "Manual product sync triggered",
            merchant_id=merchant_id,
            store_mapping_id=str(store_mapping.id),
            user_id=user_id,
        )
        
        return {
            "status": "success",
            "message": "Product sync started in background",
            "merchant_id": merchant_id,
            "store_mapping_id": str(store_mapping.id),
            "note": "Sync is running in the background. Check sync-status endpoint for progress.",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to trigger manual sync",
            merchant_id=merchant_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {str(e)}",
        )