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
from app.services.shopify_api_client import ShopifyAPIClient
from app.integrations.ncr.adapter import NCRIntegrationAdapter
from app.integrations.square.adapter import SquareIntegrationAdapter
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
            
            logger.debug(
                "Checking for due schedules",
                current_time_utc=current_time_utc.isoformat(),
            )
            
            schedules = self.supabase_service.get_schedules_due_for_trigger(
                current_time_utc
            )

            if not schedules:
                logger.debug("No schedules due for trigger")
                return  # No schedules to process

            logger.info(
                "Processing price adjustment schedules",
                schedule_count=len(schedules),
                schedule_ids=[str(s.id) for s in schedules],
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
            logger.info(
                "Processing schedule",
                schedule_id=str(schedule.id),
                schedule_name=schedule.name,
                order_number=schedule.order_number,
                repeat_type=schedule.repeat_type,
                time_slots=schedule.time_slots,
            )
            
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
            
            logger.info(
                "Schedule timezone info",
                schedule_id=str(schedule.id),
                store_timezone=str(store_timezone),
                has_timezone_in_metadata=bool(store_mapping.metadata and "timezone" in store_mapping.metadata),
            )

            # Convert current time to store timezone
            current_time = current_time_utc.astimezone(store_timezone)

            # Check if we're in a time slot
            in_time_slot, is_start = self._check_time_slot(
                schedule, current_time, store_timezone
            )
            
            logger.info(
                "Time slot check result",
                schedule_id=str(schedule.id),
                current_time_utc=current_time_utc.isoformat(),
                current_time_local=current_time.isoformat(),
                in_time_slot=in_time_slot,
                is_start=is_start,
            )

            if not in_time_slot:
                # Not in a time slot - calculate next trigger and skip
                logger.info(
                    "Schedule not in time slot, calculating next trigger",
                    schedule_id=str(schedule.id),
                    current_time=current_time.isoformat(),
                )
                next_trigger = self._calculate_next_trigger(
                    schedule, current_time, store_timezone
                )
                logger.info(
                    "Next trigger calculated (not in slot)",
                    schedule_id=str(schedule.id),
                    next_trigger=next_trigger.isoformat() if next_trigger else "None - schedule will be deactivated",
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
                # After applying promotional price, next trigger should be end of current slot
                # Find the current slot's end time
                current_time_str = current_time.strftime("%H:%M")
                current_time_only = datetime.strptime(current_time_str, "%H:%M").time()
                for slot in schedule.time_slots:
                    start_time = datetime.strptime(slot["start_time"], "%H:%M").time()
                    end_time = datetime.strptime(slot["end_time"], "%H:%M").time()
                    if start_time <= current_time_only <= end_time:
                        # Found the current slot, set next trigger to its end time
                        # Use store timezone to ensure correct datetime
                        current_date = current_time.date()
                        end_hour = int(slot["end_time"].split(":")[0])
                        end_minute = int(slot["end_time"].split(":")[1])
                        next_trigger = store_timezone.localize(
                            datetime.combine(
                                current_date,
                                datetime.min.time().replace(
                                    hour=end_hour, minute=end_minute
                                ),
                            )
                        )
                        break
                else:
                    # Fallback: calculate normally
                    next_trigger = self._calculate_next_trigger(
                        schedule, current_time, store_timezone
                    )
            else:
                # Restore original prices (end of time slot)
                await self._restore_original_prices(
                    schedule, store_mapping, products_data
                )
                # After restoring, next trigger is tomorrow's start time (for daily repeat)
                # or calculate normally for other repeat types
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
        
        # Log for debugging
        logger.debug(
            "Checking time slots",
            current_time=current_time.isoformat(),
            current_time_str=current_time_str,
            time_slots=schedule.time_slots,
        )

        for slot in schedule.time_slots:
            start_time = datetime.strptime(slot["start_time"], "%H:%M").time()
            end_time = datetime.strptime(slot["end_time"], "%H:%M").time()

            # Check if we're at the start time (within 2 minutes - increased tolerance for scheduler polling)
            start_datetime = store_timezone.localize(
                datetime.combine(current_time.date(), start_time)
            )
            time_diff_start = abs((current_time - start_datetime).total_seconds())
            
            # Check if we're at the end time (within 2 minutes)
            end_datetime = store_timezone.localize(
                datetime.combine(current_time.date(), end_time)
            )
            time_diff_end = abs((current_time - end_datetime).total_seconds())
            
            logger.debug(
                "Time slot comparison",
                slot_start=slot["start_time"],
                slot_end=slot["end_time"],
                time_diff_start_seconds=time_diff_start,
                time_diff_end_seconds=time_diff_end,
            )
            
            if time_diff_start <= 120:  # Within 2 minutes of start
                logger.info("At start of time slot", slot=slot, time_diff=time_diff_start)
                return (True, True)

            if time_diff_end <= 120:  # Within 2 minutes of end
                logger.info("At end of time slot", slot=slot, time_diff=time_diff_end)
                return (True, False)

            # Check if we're within the time slot (between start and end)
            # For short slots, we should apply promotional prices at the start
            if start_time <= current_time_only < end_time:
                # We're in the middle of the slot - this is a start event if we haven't triggered yet
                # Check if last_triggered_at is before today's start time
                if schedule.last_triggered_at is None:
                    # Never triggered - treat as start
                    logger.info("In time slot, no previous trigger - treating as start", slot=slot)
                    return (True, True)
                else:
                    # Check if last trigger was today
                    last_trigger_local = schedule.last_triggered_at.astimezone(store_timezone)
                    if last_trigger_local.date() < current_time.date():
                        # Last trigger was before today - treat as start
                        logger.info("In time slot, last trigger was different day - treating as start", slot=slot)
                        return (True, True)
                    else:
                        # Already triggered today - we're in the middle, waiting for end
                        logger.info("In time slot, already triggered today - waiting for end", slot=slot)
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
        logger.info(
            "Calculating next trigger",
            schedule_id=str(schedule.id),
            repeat_type=schedule.repeat_type,
            current_time=current_time.isoformat(),
            start_date=schedule.start_date.isoformat() if schedule.start_date else None,
            end_date=schedule.end_date.isoformat() if schedule.end_date else None,
        )
        
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
        # IMPORTANT: If end_date has time component (e.g. from frontend creation time), 
        # we should treat it as inclusive or end-of-day.
        if end_date:
            # If end_date is exactly the same as start_date (common UI pattern for single day),
            # or if we want to be generous, verify if it's strictly past the end date.
            # But better yet, let's normalize end_date to end-of-day if it seems to be mid-day
            # and potentially causing issues.
            
            # Use a grace period or check date component only if times are close?
            # Safer: Compare with end of the day of end_date if the time component seems arbitrary
            # But strictly speaking, if user set specific time, we should respect it.
            # However, the frontend sends new Date() which captures creation time.
            
            # Let's adjust end_date to end of day for comparison if it's the same day as current
            # This fixes the issue where "today" end date expires "today's" later schedules
            end_of_end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            if current_time > end_of_end_date:
                logger.info(
                    "Schedule has ended (past end of end_date day)",
                    schedule_id=str(schedule.id),
                    end_date=end_date.isoformat(),
                    end_of_end_date=end_of_end_date.isoformat(),
                    current_time=current_time.isoformat(),
                )
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

                    # Check if we're at or past the start time but before the end time
                    # This handles both "at start" and "in middle of slot" cases
                    if start_time <= current_time_only < end_time:
                        end_datetime = current_time.replace(
                            hour=int(slot["end_time"].split(":")[0]),
                            minute=int(slot["end_time"].split(":")[1]),
                            second=0,
                            microsecond=0,
                        )
                        return end_datetime

                    # Check if we're at or past the end time - next trigger is tomorrow
                    if current_time_only >= end_time:
                        # We've passed this slot, check if there are more slots today
                        # For daily, we'll just go to tomorrow's first slot
                        break

                # No more slots today (or we're past all slots) - next trigger is tomorrow at first time slot
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
            logger.info(
                "Processing 'none' repeat type schedule",
                schedule_id=str(schedule.id),
                current_time=current_time.isoformat(),
                time_slots=schedule.time_slots,
            )
            if schedule.time_slots:
                for slot in schedule.time_slots:
                    slot_time = current_time.replace(
                        hour=int(slot["start_time"].split(":")[0]),
                        minute=int(slot["start_time"].split(":")[1]),
                        second=0,
                        microsecond=0,
                    )
                    if slot_time > current_time:
                        logger.info(
                            "Found future slot start time",
                            schedule_id=str(schedule.id),
                            next_trigger=slot_time.isoformat(),
                        )
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
                    logger.info(
                        "Current time before last slot end, returning end time",
                        schedule_id=str(schedule.id),
                        next_trigger=last_end.isoformat(),
                    )
                    return last_end
                
                logger.info(
                    "No more triggers for 'none' repeat schedule - past all slots",
                    schedule_id=str(schedule.id),
                    current_time=current_time.isoformat(),
                    last_slot_end=last_end.isoformat(),
                )

        logger.info(
            "No next trigger found, schedule will be deactivated",
            schedule_id=str(schedule.id),
            repeat_type=schedule.repeat_type,
        )
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

    def _get_shopify_credentials(
        self, store_mapping: StoreMapping
    ) -> Optional[Tuple[str, str]]:
        """
        Get Shopify credentials from store mapping metadata.

        Returns:
            Tuple of (shop_domain, access_token) if available, None otherwise
        """
        if not store_mapping.metadata:
            logger.debug(
                "Store mapping has no metadata, cannot get Shopify credentials",
                store_mapping_id=str(store_mapping.id),
            )
            return None

        shop_domain = store_mapping.metadata.get("shopify_shop_domain")
        access_token = store_mapping.metadata.get("shopify_access_token")

        if not shop_domain:
            logger.warning(
                "Shopify shop domain not found in store mapping metadata",
                store_mapping_id=str(store_mapping.id),
                metadata_keys=list(store_mapping.metadata.keys())
                if store_mapping.metadata
                else [],
            )
            return None

        if not access_token:
            logger.warning(
                "Shopify access token not found in store mapping metadata",
                store_mapping_id=str(store_mapping.id),
                shop_domain=shop_domain,
            )
            return None

        return (shop_domain, access_token)

    async def _update_shopify_prices(
        self,
        products_data: list,
        new_price: Optional[str] = None,
        use_original: bool = False,
        shopify_credentials: Optional[Tuple[str, str]] = None,
    ):
        """
        Update prices in Shopify for products.

        Args:
            products_data: List of product data dicts with 'pc' (barcode)
            new_price: New price to set (if not using original)
            use_original: If True, use original_price from product_data
            shopify_credentials: Tuple of (shop_domain, access_token)
        """
        if not shopify_credentials:
            logger.debug("No Shopify credentials available, skipping Shopify update")
            return

        shop_domain, access_token = shopify_credentials

        try:
            async with ShopifyAPIClient(shop_domain, access_token) as shopify_client:
                updates = []

                for product_data in products_data:
                    barcode = product_data["pc"]

                    # Get product from database to find Shopify IDs
                    existing_product = self.supabase_service.get_product_by_barcode(
                        barcode
                    )

                    if not existing_product:
                        logger.warning(
                            "Product not found in database for Shopify update",
                            barcode=barcode,
                        )
                        continue

                    # Check if product is from Shopify
                    if existing_product.source_system != "shopify":
                        logger.debug(
                            "Product is not from Shopify, skipping",
                            barcode=barcode,
                            source_system=existing_product.source_system,
                        )
                        continue

                    # Get Shopify product and variant IDs
                    product_id = existing_product.source_id
                    variant_id = existing_product.source_variant_id

                    if not product_id or not variant_id:
                        logger.warning(
                            "Product missing Shopify IDs",
                            barcode=barcode,
                            product_id=product_id,
                            variant_id=variant_id,
                        )
                        continue

                    # Determine price to use
                    if use_original:
                        price = str(product_data.get("original_price", ""))
                    elif new_price:
                        price = new_price
                    else:
                        price = str(product_data.get("pp", ""))

                    if not price:
                        logger.warning(
                            "No price available for Shopify update",
                            barcode=barcode,
                        )
                        continue

                    updates.append(
                        {
                            "product_id": str(product_id),
                            "variant_id": str(variant_id),
                            "price": price,
                        }
                    )

                if updates:
                    results = await shopify_client.update_multiple_variant_prices(
                        updates
                    )
                    logger.info(
                        "Updated Shopify prices",
                        succeeded=len(results["succeeded"]),
                        failed=len(results["failed"]),
                    )

                    if results["failed"]:
                        logger.warning(
                            "Some Shopify price updates failed",
                            failed_updates=results["failed"],
                        )

        except Exception as e:
            # Log error but don't fail the entire operation
            error_str = str(e)
            # Check if it's an authentication error
            if "401" in error_str or "Unauthorized" in error_str:
                logger.error(
                    "Failed to update Shopify prices - Authentication error. "
                    "Please check that shopify_shop_domain and shopify_access_token "
                    "are correctly set in store mapping metadata",
                    shop_domain=shop_domain,
                    error=error_str,
                )
            else:
                logger.error(
                    "Failed to update Shopify prices (non-critical)",
                    shop_domain=shop_domain,
                    error=error_str,
                )

    async def _apply_promotional_prices(
        self,
        schedule: PriceAdjustmentSchedule,
        store_mapping: StoreMapping,
        products_data: list,
    ):
        """Apply promotional prices to products - preserves all existing product data."""
        logger.info(
            "Applying promotional prices",
            schedule_id=str(schedule.id),
            store_mapping_id=str(store_mapping.id),
            source_system=store_mapping.source_system,
            products_count=len(products_data),
            hipoink_store_code=store_mapping.hipoink_store_code,
        )
        try:
            # Validate hipoink_store_code
            if (
                not store_mapping.hipoink_store_code
                or store_mapping.hipoink_store_code.strip() == ""
            ):
                raise Exception(
                    f"Store mapping {store_mapping.id} has no Hipoink store code. Please complete onboarding."
                )

            # Determine which store codes to use
            store_codes = []
            if schedule.trigger_stores and len(schedule.trigger_stores) > 0:
                store_codes = schedule.trigger_stores
            else:
                store_codes = [store_mapping.hipoink_store_code]

            # Build Hipoink product items with full product data, only updating price
            hipoink_products = []
            updated_products_data = []  # Store updated product data with calculated prices for Shopify
            
            for product_data in products_data:
                barcode = product_data["pc"]

                # Calculate price: if multiplier_percentage is provided, use it; otherwise use provided price
                if schedule.multiplier_percentage is not None:
                    original_price = product_data.get("original_price")
                    if original_price is None:
                        # Try to get original price from database
                        existing_product = self.supabase_service.get_product_by_barcode(
                            barcode
                        )
                        if existing_product:
                            original_price = existing_product.price

                    if original_price is not None:
                        # Apply multiplier: price * (1 + multiplier_percentage / 100)
                        calculated_price = original_price * (
                            1 + schedule.multiplier_percentage / 100
                        )
                        new_price = str(round(calculated_price, 2))
                    else:
                        logger.warning(
                            "No original price found for multiplier calculation, using provided price",
                            barcode=barcode,
                            schedule_id=str(schedule.id),
                        )
                        new_price = str(product_data["pp"])
                else:
                    new_price = str(product_data["pp"])
                
                # Create updated product data with calculated price for Shopify
                updated_product_data = product_data.copy()
                updated_product_data["pp"] = new_price
                updated_products_data.append(updated_product_data)

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
                    "Applied promotional prices to Hipoink",
                    schedule_id=str(schedule.id),
                    product_count=len(hipoink_products),
                    store_code=str(store_code),
                )

            # Update Shopify prices if credentials are available
            shopify_credentials = self._get_shopify_credentials(store_mapping)
            if shopify_credentials:
                # Use updated_products_data which has the calculated prices (including multiplier)
                await self._update_shopify_prices(
                    updated_products_data,
                    new_price=None,  # Will use 'pp' from updated_products_data (includes calculated price)
                    shopify_credentials=shopify_credentials,
                )

            # Update NCR prices if store mapping is for NCR
            if store_mapping.source_system == "ncr":
                await self._update_ncr_prices(
                    updated_products_data,
                    store_mapping,
                )

            # Update Square prices if store mapping is for Square
            if store_mapping.source_system == "square":
                await self._update_square_prices(
                    updated_products_data,
                    store_mapping,
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
            # Validate hipoink_store_code
            if (
                not store_mapping.hipoink_store_code
                or store_mapping.hipoink_store_code.strip() == ""
            ):
                raise Exception(
                    f"Store mapping {store_mapping.id} has no Hipoink store code. Please complete onboarding."
                )

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
                    "Restored original prices to Hipoink",
                    schedule_id=str(schedule.id),
                    product_count=len(hipoink_products),
                    store_code=str(store_code),
                )

            # Update Shopify prices if credentials are available
            shopify_credentials = self._get_shopify_credentials(store_mapping)
            if shopify_credentials:
                await self._update_shopify_prices(
                    products_data,
                    use_original=True,  # Use original_price from product_data
                    shopify_credentials=shopify_credentials,
                )

            # Update NCR prices if store mapping is for NCR (restore original prices)
            if store_mapping.source_system == "ncr":
                await self._update_ncr_prices(
                    products_data,
                    store_mapping,
                    use_original=True,
                )

            # Update Square prices if store mapping is for Square (restore original prices)
            if store_mapping.source_system == "square":
                await self._update_square_prices(
                    products_data,
                    store_mapping,
                    use_original=True,
                )

        except Exception as e:
            logger.error(
                "Failed to restore original prices",
                schedule_id=str(schedule.id),
                error=str(e),
            )
            raise

    async def _update_ncr_prices(
        self,
        products_data: list,
        store_mapping: StoreMapping,
        use_original: bool = False,
    ):
        """
        Update prices in NCR for products.
        
        This method is called by the price scheduler to update NCR prices when schedules trigger.
        Since NCR doesn't provide webhooks, the scheduler polls every minute and updates prices directly.

        Args:
            products_data: List of product data dicts with 'pc' (item_code) and 'pp' (price) or 'original_price'
            store_mapping: Store mapping with NCR configuration
            use_original: If True, use original_price from product_data instead of 'pp'
        """
        if store_mapping.source_system != "ncr":
            logger.debug("Store mapping is not for NCR, skipping NCR update")
            return

        try:
            # Initialize NCR adapter
            ncr_adapter = NCRIntegrationAdapter()

            for product_data in products_data:
                item_code = product_data["pc"]  # Item code (barcode)

                # Determine price to use
                if use_original:
                    price = float(product_data.get("original_price", 0))
                else:
                    price = float(product_data.get("pp", 0))

                if price <= 0:
                    logger.warning(
                        "Invalid price for NCR update",
                        item_code=item_code,
                        price=price,
                    )
                    continue

                # Update price in NCR using the adapter
                # The adapter handles NCR API calls and updates the database
                try:
                    result = await ncr_adapter.update_price(
                        item_code=item_code,
                        price=price,
                        store_mapping_config={
                            "id": str(store_mapping.id),
                            "metadata": store_mapping.metadata or {},
                        },
                    )

                    logger.info(
                        "Updated NCR price",
                        item_code=item_code,
                        price=price,
                        use_original=use_original,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to update NCR price",
                        item_code=item_code,
                        price=price,
                        error=str(e),
                    )
                    # Continue with other products even if one fails
                    continue

        except Exception as e:
            # Log error but don't fail the entire operation
                logger.error(
                "Failed to update NCR prices (non-critical)",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
            )

    async def _update_square_prices(
        self,
        products_data: list,
        store_mapping: StoreMapping,
        use_original: bool = False,
    ):
        """
        Update prices in Square for products.
        
        This method is called by the price scheduler to update Square prices when schedules trigger.
        Square supports webhooks, but this provides a fallback polling mechanism.

        Args:
            products_data: List of product data dicts with 'pc' (object_id) and 'pp' (price) or 'original_price'
            store_mapping: Store mapping with Square configuration
            use_original: If True, use original_price from product_data instead of 'pp'
        """
        logger.info(
            "Starting Square price update",
            store_mapping_id=str(store_mapping.id),
            products_count=len(products_data),
            use_original=use_original,
        )
        
        if store_mapping.source_system != "square":
            logger.debug("Store mapping is not for Square, skipping Square update")
            return

        try:
            # Initialize Square adapter
            square_adapter = SquareIntegrationAdapter()

            # Get Square credentials from store mapping
            square_credentials = await square_adapter._get_square_credentials(store_mapping)
            if not square_credentials:
                logger.warning(
                    "No Square credentials available, skipping Square update",
                    store_mapping_id=str(store_mapping.id),
                )
                return

            merchant_id, access_token = square_credentials
            logger.info(
                "Got Square credentials",
                merchant_id=merchant_id,
            )

            updates = []
            failed_updates = []

            for product_data in products_data:
                object_id = product_data["pc"]  # Object ID (catalog object ID or barcode)

                # Determine price to use
                if use_original:
                    price = float(product_data.get("original_price", 0))
                else:
                    price = float(product_data.get("pp", 0))

                logger.info(
                    "Processing Square product price",
                    object_id=object_id,
                    price=price,
                    use_original=use_original,
                )

                if price <= 0:
                    logger.warning(
                        "Invalid price for Square update",
                        object_id=object_id,
                        price=price,
                    )
                    continue

                # Try to find product by barcode first, then by source_id or source_variant_id
                # This handles cases where object_id might be the catalog object ID, not barcode
                existing_product = self.supabase_service.get_product_by_barcode(
                    object_id
                )
                
                # If not found by barcode, try by source_id (catalog object ID)
                if not existing_product:
                    logger.debug(
                        "Product not found by barcode, trying by source_id",
                        object_id=object_id,
                    )
                    # Try to find by source_variant_id (Square variation ID)
                    existing_product = self.supabase_service.get_product_by_source_variant_id(
                        object_id
                    )

                if not existing_product:
                    logger.warning(
                        "Product not found in database for Square update",
                        barcode=object_id,
                    )
                    failed_updates.append(
                        {
                            "object_id": object_id,
                            "error": "Product not found in database",
                        }
                    )
                    continue

                # Check if product is from Square
                if existing_product.source_system != "square":
                    logger.debug(
                        "Product is not from Square, skipping",
                        barcode=object_id,
                        source_system=existing_product.source_system,
                    )
                    continue

                # Get Square catalog object ID (variation ID)
                # Use variant_id if available, otherwise use source_id
                catalog_object_id = existing_product.source_variant_id or existing_product.source_id

                if not catalog_object_id:
                    logger.warning(
                        "Product missing Square catalog object ID",
                        barcode=object_id,
                        product_id=str(existing_product.id),
                    )
                    failed_updates.append(
                        {
                            "object_id": object_id,
                            "error": "Missing catalog object ID",
                        }
                    )
                    continue

                # Update price in Square
                try:
                    result = await square_adapter.update_catalog_object_price(
                        object_id=catalog_object_id,
                        price=price,
                        access_token=access_token,
                    )
                    updates.append(
                        {
                            "object_id": catalog_object_id,
                            "barcode": object_id,
                            "price": price,
                            "result": result,
                        }
                    )
                    logger.info(
                        "Updated Square price",
                        object_id=catalog_object_id,
                        barcode=object_id,
                        price=price,
                        use_original=use_original,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to update Square price",
                        object_id=catalog_object_id,
                        barcode=object_id,
                        price=price,
                        error=str(e),
                    )
                    failed_updates.append(
                        {
                            "object_id": catalog_object_id,
                            "barcode": object_id,
                            "error": str(e),
                        }
                    )
                    # Continue with other products even if one fails
                    continue

            if updates:
                logger.info(
                    "Updated Square prices",
                    succeeded=len(updates),
                    failed=len(failed_updates),
                    store_mapping_id=str(store_mapping.id),
                )

            if failed_updates:
                logger.warning(
                    "Some Square price updates failed",
                    failed_updates=failed_updates,
                    store_mapping_id=str(store_mapping.id),
                )

        except Exception as e:
            # Log error but don't fail the entire operation
            error_str = str(e)
            # Check if it's an authentication error
            if "401" in error_str or "Unauthorized" in error_str:
                logger.error(
                    "Failed to update Square prices - Authentication error. "
                    "Please check that square_access_token is correctly set in store mapping metadata",
                    store_mapping_id=str(store_mapping.id),
                    error=error_str,
                )
            else:
                logger.error(
                    "Failed to update Square prices (non-critical)",
                    store_mapping_id=str(store_mapping.id),
                    error=error_str,
                )


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
