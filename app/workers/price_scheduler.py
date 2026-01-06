import asyncio
import structlog
import pytz
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.services.hipoink_client import (
    HipoinkClient,
    HipoinkAPIError,
    HipoinkProductItem,
)
from app.models.database import PriceAdjustmentSchedule, StoreMapping

logger = structlog.get_logger()


def get_store_timezone(store_mapping: StoreMapping) -> pytz.BaseTzInfo:
    """
    Get timezone for a store mapping.
    Checks metadata for 'timezone' field, defaults to UTC if not found.

    Args:
        store_mapping: Store mapping object

    Returns:
        pytz timezone object
    """
    if store_mapping.metadata and "timezone" in store_mapping.metadata:
        try:
            return pytz.timezone(store_mapping.metadata["timezone"])
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(
                "Unknown timezone in store mapping, using UTC",
                timezone=store_mapping.metadata["timezone"],
                store_mapping_id=str(store_mapping.id),
            )
    # Default to UTC if no timezone specified
    return pytz.UTC


logger = structlog.get_logger()


class PriceScheduler:
    """
    Worker that processes price adjustment schedules and applies price changes.
    """

    def __init__(self):
        """Initialize price scheduler."""
        self.supabase_service = SupabaseService()
        self.hipoink_client = HipoinkClient(
            client_id=getattr(settings, "hipoink_client_id", "default")
        )
        self.running = False
        self.check_interval_seconds = 60  # Check every minute

    async def start(self):
        """Start the price scheduler loop."""
        self.running = True
        logger.info("Price scheduler started")

        while self.running:
            try:
                await self.process_schedules()
            except Exception as e:
                logger.error("Error in price scheduler loop", error=str(e))

            # Wait before next check
            await asyncio.sleep(self.check_interval_seconds)

    async def stop(self):
        """Stop the price scheduler."""
        self.running = False
        await self.hipoink_client.close()
        logger.info("Price scheduler stopped")

    async def process_schedules(self):
        """
        Process schedules that are due to trigger.
        Checks for schedules where next_trigger_at <= current_time.
        """
        try:
            # Get schedules due for trigger (stored in UTC)
            current_time_utc = datetime.now(pytz.UTC)
            schedules = self.supabase_service.get_schedules_due_for_trigger(
                current_time_utc
            )

            if not schedules:
                return  # No schedules to process

            logger.info(
                "Processing price adjustment schedules",
                schedule_count=len(schedules),
            )

            # Process each schedule
            for schedule in schedules:
                try:
                    await self.process_schedule(schedule, current_time_utc)
                except Exception as e:
                    logger.error(
                        "Failed to process schedule",
                        schedule_id=str(schedule.id),
                        error=str(e),
                    )

        except Exception as e:
            logger.error("Error processing schedules", error=str(e))

    async def process_schedule(
        self, schedule: PriceAdjustmentSchedule, current_time_utc: datetime
    ):
        """
        Process a single schedule - apply price changes and calculate next trigger.

        Args:
            schedule: Schedule to process
            current_time_utc: Current datetime in UTC
        """
        try:
            # Get store mapping
            store_mapping = self.supabase_service.get_store_mapping_by_id(
                schedule.store_mapping_id  # type: ignore
            )
            if not store_mapping:
                logger.error(
                    "Store mapping not found for schedule",
                    schedule_id=str(schedule.id),
                    store_mapping_id=str(schedule.store_mapping_id),
                )
                return

            # Get store timezone
            store_timezone = get_store_timezone(store_mapping)

            # Convert current time to store timezone
            current_time = current_time_utc.astimezone(store_timezone)

            # Check if we're in a time slot
            in_time_slot, is_start = self._check_time_slot(
                schedule, current_time, store_timezone
            )

            if not in_time_slot:
                # Not in a time slot - calculate next trigger and skip
                next_trigger = self._calculate_next_trigger(
                    schedule, current_time, store_timezone
                )
                # Convert to UTC for storage
                next_trigger_utc = (
                    next_trigger.astimezone(pytz.UTC) if next_trigger else None
                )
                self._update_schedule_next_trigger(schedule, next_trigger_utc)
                return

            # Get products from schedule
            products_data = schedule.products.get("products", [])
            if not products_data:
                logger.warning(
                    "Schedule has no products",
                    schedule_id=str(schedule.id),
                )
                return

            # Determine if we should apply promotional price or restore original
            if is_start:
                # Apply promotional prices
                await self._apply_promotional_prices(
                    schedule, store_mapping, products_data
                )
            else:
                # Restore original prices (end of time slot)
                await self._restore_original_prices(
                    schedule, store_mapping, products_data
                )

            # Calculate next trigger time (returns in store timezone)
            next_trigger = self._calculate_next_trigger(
                schedule, current_time, store_timezone
            )

            # Convert next trigger to UTC for storage
            next_trigger_utc = (
                next_trigger.astimezone(pytz.UTC) if next_trigger else None
            )

            # Update schedule (store times in UTC)
            self._update_schedule_next_trigger(
                schedule, next_trigger_utc, last_triggered_at=current_time_utc
            )

            logger.info(
                "Successfully processed schedule",
                schedule_id=str(schedule.id),
                order_number=schedule.order_number,
                is_start=is_start,
                next_trigger_at=next_trigger.isoformat() if next_trigger else None,
            )

        except Exception as e:
            logger.error(
                "Error processing schedule",
                schedule_id=str(schedule.id),
                error=str(e),
            )
            raise

    def _check_time_slot(
        self,
        schedule: PriceAdjustmentSchedule,
        current_time: datetime,
        store_timezone: pytz.BaseTzInfo,
    ) -> Tuple[bool, bool]:
        """
        Check if current time is within any time slot.

        Returns:
            (in_slot, is_start) - True if in slot, True if at start of slot
        """
        current_time_str = current_time.strftime("%H:%M")
        current_time_only = datetime.strptime(current_time_str, "%H:%M").time()

        for slot in schedule.time_slots:
            start_time = datetime.strptime(slot["start_time"], "%H:%M").time()
            end_time = datetime.strptime(slot["end_time"], "%H:%M").time()

            # Check if we're at the start time (within 1 minute)
            start_datetime = store_timezone.localize(
                datetime.combine(current_time.date(), start_time)
            )
            time_diff = abs((current_time - start_datetime).total_seconds())
            if time_diff <= 60:  # Within 1 minute of start
                return (True, True)

            # Check if we're at the end time (within 1 minute)
            end_datetime = store_timezone.localize(
                datetime.combine(current_time.date(), end_time)
            )
            time_diff = abs((current_time - end_datetime).total_seconds())
            if time_diff <= 60:  # Within 1 minute of end
                return (True, False)

            # Check if we're within the time slot
            if start_time <= current_time_only <= end_time:
                return (True, False)

        return (False, False)

    def _calculate_next_trigger(
        self,
        schedule: PriceAdjustmentSchedule,
        current_time: datetime,
        store_timezone: pytz.BaseTzInfo,
    ) -> Optional[datetime]:
        """
        Calculate the next trigger time for a schedule.
        All datetime operations are performed in the store's timezone.
        """
        # Ensure schedule dates are in store timezone
        start_date = schedule.start_date
        if start_date.tzinfo is None:
            start_date = store_timezone.localize(start_date)
        else:
            start_date = start_date.astimezone(store_timezone)

        end_date = schedule.end_date
        if end_date is not None:
            if end_date.tzinfo is None:
                end_date = store_timezone.localize(end_date)
            else:
                end_date = end_date.astimezone(store_timezone)

        # Check if schedule has ended
        if end_date and current_time > end_date:
            return None

        # Check if schedule hasn't started yet
        if current_time < start_date:
            if schedule.time_slots:
                first_slot = schedule.time_slots[0]
                start_datetime = start_date.replace(
                    hour=int(first_slot["start_time"].split(":")[0]),
                    minute=int(first_slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                return start_datetime
            return start_date

        # For daily repeat, check if we need to trigger at end of current slot first
        if schedule.repeat_type == "daily":
            if schedule.time_slots:
                # Check if we're currently in a time slot and need to trigger at end
                current_time_str = current_time.strftime("%H:%M")
                current_time_only = datetime.strptime(current_time_str, "%H:%M").time()

                for slot in schedule.time_slots:
                    start_time = datetime.strptime(slot["start_time"], "%H:%M").time()
                    end_time = datetime.strptime(slot["end_time"], "%H:%M").time()

                    # If we're within the time slot but not at the end yet, trigger at end
                    if start_time <= current_time_only < end_time:
                        end_datetime = current_time.replace(
                            hour=int(slot["end_time"].split(":")[0]),
                            minute=int(slot["end_time"].split(":")[1]),
                            second=0,
                            microsecond=0,
                        )
                        return end_datetime

                # Otherwise, next trigger is tomorrow at first time slot
                first_slot = schedule.time_slots[0]
                tomorrow = current_time + timedelta(days=1)
                return tomorrow.replace(
                    hour=int(first_slot["start_time"].split(":")[0]),
                    minute=int(first_slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )

        # For weekly repeat, find next trigger day
        if schedule.repeat_type == "weekly" and schedule.trigger_days:
            current_weekday = current_time.weekday()  # 0=Mon, 6=Sun

            trigger_days_int = sorted([int(d) for d in schedule.trigger_days])

            # Find next day
            days_ahead = None
            for day in trigger_days_int:
                day_index = day - 1
                if day_index > current_weekday:
                    days_ahead = day_index - current_weekday
                    break

            if days_ahead is None:
                # Next week
                days_ahead = (7 - current_weekday) + (trigger_days_int[0] - 1)

            next_date = current_time + timedelta(days=days_ahead)
            if schedule.time_slots:
                first_slot = schedule.time_slots[0]
                return next_date.replace(
                    hour=int(first_slot["start_time"].split(":")[0]),
                    minute=int(first_slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )

        # For no repeat, check if there are more time slots today
        if schedule.repeat_type == "none":
            if schedule.time_slots:
                for slot in schedule.time_slots:
                    slot_time = current_time.replace(
                        hour=int(slot["start_time"].split(":")[0]),
                        minute=int(slot["start_time"].split(":")[1]),
                        second=0,
                        microsecond=0,
                    )
                    if slot_time > current_time:
                        return slot_time

                # Check end time of last slot
                last_slot = schedule.time_slots[-1]
                last_end = current_time.replace(
                    hour=int(last_slot["end_time"].split(":")[0]),
                    minute=int(last_slot["end_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                if current_time < last_end:
                    return last_end

        return None

    def _update_schedule_next_trigger(
        self,
        schedule: PriceAdjustmentSchedule,
        next_trigger: Optional[datetime],
        last_triggered_at: Optional[datetime] = None,
    ):
        """Update schedule's next trigger time."""
        update_data = {}
        if next_trigger:
            update_data["next_trigger_at"] = next_trigger.isoformat()
        else:
            # No more triggers - deactivate schedule
            update_data["is_active"] = False
            update_data["next_trigger_at"] = None

        if last_triggered_at:
            update_data["last_triggered_at"] = last_triggered_at.isoformat()

        self.supabase_service.update_price_adjustment_schedule(
            schedule.id,  # type: ignore
            update_data,
        )

    async def _apply_promotional_prices(
        self,
        schedule: PriceAdjustmentSchedule,
        store_mapping: StoreMapping,
        products_data: list,
    ):
        """Apply promotional prices to products - preserves all existing product data."""
        try:
            # Determine which store codes to use
            store_codes = []
            if schedule.trigger_stores and len(schedule.trigger_stores) > 0:
                store_codes = schedule.trigger_stores
            else:
                store_codes = [store_mapping.hipoink_store_code]

            # Build Hipoink product items with full product data, only updating price
            hipoink_products = []
            for product_data in products_data:
                barcode = product_data["pc"]
                new_price = str(product_data["pp"])

                # Get existing product from database to preserve all fields
                existing_product = self.supabase_service.get_product_by_barcode(barcode)

                if existing_product and existing_product.normalized_data:
                    # Use existing product data, only update price
                    normalized = existing_product.normalized_data
                    hipoink_product = HipoinkProductItem(
                        product_code=barcode,
                        product_name=normalized.get("title")
                        or existing_product.title
                        or "",
                        product_price=new_price,  # Updated price
                        product_inner_code=normalized.get("sku")
                        or existing_product.sku,
                        product_image_url=normalized.get("image_url")
                        or existing_product.image_url,
                        product_qrcode_url=normalized.get("image_url")
                        or existing_product.image_url,
                        f1=existing_product.source_system
                        if existing_product.source_system
                        else None,
                    )
                else:
                    # Product not in database - create minimal product with just price
                    # This shouldn't happen normally, but handle gracefully
                    logger.warning(
                        "Product not found in database, creating minimal product",
                        barcode=barcode,
                        schedule_id=str(schedule.id),
                    )
                    hipoink_product = HipoinkProductItem(
                        product_code=barcode,
                        product_name="",  # Will be empty if product doesn't exist
                        product_price=new_price,
                    )

                hipoink_products.append(hipoink_product)

            # Apply price changes to all specified stores
            for store_code in store_codes:
                # Update products in Hipoink (same as Shopify update - preserves all fields)
                response = await self.hipoink_client.create_products_multiple(
                    store_code=str(store_code),
                    products=hipoink_products,
                )

                # Check response
                error_code = response.get("error_code")
                if error_code != 0:
                    error_msg = response.get("error_msg", "Unknown error")
                    raise HipoinkAPIError(
                        f"Hipoink price update failed for store {store_code}: {error_msg} (code: {error_code})"
                    )

                logger.info(
                    "Applied promotional prices",
                    schedule_id=str(schedule.id),
                    product_count=len(hipoink_products),
                    store_code=str(store_code),
                )

        except Exception as e:
            logger.error(
                "Failed to apply promotional prices",
                schedule_id=str(schedule.id),
                error=str(e),
            )
            raise

    async def _restore_original_prices(
        self,
        schedule: PriceAdjustmentSchedule,
        store_mapping: StoreMapping,
        products_data: list,
    ):
        """Restore original prices to products - preserves all existing product data."""
        try:
            # Determine which store codes to use
            store_codes = []
            if schedule.trigger_stores and len(schedule.trigger_stores) > 0:
                store_codes = schedule.trigger_stores
            else:
                store_codes = [store_mapping.hipoink_store_code]

            # Build Hipoink product items with full product data, only updating price
            hipoink_products = []
            for product_data in products_data:
                barcode = product_data["pc"]
                original_price = product_data.get("original_price")

                if original_price is None:
                    logger.warning(
                        "No original price found for product",
                        product_code=barcode,
                        schedule_id=str(schedule.id),
                    )
                    continue

                # Get existing product from database to preserve all fields
                existing_product = self.supabase_service.get_product_by_barcode(barcode)

                if existing_product and existing_product.normalized_data:
                    # Use existing product data, only update price
                    normalized = existing_product.normalized_data
                    hipoink_product = HipoinkProductItem(
                        product_code=barcode,
                        product_name=normalized.get("title")
                        or existing_product.title
                        or "",
                        product_price=str(original_price),  # Restored original price
                        product_inner_code=normalized.get("sku")
                        or existing_product.sku,
                        product_image_url=normalized.get("image_url")
                        or existing_product.image_url,
                        product_qrcode_url=normalized.get("image_url")
                        or existing_product.image_url,
                        f1=existing_product.source_system
                        if existing_product.source_system
                        else None,
                    )
                else:
                    # Product not in database - create minimal product with just price
                    logger.warning(
                        "Product not found in database, creating minimal product",
                        barcode=barcode,
                        schedule_id=str(schedule.id),
                    )
                    hipoink_product = HipoinkProductItem(
                        product_code=barcode,
                        product_name="",
                        product_price=str(original_price),
                    )

                hipoink_products.append(hipoink_product)

            if not hipoink_products:
                logger.warning(
                    "No products with original prices to restore",
                    schedule_id=str(schedule.id),
                )
                return

            # Restore prices for all specified stores
            for store_code in store_codes:
                # Update products in Hipoink (same as Shopify update - preserves all fields)
                response = await self.hipoink_client.create_products_multiple(
                    store_code=str(store_code),
                    products=hipoink_products,
                )

                # Check response
                error_code = response.get("error_code")
                if error_code != 0:
                    error_msg = response.get("error_msg", "Unknown error")
                    raise HipoinkAPIError(
                        f"Hipoink price restore failed for store {store_code}: {error_msg} (code: {error_code})"
                    )

                logger.info(
                    "Restored original prices",
                    schedule_id=str(schedule.id),
                    product_count=len(hipoink_products),
                    store_code=str(store_code),
                )

        except Exception as e:
            logger.error(
                "Failed to restore original prices",
                schedule_id=str(schedule.id),
                error=str(e),
            )
            raise


async def run_price_scheduler():
    """
    Main entry point for running the price scheduler.
    Creates a PriceScheduler instance and starts it.
    """
    scheduler = PriceScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down price scheduler")
    finally:
        await scheduler.stop()
