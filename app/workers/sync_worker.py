"""
Background worker that processes sync queue items.
Polls Supabase sync_queue, transforms data to Hipoink format, and syncs to Hipoink ESL API.
"""

import asyncio
import time
import structlog
from typing import Optional

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.services.hipoink_client import HipoinkClient, HipoinkAPIError, HipoinkProductItem
from app.models.database import SyncQueueItem, Product, StoreMapping
from app.utils.retry import PermanentError, TransientError

logger = structlog.get_logger()


class SyncWorker:
    """
    Worker that processes sync queue and syncs products to Hipoink ESL system.
    """

    def __init__(self):
        """Initialize sync worker."""
        self.supabase_service = SupabaseService()
        self.hipoink_client = HipoinkClient(
            client_id=getattr(settings, 'hipoink_client_id', 'default')
        )
        self.running = False

    async def start(self):
        """Start the sync worker loop."""
        self.running = True
        logger.info("Sync worker started")

        while self.running:
            try:
                await self.process_sync_queue()
            except Exception as e:
                logger.error("Error in sync worker loop", error=str(e))

            # Wait before next poll
            await asyncio.sleep(settings.sync_worker_interval_seconds)

    async def stop(self):
        """Stop the sync worker."""
        self.running = False
        await self.hipoink_client.close()
        logger.info("Sync worker stopped")

    async def process_sync_queue(self):
        """
        Process pending items in sync queue.
        Fetches items with status 'pending' and processes them.
        """
        try:
            # Get pending queue items
            queue_items = self.supabase_service.get_pending_sync_queue_items(
                limit=10  # Process up to 10 items at a time
            )

            if not queue_items:
                return  # No items to process

            logger.info("Processing sync queue", item_count=len(queue_items))

            # Process each item
            for queue_item in queue_items:
                try:
                    await self.process_queue_item(queue_item)
                except Exception as e:
                    logger.error(
                        "Failed to process queue item",
                        queue_item_id=str(queue_item.id),
                        error=str(e),
                    )

        except Exception as e:
            logger.error("Error processing sync queue", error=str(e))

    async def process_queue_item(self, queue_item: SyncQueueItem):
        """
        Process a single sync queue item.

        Args:
            queue_item: Queue item to process
        """
        start_time = time.time()

        try:
            # Mark as syncing
            self.supabase_service.update_sync_queue_status(
                queue_item.id,  # type: ignore
                "syncing",
            )

            # Get product
            product = self.supabase_service.get_product_by_id(queue_item.product_id)  # type: ignore
            if not product:
                raise Exception(f"Product not found: {queue_item.product_id}")

            # Get store mapping
            store_mapping = self.supabase_service.get_store_mapping_by_id(
                queue_item.store_mapping_id  # type: ignore
            )
            if not store_mapping:
                raise Exception(
                    f"Store mapping not found: {queue_item.store_mapping_id}"
                )

            # Handle different operations
            hipoink_product_code = None
            if queue_item.operation == "delete":
                await self._handle_delete(product, store_mapping, queue_item)
            else:
                hipoink_product_code = await self._handle_create_or_update(
                    product, store_mapping, queue_item
                )

            # Mark as succeeded
            duration_ms = int((time.time() - start_time) * 1000)
            self.supabase_service.update_sync_queue_status(
                queue_item.id,  # type: ignore
                "succeeded",
            )

            # Log success
            from app.models.database import SyncLog

            log_entry = SyncLog(
                sync_queue_id=queue_item.id,
                product_id=product.id,
                store_mapping_id=store_mapping.id,
                operation=queue_item.operation,
                status="succeeded",
                hipoink_product_code=hipoink_product_code,
                duration_ms=duration_ms,
            )
            self.supabase_service.create_sync_log(log_entry)

            logger.info(
                "Successfully synced product",
                product_id=str(product.id),
                operation=queue_item.operation,
                duration_ms=duration_ms,
            )

        except PermanentError as e:
            # Permanent error - don't retry
            duration_ms = int((time.time() - start_time) * 1000)
            self.supabase_service.update_sync_queue_status(
                queue_item.id,  # type: ignore
                "failed",
                error_message=str(e),
                error_details={"error_type": "permanent"},
            )

            # Log failure
            from app.models.database import SyncLog

            log_entry = SyncLog(
                sync_queue_id=queue_item.id,
                product_id=queue_item.product_id,
                store_mapping_id=queue_item.store_mapping_id,
                operation=queue_item.operation,
                status="failed",
                error_message=str(e),
                error_code="PERMANENT_ERROR",
                duration_ms=duration_ms,
            )
            self.supabase_service.create_sync_log(log_entry)

            raise

        except (TransientError, HipoinkAPIError) as e:
            # Transient error - will be retried
            duration_ms = int((time.time() - start_time) * 1000)

            # Increment retry count
            retry_count = queue_item.retry_count + 1
            if retry_count >= queue_item.max_retries:
                # Max retries reached - mark as failed
                self.supabase_service.update_sync_queue_status(
                    queue_item.id,  # type: ignore
                    "failed",
                    error_message=str(e),
                    error_details={"error_type": "transient", "retry_count": retry_count},
                )

                # Log failure
                from app.models.database import SyncLog

                log_entry = SyncLog(
                    sync_queue_id=queue_item.id,
                    product_id=queue_item.product_id,
                    store_mapping_id=queue_item.store_mapping_id,
                    operation=queue_item.operation,
                    status="failed",
                    error_message=str(e),
                    error_code="MAX_RETRIES_EXCEEDED",
                    duration_ms=duration_ms,
                )
                self.supabase_service.create_sync_log(log_entry)

                raise PermanentError(f"Max retries exceeded: {str(e)}")
            else:
                # Update retry count and reschedule
                self.supabase_service.update_sync_queue_status(
                    queue_item.id,  # type: ignore
                    "pending",
                    retry_count=retry_count,
                )

                # Log attempt
                from app.models.database import SyncLog

                log_entry = SyncLog(
                    sync_queue_id=queue_item.id,
                    product_id=queue_item.product_id,
                    store_mapping_id=queue_item.store_mapping_id,
                    operation=queue_item.operation,
                    status="failed",
                    error_message=str(e),
                    error_code="TRANSIENT_ERROR",
                    duration_ms=duration_ms,
                )
                self.supabase_service.create_sync_log(log_entry)

            raise

    async def _handle_create_or_update(
        self, product: Product, store_mapping: StoreMapping, queue_item: SyncQueueItem
    ) -> Optional[str]:
        """
        Handle create or update operation.
        Syncs product to Hipoink ESL system.

        Args:
            product: Product to sync
            store_mapping: Store mapping configuration
            queue_item: Queue item being processed
            
        Returns:
            Hipoink product code (pc) if successful
        """
        if not product.normalized_data:
            raise Exception("Product normalized_data is missing")

        normalized = product.normalized_data

        # Get barcode - required for Hipoink (used as product code)
        barcode = normalized.get("barcode") or product.barcode
        if not barcode:
            raise Exception("Barcode is required for Hipoink import")

        # Build Hipoink product item
        # Map Shopify fields to Hipoink API fields
        hipoink_product = HipoinkProductItem(
            product_code=barcode,  # pc - required (barcode)
            product_name=normalized.get("title") or product.title,  # pn - required
            product_price=str(normalized.get("price") or product.price or 0.0),  # pp - required (as string)
            product_inner_code=normalized.get("sku") or product.sku,  # pi - optional (using SKU)
            product_image_url=normalized.get("image_url") or product.image_url,  # pim - optional
            product_qrcode_url=normalized.get("image_url") or product.image_url,  # pqr - optional (using image URL)
            # Add source system to a custom field if needed
            f1=product.source_system,  # Store source system in f1
        )

        # Create product in Hipoink
        response = await self.hipoink_client.create_product(
            store_code=store_mapping.hipoink_store_code,
            product=hipoink_product,
        )

        # Check response
        error_code = response.get("error_code")
        if error_code != 0:
            error_msg = response.get("error_msg", "Unknown error")
            raise HipoinkAPIError(f"Hipoink import failed: {error_msg} (code: {error_code})")

        logger.info(
            "Hipoink product created/updated successfully",
            product_code=barcode,
            store_code=store_mapping.hipoink_store_code,
        )

        # Store Hipoink product mapping
        from app.models.database import HipoinkProduct

        hipoink_mapping = HipoinkProduct(
            product_id=product.id,  # type: ignore
            store_mapping_id=store_mapping.id,  # type: ignore
            hipoink_product_code=barcode,
        )
        self.supabase_service.create_or_update_hipoink_product(hipoink_mapping)

        return barcode

    async def _handle_delete(
        self, product: Product, store_mapping: StoreMapping, queue_item: SyncQueueItem
    ):
        """
        Handle delete operation.
        Note: Hipoink API may not have a delete endpoint - implement when available.

        Args:
            product: Product to delete
            store_mapping: Store mapping configuration
            queue_item: Queue item being processed
        """
        # Get product code for deletion
        barcode = None
        hipoink_mapping = self.supabase_service.get_hipoink_product_by_product_id(
            product.id,  # type: ignore
            store_mapping.id,  # type: ignore
        )

        if hipoink_mapping:
            barcode = hipoink_mapping.hipoink_product_code

        # Fallback to product fields if no mapping
        if not barcode:
            if product.normalized_data:
                barcode = product.normalized_data.get("barcode")
            if not barcode:
                barcode = product.barcode

        if not barcode:
            logger.warning(
                "Cannot delete product - no barcode found",
                product_id=str(product.id),
            )
            return

        # TODO: Implement Hipoink product delete when API endpoint is available
        logger.warning(
            "Hipoink product delete not yet implemented",
            product_code=barcode,
            store_code=store_mapping.hipoink_store_code,
        )
