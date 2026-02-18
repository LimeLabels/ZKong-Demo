"""
Clover OAuth authentication endpoints.
Handles OAuth flow for Clover POS integration (authorize, callback, store mapping).
"""

import base64
import json
import secrets
from datetime import datetime
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import settings
from app.integrations.clover.token_encryption import encrypt_tokens_for_storage
from app.models.database import StoreMapping
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["clover-auth"])

# Clover OAuth URLs (plan §2.3)
CLOVER_AUTHORIZE_URL_SANDBOX = "https://sandbox.dev.clover.com/oauth/v2/authorize"
CLOVER_AUTHORIZE_URL_PRODUCTION = "https://www.clover.com/oauth/v2/authorize"
CLOVER_TOKEN_URL_SANDBOX = "https://apisandbox.dev.clover.com/oauth/v2/token"
CLOVER_TOKEN_URL_PRODUCTION = "https://api.clover.com/oauth/v2/token"


def _get_authorize_url() -> str:
    """Return Clover authorize URL for current environment."""
    return (
        CLOVER_AUTHORIZE_URL_SANDBOX
        if settings.clover_environment == "sandbox"
        else CLOVER_AUTHORIZE_URL_PRODUCTION
    )


def _get_token_url() -> str:
    """Return Clover token exchange URL for current environment."""
    return (
        CLOVER_TOKEN_URL_SANDBOX
        if settings.clover_environment == "sandbox"
        else CLOVER_TOKEN_URL_PRODUCTION
    )


@router.get("/clover")
async def clover_oauth_initiate(
    hipoink_store_code: str | None = Query(
        None, description="Hipoink store code from onboarding form"
    ),
    store_name: str | None = Query(None, description="Store name from onboarding form"),
    timezone: str | None = Query(
        None, description="Timezone from onboarding form (e.g., America/New_York)"
    ),
    state: str | None = Query(None, description="State parameter for CSRF protection (optional)"),
):
    """
    Initiate Clover OAuth flow.
    Accepts Hipoink code, store name, timezone from onboarding page.
    Encodes them into state and redirects to Clover authorization page.
    """
    if not settings.clover_app_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clover Application ID not configured",
        )
    app_base = (settings.app_base_url or "").strip().rstrip("/")
    if not app_base:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backend base URL (app_base_url) not configured",
        )

    state_data = {
        "token": state or secrets.token_urlsafe(32),
        "hipoink_store_code": (hipoink_store_code or "").strip(),
        "store_name": (store_name or "").strip(),
        "timezone": (timezone or "").strip(),
    }
    state_token = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    redirect_uri = f"{app_base}/auth/clover/callback"
    authorize_url = _get_authorize_url()
    params = {
        "client_id": settings.clover_app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state_token,
    }
    auth_url = f"{authorize_url}?{urlencode(params)}"

    logger.info(
        "Initiating Clover OAuth",
        redirect_uri=redirect_uri,
        environment=settings.clover_environment,
        has_hipoink_code=bool(hipoink_store_code),
        has_store_name=bool(store_name),
        timezone=timezone,
    )
    return RedirectResponse(url=auth_url, status_code=302)


def _decode_state(state: str | None) -> tuple[str, str, str]:
    """
    Decode state query param to (hipoink_store_code, store_name, timezone).
    Returns ("", "", "") on failure.
    """
    if not state or not state.strip():
        return "", "", ""
    try:
        decoded = base64.urlsafe_b64decode(state.encode())
        data = json.loads(decoded.decode())
        return (
            (data.get("hipoink_store_code") or "").strip(),
            (data.get("store_name") or "").strip(),
            (data.get("timezone") or "").strip(),
        )
    except Exception as e:
        logger.warning("Failed to decode Clover OAuth state", error=str(e))
        return "", "", ""


@router.get("/clover/callback")
async def clover_oauth_callback(
    code: str | None = Query(None, description="Authorization code from Clover"),
    merchant_id: str | None = Query(None, description="Clover merchant ID"),
    state: str | None = Query(None, description="State parameter"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Handle Clover OAuth callback.
    Exchanges code for tokens, creates/updates store mapping, redirects to frontend success.
    """
    if not code or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )
    if not merchant_id or not merchant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing merchant_id",
        )

    hipoink_store_code, store_name, timezone = _decode_state(state)
    logger.info(
        "Clover OAuth callback received",
        merchant_id=merchant_id,
        hipoink_store_code=hipoink_store_code,
        store_name=store_name,
        timezone=timezone,
    )

    if not settings.clover_app_id or not settings.clover_app_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clover API credentials not configured",
        )

    token_url = _get_token_url()
    (settings.app_base_url or "").strip().rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    "client_id": settings.clover_app_id,
                    "client_secret": settings.clover_app_secret,
                    "code": code.strip(),
                },
                timeout=30.0,
            )
            response.raise_for_status()
            token_data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Clover token exchange failed",
            status_code=e.response.status_code,
            body=e.response.text,
            merchant_id=merchant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code for tokens",
        ) from e
    except Exception as e:
        logger.error("Clover token exchange error", error=str(e), merchant_id=merchant_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth callback failed",
        ) from e

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error(
            "No access_token in Clover token response",
            merchant_id=merchant_id,
            keys=list(token_data.keys()),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No access token in Clover response",
        )

    refresh_token = token_data.get("refresh_token", "")
    access_token_expiration = token_data.get("access_token_expiration")
    refresh_token_expiration = token_data.get("refresh_token_expiration")

    metadata = {
        "clover_access_token": access_token,
        "clover_refresh_token": refresh_token,
        "clover_access_token_expiration": access_token_expiration,
        "clover_refresh_token_expiration": refresh_token_expiration,
        "timezone": timezone or "UTC",
        "clover_merchant_id": merchant_id,
        "clover_oauth_installed_at": datetime.utcnow().isoformat(),
    }
    if store_name:
        metadata["store_name"] = store_name
    metadata = encrypt_tokens_for_storage(metadata)

    supabase_service = SupabaseService()
    existing = supabase_service.get_store_mapping("clover", merchant_id)
    mapping_id: str | None = None

    if existing:
        existing_metadata = existing.metadata or {}
        existing_metadata.update(metadata)
        supabase_service.client.table("store_mappings").update(
            {
                "metadata": existing_metadata,
                "hipoink_store_code": hipoink_store_code or existing.hipoink_store_code,
                "is_active": True,
            }
        ).eq("id", str(existing.id)).execute()
        mapping_id = str(existing.id)
        logger.info(
            "Updated Clover store mapping",
            merchant_id=merchant_id,
            mapping_id=mapping_id,
        )
    else:
        new_mapping = StoreMapping(
            source_system="clover",
            source_store_id=merchant_id,
            hipoink_store_code=hipoink_store_code,
            is_active=True,
            metadata=metadata,
        )
        created = supabase_service.create_store_mapping(new_mapping)
        mapping_id = str(created.id) if created.id else None
        logger.info(
            "Created Clover store mapping",
            merchant_id=merchant_id,
            mapping_id=mapping_id,
        )

    if mapping_id:
        try:
            mapping_uuid = UUID(mapping_id)
            background_tasks.add_task(_trigger_clover_initial_sync, mapping_uuid)
            logger.info("Clover initial sync scheduled", merchant_id=merchant_id)
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid mapping_id for Clover initial sync",
                merchant_id=merchant_id,
                error=str(e),
            )

    frontend_url = getattr(settings, "frontend_url", None) or "http://localhost:3000"
    if ":8000" in frontend_url or frontend_url.startswith("http://localhost:8000"):
        frontend_url = "http://localhost:3000"
    redirect_url = (
        f"{frontend_url}/onboarding/clover/success"
        f"?merchant_id={quote(merchant_id, safe='')}"
        f"&hipoink_store_code={quote(hipoink_store_code or 'none', safe='')}"
    )
    if store_name:
        redirect_url += f"&store_name={quote(store_name, safe='')}"

    logger.info("Redirecting to Clover success page", redirect_url=redirect_url)
    return RedirectResponse(url=redirect_url, status_code=302)


async def _trigger_clover_initial_sync(store_mapping_id: UUID | str) -> None:
    """
    Background task: run one polling sync for this Clover store so products appear quickly.
    Fetches mapping by id to avoid passing stale state.
    """
    from app.integrations.clover.adapter import CloverIntegrationAdapter

    supabase_service = SupabaseService()
    uid = store_mapping_id if isinstance(store_mapping_id, UUID) else UUID(str(store_mapping_id))
    store_mapping = supabase_service.get_store_mapping_by_id(uid)
    if not store_mapping:
        logger.warning(
            "Clover initial sync: store mapping not found", mapping_id=str(store_mapping_id)
        )
        return
    try:
        adapter = CloverIntegrationAdapter()
        # Skip token refresh: token was just issued by OAuth; only the worker should refresh
        # to avoid cross-process race with single-use Clover refresh tokens.
        await adapter.sync_products_via_polling(store_mapping, skip_token_refresh=True)
        logger.info(
            "Clover initial sync completed",
            merchant_id=store_mapping.source_store_id,
        )
    except Exception as e:
        logger.error(
            "Clover initial sync failed",
            merchant_id=store_mapping.source_store_id,
            error=str(e),
        )
