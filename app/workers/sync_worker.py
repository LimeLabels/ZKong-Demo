"""
Background worker that processes sync queue items.
Polls Supabase sync_queue, transforms data to ZKong format, and syncs to ZKong API.
"""
import asyncio
import time
from typing import List, Dict, Any
from uuid import UUID
import structlog

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.services.zkong_client import ZKongClient, ZKongAPIError
from app.models.database import SyncQueueItem, Product, StoreMapping
from app.models.zkong import ZKongProductImportItem
from app.utils.retry import PermanentError, TransientError

logger = structlog.get_logger()


class SyncWorker:
    """Worker that processes sync queue and syncs products to ZKong."""
    
    def __init__(self):
        """Initialize sync worker."""
        self.supabase_service = SupabaseService()
        self.zkong_client = ZKongClient()
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
        await self.zkong_client.close()
        logger.info("Sync worker stopped")
    
    async def process_sync_queue(self):
        """
        Process pending items from sync queue.
        Fetches pending items, processes them, and updates status.
        """
        # Get pending queue items
        queue_items = self.supabase_service.get_pending_sync_queue_items(limit=10)
        
        if not queue_items:
            return
        
        logger.info("Processing sync queue items", count=len(queue_items))
        
        for queue_item in queue_items:
            try:
                # Mark as syncing
                self.supabase_service.update_sync_queue_status(
                    queue_item.id,  # type: ignore
                    "syncing"
                )
                
                # Process the item
                await self.process_queue_item(queue_item)
                
            except Exception as e:
                logger.error(
                    "Failed to process queue item",
                    queue_item_id=str(queue_item.id),
                    error=str(e)
                )
                # Update status to failed if max retries reached
                retry_count = queue_item.retry_count + 1
                if retry_count >= queue_item.max_retries:
                    self.supabase_service.update_sync_queue_status(
                        queue_item.id,  # type: ignore
                        "failed",
                        error_message=str(e),
                        error_details={"exception_type": type(e).__name__},
                        retry_count=retry_count
                    )
                else:
                    # Reset to pending for retry
                    self.supabase_service.update_sync_queue_status(
                        queue_item.id,  # type: ignore
                        "pending",
                        retry_count=retry_count
                    )
    
    async def process_queue_item(self, queue_item: SyncQueueItem):
        """
        Process a single sync queue item.
        
        Args:
            queue_item: SyncQueueItem to process
        """
        start_time = time.time()
        
        try:
            # Get product and store mapping
            product = self.supabase_service.get_product(queue_item.product_id)
            if not product:
                raise Exception(f"Product not found: {queue_item.product_id}")
            
            # Get store mapping by ID from queue item
            store_mapping = self.supabase_service.get_store_mapping_by_id(
                queue_item.store_mapping_id
            )
            if not store_mapping:
                raise Exception(f"Store mapping not found: {queue_item.store_mapping_id}")
            
            # Handle different operations
            if queue_item.operation == "delete":
                await self._handle_delete(product, store_mapping, queue_item)
            else:
                await self._handle_create_or_update(product, store_mapping, queue_item)
            
            # Mark as succeeded
            duration_ms = int((time.time() - start_time) * 1000)
            self.supabase_service.update_sync_queue_status(
                queue_item.id,  # type: ignore
                "succeeded"
            )
            
            # Log success
            from app.models.database import SyncLog
            log_entry = SyncLog(
                sync_queue_id=queue_item.id,
                product_id=product.id,
                store_mapping_id=store_mapping.id,
                operation=queue_item.operation,
                status="succeeded",
                duration_ms=duration_ms
            )
            self.supabase_service.create_sync_log(log_entry)
            
            logger.info(
                "Successfully synced product",
                product_id=str(product.id),
                operation=queue_item.operation,
                duration_ms=duration_ms
            )
            
        except PermanentError as e:
            # Permanent error - don't retry
            duration_ms = int((time.time() - start_time) * 1000)
            self.supabase_service.update_sync_queue_status(
                queue_item.id,  # type: ignore
                "failed",
                error_message=str(e),
                error_details={"error_type": "permanent"}
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
                duration_ms=duration_ms
            )
            self.supabase_service.create_sync_log(log_entry)
            
            raise
            
        except (TransientError, ZKongAPIError) as e:
            # Transient error - will be retried
            duration_ms = int((time.time() - start_time) * 1000)
            
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
                duration_ms=duration_ms
            )
            self.supabase_service.create_sync_log(log_entry)
            
            raise
    
    async def _handle_create_or_update(
        self,
        product: Product,
        store_mapping: StoreMapping,
        queue_item: SyncQueueItem
    ):
        """
        Handle create or update operation.
        
        Args:
            product: Product to sync
            store_mapping: Store mapping configuration
            queue_item: Queue item being processed
        """
        # Build ZKong product import item
        if not product.normalized_data:
            raise Exception("Product normalized_data is missing")
        
        normalized = product.normalized_data
        
        # Get barcode - required by ZKong
        barcode = normalized.get("barcode") or product.barcode
        if not barcode:
            raise Exception("Barcode is required for ZKong import")
        
        zkong_product = ZKongProductImportItem(
            barcode=barcode,
            merchant_id=store_mapping.zkong_merchant_id,
            store_id=store_mapping.zkong_store_id,
            product_name=normalized.get("title") or product.title,
            price=float(normalized.get("price") or product.price or 0.0),
            currency=normalized.get("currency") or product.currency or "USD",
            image_url=normalized.get("image_url") or product.image_url,
            external_id=product.source_id,
            sku=normalized.get("sku") or product.sku,
            source_system=product.source_system  # Pass source system for origin field
        )
        
        # Import to ZKong (bulk import with single item)
        response = await self.zkong_client.import_products_bulk(
            products=[zkong_product],
            merchant_id=store_mapping.zkong_merchant_id,
            store_id=store_mapping.zkong_store_id
        )
        
        # ZKong uses various success codes (200, 14014, 10000, etc.)
        # Check if the response indicates success by checking the message or code
        # "商品导入成功" means "Product import successful" in Chinese
        is_success = (
            response.code == 200 or
            response.code == 14014 or
            response.code == 10000 or
            (response.message and "成功" in str(response.message)) or  # "成功" means "success" in Chinese
            (response.message and "success" in str(response.message).lower())
        )
        
        if not is_success:
            raise ZKongAPIError(
                f"ZKong import failed: {response.message} (code: {response.code})"
            )
        
        # Log success even if code isn't 200
        if response.code != 200:
            logger.info(
                "ZKong import successful with non-200 code",
                code=response.code,
                message=response.message
            )
        
        # Extract ZKong product ID from response
        zkong_product_id = None
        if response.data:
            # Response structure may vary - check common fields
            zkong_product_id = (
                response.data.get("product_id") or
                response.data.get("id") or
                response.data.get("barcode")
            )
        
        # Store ZKong product mapping
        if zkong_product_id:
            from app.models.database import ZKongProduct
            zkong_mapping = ZKongProduct(
                product_id=product.id,  # type: ignore
                store_mapping_id=store_mapping.id,  # type: ignore
                zkong_product_id=str(zkong_product_id),
                zkong_barcode=barcode
            )
            self.supabase_service.create_or_update_zkong_product(zkong_mapping)
        
        # Upload image if available
        image_url = normalized.get("image_url") or product.image_url
        if image_url and zkong_product_id:
            try:
                await self.zkong_client.upload_product_image(
                    barcode=barcode,
                    image_url=image_url,
                    merchant_id=store_mapping.zkong_merchant_id,
                    store_id=store_mapping.zkong_store_id
                )
            except Exception as e:
                # Image upload failure shouldn't fail the whole sync
                logger.warning(
                    "Failed to upload product image",
                    product_id=str(product.id),
                    error=str(e)
                )
    
    async def _handle_delete(
        self,
        product: Product,
        store_mapping: StoreMapping,
        queue_item: SyncQueueItem
    ):
        """
        Handle delete operation.
        
        Args:
            product: Product to delete
            store_mapping: Store mapping configuration
            queue_item: Queue item being processed
        """
        # For now, deletion is a placeholder
        # ZKong API might have a delete endpoint (check API docs section 3.2)
        logger.info(
            "Delete operation requested",
            product_id=str(product.id)
        )
        # TODO: Implement ZKong product deletion if API supports it


async def run_worker():
    """Run the sync worker."""
    worker = SyncWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await worker.stop()

