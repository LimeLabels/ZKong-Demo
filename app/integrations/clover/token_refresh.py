"""
Clover OAuth token refresh service.
Refreshes expiring access tokens. Clover refresh endpoint uses ONLY client_id and refresh_token (no client_secret).
Includes retry logic (3 attempts with backoff) and Slack alert on final failure.
"""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

import httpx
import structlog
from uuid import UUID

from app.config import settings
from app.models.database import StoreMapping
from app.services.supabase_service import SupabaseService
from app.services.slack_service import get_slack_service

logger = structlog.get_logger()

CLOVER_REFRESH_URL_SANDBOX = "https://apisandbox.dev.clover.com/oauth/v2/refresh"
CLOVER_REFRESH_URL_PRODUCTION = "https://api.clover.com/oauth/v2/refresh"

# Refresh if access token expires within this many seconds (24 hours)
REFRESH_THRESHOLD_SECONDS = 24 * 3600

# Retry: max attempts and delay between attempts (seconds)
MAX_REFRESH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 60


def _get_refresh_url() -> str:
    return (
        CLOVER_REFRESH_URL_SANDBOX
        if settings.clover_environment == "sandbox"
        else CLOVER_REFRESH_URL_PRODUCTION
    )


def _update_store_mapping_metadata_sync(
    store_mapping_id: UUID,
    token_updates: Dict[str, Any],
    supabase_service: SupabaseService,
) -> Optional[StoreMapping]:
    """
    Re-fetch current metadata, merge token fields, write back.
    Run via asyncio.to_thread to avoid blocking the event loop.
    """
    try:
        row = (
            supabase_service.client.table("store_mappings")
            .select("metadata")
            .eq("id", str(store_mapping_id))
            .execute()
        )
        if not row.data or len(row.data) == 0:
            return None
        current = (row.data[0].get("metadata") or {}).copy()
        current.update(token_updates)
        supabase_service.client.table("store_mappings").update(
            {"metadata": current}
        ).eq("id", str(store_mapping_id)).execute()
        return supabase_service.get_store_mapping_by_id(store_mapping_id)
    except Exception as e:
        logger.error(
            "DB update failed in Clover token refresh",
            store_mapping_id=str(store_mapping_id),
            error=str(e),
        )
        return None


class CloverTokenRefreshService:
    """Service for refreshing Clover OAuth tokens. Refresh body: client_id + refresh_token only."""

    def __init__(self) -> None:
        self.supabase_service = SupabaseService()

    def is_token_expiring_soon(
        self,
        expiration: Optional[Any],
        threshold_seconds: int = REFRESH_THRESHOLD_SECONDS,
    ) -> bool:
        """
        Check if Clover access token is expiring within threshold.
        Clover returns Unix timestamp (seconds or milliseconds).

        Returns:
            True if token expires within threshold or expiration is missing/invalid.
        """
        if expiration is None:
            logger.warning("No Clover access token expiration in metadata, assuming expiring")
            return True
        try:
            now = time.time()
            ts = float(expiration)
            if ts > 1e12:
                ts = ts / 1000.0
            seconds_until = ts - now
            return seconds_until < threshold_seconds
        except (TypeError, ValueError) as e:
            logger.warning("Invalid Clover expiration value", expiration=expiration, error=str(e))
            return True

    async def refresh_token(
        self, store_mapping: StoreMapping
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Refresh Clover OAuth token. Uses ONLY client_id and refresh_token (no client_secret).

        Returns:
            (success, new_token_data or None). new_token_data: access_token, refresh_token, access_token_expiration, refresh_token_expiration
        """
        if not store_mapping.metadata:
            logger.warning(
                "Store mapping has no metadata",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None

        refresh_token = store_mapping.metadata.get("clover_refresh_token")
        if not refresh_token:
            logger.error(
                "No Clover refresh token in store mapping",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )
            return False, None

        if not settings.clover_app_id:
            logger.error("Clover app_id not configured")
            return False, None

        refresh_url = _get_refresh_url()
        # Critical: body has ONLY client_id and refresh_token (no client_secret)
        body = {
            "client_id": settings.clover_app_id,
            "refresh_token": refresh_token,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    refresh_url,
                    json=body,
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.error(
                        "Clover token refresh failed",
                        status_code=response.status_code,
                        response_text=response.text,
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    return False, None

                data = response.json()
                access_token = data.get("access_token")
                if not access_token:
                    logger.error(
                        "No access_token in Clover refresh response",
                        store_mapping_id=str(store_mapping.id),
                    )
                    return False, None

                new_token_data = {
                    "access_token": access_token,
                    "refresh_token": data.get("refresh_token") or refresh_token,
                    "access_token_expiration": data.get("access_token_expiration"),
                    "refresh_token_expiration": data.get("refresh_token_expiration"),
                }
                logger.info(
                    "Clover token refreshed",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=store_mapping.source_store_id,
                )
                return True, new_token_data

        except httpx.TimeoutException:
            logger.error(
                "Timeout refreshing Clover token",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None
        except Exception as e:
            logger.error(
                "Error refreshing Clover token",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None

    async def refresh_token_and_update(
        self, store_mapping: StoreMapping
    ) -> Tuple[bool, Optional[StoreMapping]]:
        """
        Refresh token and update store mapping metadata.
        Retries the Clover API call up to MAX_REFRESH_ATTEMPTS with RETRY_DELAY_SECONDS between attempts.
        Sends a Slack alert if all attempts fail.
        """
        last_error: Optional[str] = None
        new_token_data: Optional[Dict[str, Any]] = None

        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            success, new_token_data = await self.refresh_token(store_mapping)
            if success and new_token_data:
                break
            last_error = "Refresh returned no token data"
            if attempt < MAX_REFRESH_ATTEMPTS:
                logger.warning(
                    "Clover token refresh attempt failed, retrying",
                    attempt=attempt,
                    max_attempts=MAX_REFRESH_ATTEMPTS,
                    merchant_id=store_mapping.source_store_id,
                    store_mapping_id=str(store_mapping.id),
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)

        if not new_token_data:
            logger.error(
                "Clover token refresh failed after all retries",
                merchant_id=store_mapping.source_store_id,
                store_mapping_id=str(store_mapping.id),
                attempts=MAX_REFRESH_ATTEMPTS,
            )
            await self._send_refresh_failure_alert(store_mapping, last_error or "All refresh attempts failed")
            return False, None

        if not store_mapping.id:
            logger.error(
                "Clover store mapping has no id, cannot persist tokens",
                merchant_id=store_mapping.source_store_id,
            )
            await self._send_refresh_failure_alert(
                store_mapping,
                "Store mapping has no id; cannot update metadata.",
            )
            return False, None

        token_updates = {
            "clover_access_token": new_token_data["access_token"],
            "clover_refresh_token": new_token_data["refresh_token"],
            "clover_access_token_expiration": new_token_data.get("access_token_expiration"),
            "clover_refresh_token_expiration": new_token_data.get("refresh_token_expiration"),
        }

        try:
            updated = await asyncio.to_thread(
                _update_store_mapping_metadata_sync,
                store_mapping.id,
                token_updates,
                self.supabase_service,
            )
            if updated:
                logger.info(
                    "Clover store mapping updated with new token",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=store_mapping.source_store_id,
                )
                return True, updated
            logger.error(
                "Clover token refresh: DB update returned None",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )
            await self._send_refresh_failure_alert(
                store_mapping,
                "Refresh succeeded but DB update failed; merchant may need to re-authorize.",
            )
            return False, None
        except Exception as e:
            logger.error(
                "Failed to update store mapping with new Clover token",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
                error=str(e),
            )
            await self._send_refresh_failure_alert(
                store_mapping,
                f"DB update raised: {e!s}. Merchant may need to re-authorize.",
            )
            return False, None

    async def _send_refresh_failure_alert(
        self, store_mapping: StoreMapping, error_message: str
    ) -> None:
        """Send Slack alert when token refresh fails after all retries. Swallows errors so refresh flow is not blocked."""
        try:
            slack = get_slack_service()
            await slack.send_api_error_alert(
                error_message=error_message,
                api_name="clover",
                merchant_id=store_mapping.source_store_id,
                store_code=store_mapping.hipoink_store_code,
            )
        except Exception as slack_err:
            logger.warning(
                "Failed to send Clover token refresh failure alert to Slack",
                error=str(slack_err),
                merchant_id=store_mapping.source_store_id,
            )
