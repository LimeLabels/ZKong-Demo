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
from app.services.hipoink_client import (
    HipoinkClient,
    HipoinkAPIError,
    HipoinkProductItem,
)
from app.services.slack_service import get_slack_service
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
            client_id=getattr(settings, "hipoink_client_id", "default")
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
            product = self.supabase_service.get_product(queue_item.product_id)  # type: ignore
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

            # Validate store mapping is active
            if not store_mapping.is_active:
                raise Exception(
                    f"Store mapping is not active: {store_mapping.id}"
                )

            # Validate hipoink_store_code is set
            if not store_mapping.hipoink_store_code:
                raise Exception(
                    f"Store mapping missing hipoink_store_code: {store_mapping.id}"
                )

            # Validate product source_system matches store mapping source_system
            if product.source_system != store_mapping.source_system:
                raise Exception(
                    f"Product source_system ({product.source_system}) doesn't match "
                    f"store mapping source_system ({store_mapping.source_system})"
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

            # Send Slack alert for permanent errors
            try:
                store_mapping = self.supabase_service.get_store_mapping_by_id(
                    queue_item.store_mapping_id  # type: ignore
                )
                merchant_id = store_mapping.source_store_id if store_mapping else None
                store_code = store_mapping.hipoink_store_code if store_mapping else None
                
                slack_service = get_slack_service()
                await slack_service.send_sync_failure_alert(
                    error_message=str(e),
                    product_id=str(queue_item.product_id) if queue_item.product_id else None,
                    store_mapping_id=str(queue_item.store_mapping_id) if queue_item.store_mapping_id else None,
                    operation=queue_item.operation,
                    merchant_id=merchant_id,
                    store_code=store_code,
                )
            except Exception as slack_error:
                # Don't fail sync processing if Slack fails
                logger.warning("Failed to send Slack alert", error=str(slack_error))

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
                    error_details={
                        "error_type": "transient",
                        "retry_count": retry_count,
                    },
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

                # Send Slack alert for max retries exceeded
                try:
                    store_mapping = self.supabase_service.get_store_mapping_by_id(
                        queue_item.store_mapping_id  # type: ignore
                    )
                    merchant_id = store_mapping.source_store_id if store_mapping else None
                    store_code = store_mapping.hipoink_store_code if store_mapping else None
                    
                    slack_service = get_slack_service()
                    await slack_service.send_sync_failure_alert(
                        error_message=f"Max retries exceeded: {str(e)}",
                        product_id=str(queue_item.product_id) if queue_item.product_id else None,
                        store_mapping_id=str(queue_item.store_mapping_id) if queue_item.store_mapping_id else None,
                        operation=queue_item.operation,
                        merchant_id=merchant_id,
                        store_code=store_code,
                    )
                except Exception as slack_error:
                    logger.warning("Failed to send Slack alert", error=str(slack_error))

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

        # Get base price
        base_price = float(normalized.get("price") or product.price or 0.0)
        final_price = base_price

        # f1-f4 dynamic fields: Square uses pre-calculated (weight vs per-item); Shopify uses unit/ounce logic
        f1 = None
        f2 = None
        f3 = None
        f4 = None

        if product.source_system == "square":
            # Square: use pre-calculated f1-f4 from transformer (weight vs per-item)
            f1 = normalized.get("f1")
            f2 = normalized.get("f2")
            f3 = normalized.get("f3")
            f4 = normalized.get("f4")
            # Fallback: older Square products may lack f1-f4 in normalized_data
            # Try to recalculate using transformer logic if available
            if f1 is None and f2 is None and f3 is None and f4 is None:
                raw = product.raw_data
                if isinstance(raw, dict):
                    item_data = raw.get("item_data") or {}
                    variations = item_data.get("variations") or []
                    for var in variations:
                        if str(var.get("id")) != str(product.source_variant_id):
                            continue
                        vd = var.get("item_variation_data") or {}
                        if not vd:
                            break
                        
                        # Try to extract unit cost and recalculate using transformer logic
                        from app.integrations.square.transformer import SquareTransformer
                        
                        # Get price for calculation
                        pm = vd.get("price_money") or {}
                        price_cents = pm.get("amount", 0) or 0
                        total_price = (price_cents / 100.0) if price_cents else 0.0
                        
                        # Try to extract unit cost (for Plus users)
                        catalog_object_dict = item_data  # Use item_data as catalog_object for custom attributes
                        unit_cost = SquareTransformer.extract_unit_cost(vd, catalog_object_dict)
                        
                        # Determine if weight-based or per-item
                        has_measurement_unit = bool(vd.get("measurement_unit_id"))
                        
                        # Only calculate if we have unit cost (Plus users)
                        if unit_cost and unit_cost > 0 and total_price > 0:
                            if has_measurement_unit:
                                # Weight-based: use f3 (total ounces) and f4 (price per ounce)
                                # Note: We don't have measurement_units_cache here, so we can't convert pounds
                                # For fallback, assume unit cost is already per ounce or use as-is
                                # In practice, new products will have this calculated correctly by transformer
                                unit_cost_per_ounce = unit_cost  # Assume already in ounces (or will be corrected on next sync)
                                total_ounces = total_price / unit_cost_per_ounce
                                f3 = f"{total_ounces:.2f}"  # Total ounces (numeric only)
                                f4 = f"{unit_cost_per_ounce:.2f}"  # Price per ounce (numeric only)
                            else:
                                # Per-item: use f1 (total units) and f2 (price per unit)
                                total_units = total_price / unit_cost
                                f1 = f"{total_units:.2f}"  # Total units (numeric only)
                                f2 = f"{unit_cost:.2f}"  # Price per unit (numeric only)
                        # If no unit cost (non-Plus user), leave as None - that's correct!
                        break
        else:
            # Shopify (and other sources): existing unit/ounce calculation
            unit_amount = None
            ounce_amount = None
            if product.normalized_data:
                unit_amount = product.normalized_data.get("unit_amount")
                ounce_amount = product.normalized_data.get("ounce_amount")

            if not unit_amount and product.raw_data and isinstance(product.raw_data, dict):
                variants = product.raw_data.get("variants", [])
                if variants and isinstance(variants, list):
                    variant_id = product.source_variant_id
                    for variant in variants:
                        if str(variant.get("id")) != str(variant_id):
                            continue
                        grams = variant.get("grams", 0)
                        weight = variant.get("weight", 0.0)
                        weight_unit = (variant.get("weight_unit") or "kg").lower()
                        if grams > 0:
                            ounce_amount = grams / 28.3495
                        elif weight > 0:
                            if weight_unit == "kg":
                                ounce_amount = weight * 35.274
                            elif weight_unit == "lb":
                                ounce_amount = weight * 16
                            elif weight_unit == "oz":
                                ounce_amount = weight
                        unit_amount = variant.get("inventory_quantity", 1)
                        break

            if unit_amount and unit_amount > 0:
                f1 = str(round(final_price / unit_amount, 2))
                f3 = str(unit_amount)
            if ounce_amount and ounce_amount > 0:
                f2 = str(round(final_price / ounce_amount, 2))
                f4 = str(round(ounce_amount, 2))

        # Check if product already exists in Hipoink for this store
        existing_hipoink = self.supabase_service.get_hipoink_product_by_product_id(
            product.id,  # type: ignore
            store_mapping.id,  # type: ignore
        )

        # Build Hipoink product item
        # Map Shopify fields to Hipoink API fields
        hipoink_product = HipoinkProductItem(
            product_code=barcode,  # pc - required (barcode)
            product_name=normalized.get("title") or product.title,  # pn - required
            product_price=str(
                round(final_price, 2)
            ),  # pp - required (as string, with multiplier applied)
            product_inner_code=normalized.get("sku") or product.sku,  # pi - using SKU
            product_image_url=normalized.get("image_url")
            or product.image_url,  # pim - optional
            product_qrcode_url=normalized.get("image_url")
            or product.image_url,  # pqr - optional (using image URL)
            # f1-f4 fields for pricing calculations
            f1=f1,  # price per unit
            f2=f2,  # price per ounce
            f3=f3,  # unit amount
            f4=f4,  # ounce amount
        )

        # If product already exists in Hipoink, treat as update
        if existing_hipoink:
            logger.info(
                "Product already exists in Hipoink, treating as update",
                product_id=str(product.id),
                store_mapping_id=str(store_mapping.id),
                hipoink_product_code=existing_hipoink.hipoink_product_code,
                operation=queue_item.operation,
            )
            # Update the operation to "update" if it was "create"
            # This ensures the product gets updated with latest data
            if queue_item.operation == "create":
                logger.debug(
                    "Converting create operation to update",
                    product_id=str(product.id),
                )

        # Create or update product in Hipoink (create_product handles both)
        response = await self.hipoink_client.create_product(
            store_code=store_mapping.hipoink_store_code,
            product=hipoink_product,
        )

        # Check response
        error_code = response.get("error_code")
        if error_code != 0:
            error_msg = response.get("error_msg", "Unknown error")
            raise HipoinkAPIError(
                f"Hipoink import failed: {error_msg} (code: {error_code})"
            )

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
        Deletes product from Hipoink ESL system and cleans up mapping.

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

        try:
            # Call Hipoink API to delete the product
            response = await self.hipoink_client.delete_products(
                store_code=store_mapping.hipoink_store_code,
                product_codes=[barcode],  # API expects a list
            )

            deleted_count = response.get("count", 0)
            logger.info(
                "Successfully deleted product from Hipoink",
                product_code=barcode,
                store_code=store_mapping.hipoink_store_code,
                deleted_count=deleted_count,
            )

            # Clean up the hipoink_products mapping table
            if hipoink_mapping:
                self.supabase_service.delete_hipoink_product_mapping(
                    product_id=product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                )
                logger.info(
                    "Cleaned up Hipoink product mapping",
                    product_id=str(product.id),
                )

            # Hard delete product from Supabase database
            # This removes the product completely, freeing up SKU/barcode for reuse
            deleted = self.supabase_service.delete_product(product.id)
            if deleted:
                logger.info(
                    "Hard deleted product from Supabase database",
                    product_id=str(product.id),
                    source_system=product.source_system,
                    source_id=product.source_id,
                )
            else:
                logger.warning(
                    "Failed to hard delete product from database (may not exist)",
                    product_id=str(product.id),
                )

        except HipoinkAPIError as e:
            logger.error(
                "Failed to delete product from Hipoink",
                product_code=barcode,
                store_code=store_mapping.hipoink_store_code,
                error=str(e),
            )
            raise


async def run_worker():
    """
    Main entry point for running the sync worker.
    Creates a SyncWorker instance and starts it.
    """
    worker = SyncWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down worker")
    finally:
        await worker.stop()
