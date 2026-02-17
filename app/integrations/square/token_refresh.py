"""
Square OAuth token refresh service.
Handles automatic refresh of expiring access tokens.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.config import settings
from app.models.database import StoreMapping
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()


def _update_store_mapping_metadata_sync(
    store_mapping_id: UUID,
    token_updates: dict[str, Any],
    supabase_service: SupabaseService,
) -> StoreMapping | None:
    """
    Synchronous helper: re-fetch current metadata, merge token fields, write back.
    Run via asyncio.to_thread to avoid blocking the event loop.
    Re-fetching before write reduces the race window where we might overwrite
    concurrent changes to other metadata keys (e.g. store name, timezone).
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
        supabase_service.client.table("store_mappings").update({"metadata": current}).eq(
            "id", str(store_mapping_id)
        ).execute()
        return supabase_service.get_store_mapping_by_id(store_mapping_id)
    except Exception as e:
        logger.error(
            "DB update failed in token refresh",
            store_mapping_id=str(store_mapping_id),
            error=str(e),
        )
        return None


class SquareTokenRefreshService:
    """Service for refreshing Square OAuth tokens."""

    def __init__(self):
        """Initialize token refresh service."""
        self.supabase_service = SupabaseService()
        self.refresh_threshold_days = 7  # Refresh if less than 7 days remaining

    def is_token_expiring_soon(
        self, expires_at: str | None, threshold_days: int | None = None
    ) -> bool:
        """
        Check if token is expiring within the threshold period.

        Args:
            expires_at: ISO timestamp string of token expiration
            threshold_days: Days before expiration to trigger refresh (default: 7)

        Returns:
            True if token expires within threshold, False otherwise
        """
        if not expires_at:
            # If no expiration date, assume expired (should refresh)
            logger.warning("No expiration date found for token, assuming expired")
            return True

        threshold = threshold_days or self.refresh_threshold_days

        try:
            # Robust ISO 8601 parsing. Square uses strings like "2024-01-15T12:00:00Z".
            # Normalize "Z" to "+00:00" for fromisoformat (Python < 3.11 needs this).
            expires_str = expires_at.strip()
            if expires_str.upper().endswith("Z"):
                expires_str = expires_str[:-1] + "+00:00"

            expires_dt = datetime.fromisoformat(expires_str)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=UTC)
            else:
                expires_dt = expires_dt.astimezone(UTC)

            now = datetime.now(UTC)
            # Use total_seconds() for fractional days instead of .days (which truncates)
            days_until_expiry = (expires_dt - now).total_seconds() / 86400.0
            is_expiring = days_until_expiry < threshold

            logger.debug(
                "Token expiration check",
                expires_at=expires_at,
                days_until_expiry=round(days_until_expiry, 2),
                threshold_days=threshold,
                is_expiring=is_expiring,
            )
            return is_expiring
        except Exception as e:
            logger.error(
                "Error parsing expiration date, assuming expired",
                expires_at=expires_at,
                error=str(e),
            )
            return True  # Assume expired if we can't parse

    async def refresh_token(
        self, store_mapping: StoreMapping
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Refresh Square OAuth token for a store mapping.

        Args:
            store_mapping: Store mapping with Square tokens in metadata

        Returns:
            Tuple of (success: bool, new_token_data: Optional[Dict])
            new_token_data contains: access_token, refresh_token, expires_at
        """
        if not store_mapping.metadata:
            logger.warning(
                "Store mapping has no metadata",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None

        refresh_token = store_mapping.metadata.get("square_refresh_token")
        if not refresh_token:
            logger.error(
                "No refresh token found in store mapping",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )
            return False, None

        square_application_id = settings.square_application_id
        square_application_secret = settings.square_application_secret

        if not square_application_id or not square_application_secret:
            logger.error("Square application credentials not configured")
            return False, None

        # Determine Square API base URL
        if settings.square_environment == "sandbox":
            base_url = "https://connect.squareupsandbox.com"
        else:
            base_url = "https://connect.squareup.com"

        token_url = f"{base_url}/oauth2/token"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    json={
                        "client_id": square_application_id,
                        "client_secret": square_application_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.error(
                        "Square token refresh failed",
                        status_code=response.status_code,
                        response_text=response.text,
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    return False, None

                token_data = response.json()

                access_token = token_data.get("access_token")
                new_refresh_token = token_data.get("refresh_token")
                expires_at = token_data.get("expires_at")

                if not access_token:
                    logger.error(
                        "No access token in refresh response",
                        store_mapping_id=str(store_mapping.id),
                    )
                    return False, None

                # Return new token data
                new_token_data = {
                    "access_token": access_token,
                    "refresh_token": new_refresh_token
                    or refresh_token,  # Use new if provided, else keep old
                    "expires_at": expires_at,
                }

                logger.info(
                    "Square token refreshed successfully",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=store_mapping.source_store_id,
                    expires_at=expires_at,
                )

                return True, new_token_data

        except httpx.TimeoutException:
            logger.error(
                "Timeout refreshing Square token",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None
        except Exception as e:
            logger.error(
                "Error refreshing Square token",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None

    async def refresh_token_and_update(
        self, store_mapping: StoreMapping
    ) -> tuple[bool, StoreMapping | None]:
        """
        Refresh token and update store mapping metadata.

        DB update runs in a thread pool via asyncio.to_thread so the sync Supabase
        client does not block the event loop. We re-fetch metadata right before
        writing to reduce overwriting concurrent changes to other metadata keys.

        Args:
            store_mapping: Store mapping to refresh token for

        Returns:
            Tuple of (success: bool, updated_store_mapping: Optional[StoreMapping])
        """
        success, new_token_data = await self.refresh_token(store_mapping)
        if not success or not new_token_data:
            return False, None

        token_updates = {
            "square_access_token": new_token_data["access_token"],
            "square_refresh_token": new_token_data["refresh_token"],
            "square_expires_at": new_token_data["expires_at"],
            "square_token_refreshed_at": datetime.now(UTC).isoformat(),
        }

        try:
            # Run sync Supabase calls in a thread to avoid blocking the event loop.
            # Helper re-fetches current metadata, merges token_updates, then writes.
            updated_mapping = await asyncio.to_thread(
                _update_store_mapping_metadata_sync,
                store_mapping.id,
                token_updates,
                self.supabase_service,
            )
            if updated_mapping:
                logger.info(
                    "Store mapping updated with new token",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=store_mapping.source_store_id,
                )
                return True, updated_mapping
            return False, None
        except Exception as e:
            logger.error(
                "Failed to update store mapping with new token",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
            )
            return False, None

    def get_access_token(
        self, store_mapping: StoreMapping, auto_refresh: bool = True
    ) -> str | None:
        """
        Get access token from store mapping, optionally checking if expiring.

        Note: This is a synchronous method. For actual refresh, use async methods.

        Args:
            store_mapping: Store mapping with tokens
            auto_refresh: If True, log warning if token is expiring (actual refresh is async)

        Returns:
            Access token string or None if not available
        """
        if not store_mapping.metadata:
            return None

        access_token = store_mapping.metadata.get("square_access_token")
        expires_at = store_mapping.metadata.get("square_expires_at")

        if not access_token:
            return None

        # Check if token is expiring soon (for logging only - actual refresh is async)
        if auto_refresh and self.is_token_expiring_soon(expires_at):
            logger.warning(
                "Token is expiring soon - should be refreshed by scheduler or adapter",
                store_mapping_id=str(store_mapping.id),
                expires_at=expires_at,
            )

        return access_token
