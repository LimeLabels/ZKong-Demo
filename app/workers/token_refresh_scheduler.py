"""
Scheduled job for refreshing Square and Clover OAuth tokens.
Runs daily to check and refresh expiring tokens.
"""

import asyncio

import structlog

from app.integrations.clover.token_refresh import CloverTokenRefreshService
from app.integrations.square.token_refresh import SquareTokenRefreshService
from app.models.database import StoreMapping
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()


class SquareTokenRefreshScheduler:
    """
    Scheduler that checks Square store mappings daily and refreshes expiring tokens.
    """

    def __init__(self):
        """Initialize token refresh scheduler (Square + Clover)."""
        self.supabase_service = SupabaseService()
        self.square_refresh = SquareTokenRefreshService()
        self.clover_refresh = CloverTokenRefreshService()
        self.running = False
        self.check_interval_hours = 24  # Check once per day

    async def start(self):
        """Start the token refresh scheduler loop."""
        self.running = True
        logger.info("Square token refresh scheduler started")

        while self.running:
            try:
                await self.check_and_refresh_tokens()
            except Exception as e:
                logger.error("Error in token refresh scheduler loop", error=str(e))

            # Wait before next check (24 hours)
            await asyncio.sleep(self.check_interval_hours * 3600)

    async def stop(self):
        """Stop the token refresh scheduler."""
        self.running = False
        logger.info("Square token refresh scheduler stopped")

    async def check_and_refresh_tokens(self):
        """
        Check Square and Clover store mappings and refresh expiring tokens.
        """
        try:
            await self._check_square_tokens()
            await self._check_clover_tokens()
        except Exception as e:
            logger.error("Error checking tokens for refresh", error=str(e))
            raise

    async def _check_square_tokens(self):
        """Check and refresh Square tokens."""
        store_mappings = self._get_square_store_mappings()
        if not store_mappings:
            logger.debug("No Square store mappings found")
            return

        logger.info(
            "Checking Square tokens for refresh",
            store_mapping_count=len(store_mappings),
        )
        refreshed_count = 0
        failed_count = 0
        skipped_count = 0

        for store_mapping in store_mappings:
            try:
                if self._should_refresh_square_token(store_mapping):
                    logger.info(
                        "Refreshing Square token",
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    success, _ = await self.square_refresh.refresh_token_and_update(store_mapping)
                    if success:
                        refreshed_count += 1
                    else:
                        failed_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(
                    "Error processing Square store mapping",
                    store_mapping_id=str(store_mapping.id),
                    error=str(e),
                )

        logger.info(
            "Square token refresh completed",
            total=len(store_mappings),
            refreshed=refreshed_count,
            failed=failed_count,
            skipped=skipped_count,
        )

    async def _check_clover_tokens(self):
        """Check and refresh Clover tokens (refresh body: client_id + refresh_token only)."""
        store_mappings = self._get_clover_store_mappings()
        if not store_mappings:
            logger.debug("No Clover store mappings found")
            return

        logger.info(
            "Checking Clover tokens for refresh",
            store_mapping_count=len(store_mappings),
        )
        refreshed_count = 0
        failed_count = 0
        skipped_count = 0

        for store_mapping in store_mappings:
            try:
                if self._should_refresh_clover_token(store_mapping):
                    logger.info(
                        "Refreshing Clover token",
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    success, _ = await self.clover_refresh.refresh_token_and_update(store_mapping)
                    if success:
                        refreshed_count += 1
                    else:
                        failed_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(
                    "Error processing Clover store mapping",
                    store_mapping_id=str(store_mapping.id),
                    error=str(e),
                )

        logger.info(
            "Clover token refresh completed",
            total=len(store_mappings),
            refreshed=refreshed_count,
            failed=failed_count,
            skipped=skipped_count,
        )

    def _get_clover_store_mappings(self) -> list[StoreMapping]:
        """Get active Clover store mappings that have a refresh token."""
        try:
            response = (
                self.supabase_service.client.table("store_mappings")
                .select("*")
                .eq("source_system", "clover")
                .eq("is_active", True)
                .execute()
            )
            result = []
            for row in response.data:
                try:
                    mapping = StoreMapping(**row)
                    if mapping.metadata and mapping.metadata.get("clover_refresh_token"):
                        result.append(mapping)
                except Exception as e:
                    logger.warning(
                        "Failed to parse Clover store mapping",
                        row_id=row.get("id"),
                        error=str(e),
                    )
            return result
        except Exception as e:
            logger.error("Failed to fetch Clover store mappings", error=str(e))
            return []

    def _should_refresh_clover_token(self, store_mapping: StoreMapping) -> bool:
        """True if Clover access token is expiring within 24 hours."""
        if not store_mapping.metadata:
            return False
        exp = store_mapping.metadata.get("clover_access_token_expiration")
        return self.clover_refresh.is_token_expiring_soon(exp)

    def _get_square_store_mappings(self) -> list[StoreMapping]:
        """
        Get all active Square store mappings.

        Returns:
            List of Square store mappings
        """
        try:
            # Query Supabase for Square store mappings
            response = (
                self.supabase_service.client.table("store_mappings")
                .select("*")
                .eq("source_system", "square")
                .eq("is_active", True)
                .execute()
            )

            store_mappings = []
            for row in response.data:
                try:
                    store_mapping = StoreMapping(**row)
                    # Only include mappings that have Square tokens
                    if store_mapping.metadata and store_mapping.metadata.get(
                        "square_refresh_token"
                    ):
                        store_mappings.append(store_mapping)
                except Exception as e:
                    logger.warning(
                        "Failed to parse store mapping",
                        row_id=row.get("id"),
                        error=str(e),
                    )

            return store_mappings

        except Exception as e:
            logger.error("Failed to fetch Square store mappings", error=str(e))
            return []

    def _should_refresh_square_token(self, store_mapping: StoreMapping) -> bool:
        """True if Square token should be refreshed (expiring within threshold)."""
        if not store_mapping.metadata:
            return False
        expires_at = store_mapping.metadata.get("square_expires_at")
        return self.square_refresh.is_token_expiring_soon(expires_at)


async def run_token_refresh_scheduler():
    """
    Main entry point for running the token refresh scheduler.
    Creates a SquareTokenRefreshScheduler instance and starts it.
    """
    scheduler = SquareTokenRefreshScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down token refresh scheduler")
    finally:
        await scheduler.stop()
