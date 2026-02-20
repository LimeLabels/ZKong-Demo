"""
Clover OAuth token refresh service.
Refreshes expiring access tokens. Clover refresh endpoint uses ONLY client_id and refresh_token (no client_secret).
Includes retry logic (3 attempts with backoff) and Slack alert on final failure.
"""

import asyncio
import time
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.config import settings
from app.integrations.clover.token_encryption import (
    decrypt_tokens_from_storage,
    encrypt_tokens_for_storage,
)
from app.models.database import StoreMapping
from app.services.slack_service import get_slack_service
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

# Per-merchant refresh locks to prevent concurrent refresh attempts
# Module-level dictionary ensures all service instances share the same locks
_refresh_locks: dict[str, asyncio.Lock] = {}
_refresh_locks_lock = asyncio.Lock()  # Lock for managing the locks dict


async def _get_refresh_lock(merchant_id: str) -> asyncio.Lock:
    """
    Get or create a lock for this merchant's refresh operations.
    Ensures only one refresh happens at a time per merchant, preventing race conditions.
    """
    async with _refresh_locks_lock:
        if merchant_id not in _refresh_locks:
            _refresh_locks[merchant_id] = asyncio.Lock()
        return _refresh_locks[merchant_id]


CLOVER_REFRESH_URL_SANDBOX = "https://apisandbox.dev.clover.com/oauth/v2/refresh"
CLOVER_REFRESH_URL_PRODUCTION = "https://api.clover.com/oauth/v2/refresh"

# Refresh if access token expires within this many seconds (24 hours)
# Used by the token refresh scheduler (runs daily).
REFRESH_THRESHOLD_SECONDS = 24 * 3600

# Threshold for on-demand refresh in the adapter (before each sync).
# Refresh when token expires within 15 minutes so sync never uses an expired token.
ON_DEMAND_REFRESH_THRESHOLD_SECONDS = 15 * 60

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
    token_updates: dict[str, Any],
    supabase_service: SupabaseService,
) -> StoreMapping | None:
    """
    Atomically merge token fields into store_mappings (single DB update).
    Uses merge_store_mapping_metadata RPC when available; falls back to read-merge-write.
    Run via asyncio.to_thread to avoid blocking the event loop.
    """
    try:
        supabase_service.merge_store_mapping_metadata(store_mapping_id, token_updates)
        return supabase_service.get_store_mapping_by_id(store_mapping_id)
    except Exception as rpc_err:
        err_msg = str(rpc_err).lower()
        if "function" in err_msg and "does not exist" in err_msg:
            logger.debug(
                "merge_store_mapping_metadata RPC not found, using read-merge-write",
                store_mapping_id=str(store_mapping_id),
            )
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
                    "DB update failed in Clover token refresh",
                    store_mapping_id=str(store_mapping_id),
                    error=str(e),
                )
                return None
        logger.error(
            "DB update failed in Clover token refresh",
            store_mapping_id=str(store_mapping_id),
            error=str(rpc_err),
        )
        return None


class CloverTokenRefreshService:
    """Service for refreshing Clover OAuth tokens. Refresh body: client_id + refresh_token only."""

    def __init__(self) -> None:
        self.supabase_service = SupabaseService()

    def is_token_expiring_soon(
        self,
        expiration: Any | None,
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
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Refresh Clover OAuth token. Uses ONLY client_id and refresh_token (no client_secret).

        FIX 1: Re-fetches store mapping from DB to ensure we use the latest refresh_token,
        avoiding stale in-memory data that could cause "Invalid refresh token" errors.

        Returns:
            (success, new_token_data or None). new_token_data: access_token, refresh_token, access_token_expiration, refresh_token_expiration
        """
        if not store_mapping.id:
            logger.error(
                "Store mapping has no id, cannot refresh token",
                merchant_id=store_mapping.source_store_id,
            )
            return False, None

        # FIX 1: Re-fetch store mapping from DB to get latest refresh_token
        # This ensures we always use the most recent token, even if another process just updated it
        fresh_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping.id)
        if not fresh_mapping or not fresh_mapping.metadata:
            logger.error(
                "Could not re-fetch store mapping for refresh",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )
            return False, None

        # Logging for debugging (per Claude Code review)
        decrypted = decrypt_tokens_from_storage(fresh_mapping.metadata)
        logger.debug(
            "Re-fetched store mapping for refresh",
            store_mapping_id=str(store_mapping.id),
            merchant_id=store_mapping.source_store_id,
            has_refresh_token=bool(decrypted.get("clover_refresh_token")),
        )

        refresh_token = decrypted.get("clover_refresh_token")
        if not refresh_token:
            logger.error(
                "No Clover refresh token in fresh store mapping",
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
                        response_text=response.text[:100] if response.text else "",
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
                        merchant_id=store_mapping.source_store_id,
                    )
                    return False, None

                # FIX 2: Clover refresh tokens are single-use. We MUST get a new refresh_token.
                # If Clover doesn't return one, the old token is invalid and we can't continue.
                new_refresh_token = data.get("refresh_token")
                if not new_refresh_token:
                    logger.error(
                        "No refresh_token in Clover refresh response - old token is now invalid",
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    return False, None  # Don't fall back to old token - it's invalid!

                new_token_data = {
                    "access_token": access_token,
                    "refresh_token": new_refresh_token,  # Always use new token from response
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
    ) -> tuple[bool, StoreMapping | None]:
        """
        Refresh token and update store mapping metadata.
        Retries the Clover API call up to MAX_REFRESH_ATTEMPTS with RETRY_DELAY_SECONDS between attempts.
        Sends a Slack alert if all attempts fail.

        FIX 3: Uses per-merchant lock to prevent concurrent refresh attempts that could
        cause race conditions with single-use refresh tokens.
        """
        merchant_id = store_mapping.source_store_id
        if not merchant_id:
            logger.error(
                "Store mapping has no merchant_id, cannot refresh token",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None

        # FIX 3: Acquire merchant-specific lock to prevent concurrent refreshes
        # Only one refresh can happen at a time for this merchant
        lock = await _get_refresh_lock(merchant_id)

        async with lock:
            last_error: str | None = None
            new_token_data: dict[str, Any] | None = None

            # Re-fetch store mapping inside the lock to get latest refresh_token from DB
            # This ensures we have the absolute latest token even if another process just updated it
            fresh_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping.id)
            if not fresh_mapping:
                logger.error(
                    "Could not fetch fresh store mapping for refresh",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=merchant_id,
                )
                return False, None

            # Rate-limit: do not call Clover if we attempted refresh too recently
            min_interval = getattr(settings, "clover_refresh_min_interval_seconds", 30)
            last_attempt = (fresh_mapping.metadata or {}).get("clover_last_refresh_attempt_at")
            if last_attempt is not None:
                try:
                    ts = float(last_attempt) if isinstance(last_attempt, int | float) else None
                    if ts is None and isinstance(last_attempt, str):
                        from datetime import datetime

                        dt = datetime.fromisoformat(last_attempt.replace("Z", "+00:00"))
                        ts = dt.timestamp()
                    if ts is not None and (time.time() - ts) < min_interval:
                        logger.debug(
                            "Clover refresh skipped, within min interval",
                            merchant_id=merchant_id,
                            store_mapping_id=str(store_mapping.id),
                            seconds_since_last=time.time() - ts,
                        )
                        return False, None
                except (TypeError, ValueError):
                    pass

            # Use fresh mapping for refresh attempts
            for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
                success, new_token_data = await self.refresh_token(fresh_mapping)
                if success and new_token_data:
                    break
                last_error = "Refresh returned no token data"
                if attempt < MAX_REFRESH_ATTEMPTS:
                    logger.warning(
                        "Clover token refresh attempt failed, retrying",
                        attempt=attempt,
                        max_attempts=MAX_REFRESH_ATTEMPTS,
                        merchant_id=merchant_id,
                        store_mapping_id=str(store_mapping.id),
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    # Re-fetch again before retry to get any updates
                    retry_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping.id)
                    if not retry_mapping:
                        logger.error(
                            "Could not re-fetch store mapping before retry",
                            store_mapping_id=str(store_mapping.id),
                            merchant_id=merchant_id,
                        )
                        # Continue with existing fresh_mapping if re-fetch fails
                        break
                    fresh_mapping = retry_mapping

            if not new_token_data:
                logger.error(
                    "Clover token refresh failed after all retries",
                    merchant_id=merchant_id,
                    store_mapping_id=str(store_mapping.id),
                    attempts=MAX_REFRESH_ATTEMPTS,
                )
                # Persist last attempt time so we don't hammer Clover on next request
                if fresh_mapping and fresh_mapping.id:
                    try:
                        await asyncio.to_thread(
                            self.supabase_service.merge_store_mapping_metadata,
                            fresh_mapping.id,
                            {"clover_last_refresh_attempt_at": time.time()},
                        )
                    except Exception:
                        pass
                alert_mapping = fresh_mapping if fresh_mapping else store_mapping
                await self._send_refresh_failure_alert(
                    alert_mapping, last_error or "All refresh attempts failed"
                )
                return False, None

            if not fresh_mapping.id:
                logger.error(
                    "Clover store mapping has no id, cannot persist tokens",
                    merchant_id=merchant_id,
                )
                await self._send_refresh_failure_alert(
                    fresh_mapping,
                    "Store mapping has no id; cannot update metadata.",
                )
                return False, None

            token_updates = {
                "clover_access_token": new_token_data["access_token"],
                "clover_refresh_token": new_token_data["refresh_token"],
                "clover_access_token_expiration": new_token_data.get("access_token_expiration"),
                "clover_refresh_token_expiration": new_token_data.get("refresh_token_expiration"),
                "clover_last_refresh_attempt_at": time.time(),
            }
            token_updates = encrypt_tokens_for_storage(token_updates)

            try:
                updated = await asyncio.to_thread(
                    _update_store_mapping_metadata_sync,
                    fresh_mapping.id,
                    token_updates,
                    self.supabase_service,
                )
                if updated:
                    logger.info(
                        "Clover store mapping updated with new token",
                        store_mapping_id=str(fresh_mapping.id),
                        merchant_id=merchant_id,
                    )
                    return True, updated
                logger.error(
                    "Clover token refresh: DB update returned None",
                    store_mapping_id=str(fresh_mapping.id),
                    merchant_id=merchant_id,
                )
                await self._send_refresh_failure_alert(
                    fresh_mapping,
                    "Refresh succeeded but DB update failed; merchant may need to re-authorize.",
                )
                return False, None
            except Exception as e:
                logger.error(
                    "Failed to update store mapping with new Clover token",
                    store_mapping_id=str(fresh_mapping.id),
                    merchant_id=merchant_id,
                    error=str(e),
                )
                await self._send_refresh_failure_alert(
                    fresh_mapping,
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
