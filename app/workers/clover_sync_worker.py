"""
Clover polling sync worker.
Polls Clover REST API for inventory changes and syncs to DB + queue (Hipoink ESL).
Runs every N minutes (configurable). Thin wrapper around CloverIntegrationAdapter.sync_products_via_polling().
"""

import asyncio
import structlog

from app.config import settings
from app.integrations.clover.adapter import CloverIntegrationAdapter
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()


class CloverSyncWorker:
    """
    Polls Clover REST API for inventory changes.
    Runs every N minutes (configurable, default 5 minutes).
    """

    def __init__(self) -> None:
        self.adapter = CloverIntegrationAdapter()
        self.supabase_service = SupabaseService()
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("Clover sync worker started", poll_interval_seconds=getattr(settings, "clover_sync_interval_seconds", 300))

        while self.running:
            try:
                if getattr(settings, "clover_sync_enabled", True):
                    await self.poll_all_merchants()
            except Exception as e:
                logger.error("Error in Clover sync worker", error=str(e))

            interval = getattr(settings, "clover_sync_interval_seconds", 300)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self.running = False
        logger.info("Clover sync worker stopped")

    async def poll_all_merchants(self) -> None:
        """Poll all active Clover store mappings."""
        mappings = self.supabase_service.get_store_mappings_by_source_system(
            "clover"
        )

        for mapping in mappings:
            if not mapping.is_active:
                continue
            if not mapping.metadata or not mapping.metadata.get(
                "clover_access_token"
            ):
                logger.warning(
                    "No access token for Clover merchant",
                    mapping_id=str(mapping.id),
                    merchant_id=mapping.source_store_id,
                )
                continue

            try:
                results = await self.adapter.sync_products_via_polling(mapping)
                logger.info(
                    "Clover sync completed",
                    merchant_id=mapping.source_store_id,
                    items_processed=results.get("items_processed", 0),
                    items_deleted=results.get("items_deleted", 0),
                    errors=results.get("errors", []),
                )
            except Exception as e:
                logger.error(
                    "Failed to sync Clover merchant",
                    merchant_id=mapping.source_store_id,
                    error=str(e),
                    exc_info=True,
                )


async def run_clover_sync_worker() -> None:
    """Entry point: run the Clover sync worker loop."""
    worker = CloverSyncWorker()
    try:
        await worker.start()
    except asyncio.CancelledError:
        await worker.stop()
