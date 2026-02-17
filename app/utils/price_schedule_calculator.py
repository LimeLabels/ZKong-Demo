"""
Utility module for calculating all price events from a price adjustment schedule.
This module calculates all future price change events that need to be pre-scheduled in NCR.
"""

from datetime import datetime, time, timedelta
from typing import Any

import pytz
import structlog

from app.models.database import PriceAdjustmentSchedule

logger = structlog.get_logger()


class PriceEvent:
    """
    Represents a single price change event that needs to be scheduled.

    Attributes:
        item_code: Product item code (barcode)
        price: Price to set
        effective_date: When the price should become effective (timezone-aware datetime)
        event_type: Type of event ('apply_promotion' or 'restore_original')
        schedule_id: ID of the schedule this event belongs to
    """

    def __init__(
        self,
        item_code: str,
        price: float,
        effective_date: datetime,
        event_type: str,
        schedule_id: str | None = None,
    ):
        self.item_code = item_code
        self.price = price
        self.effective_date = effective_date
        self.event_type = event_type
        self.schedule_id = schedule_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage in metadata."""
        return {
            "item_code": self.item_code,
            "price": self.price,
            "effective_date": self.effective_date.isoformat(),
            "event_type": self.event_type,
            "status": "scheduled",  # scheduled | applied | failed
        }


def calculate_all_price_events(
    schedule: PriceAdjustmentSchedule,
    store_timezone: pytz.BaseTzInfo,
) -> list[PriceEvent]:
    """
    Calculate all price change events for a schedule.

    This function generates all price change events that need to be pre-scheduled
    in NCR using effectiveDate. It handles:
    - Daily repeats
    - Weekly repeats (with trigger_days)
    - No repeat (single occurrence)
    - Multiple time slots per day
    - Start and end of each time slot

    Args:
        schedule: Price adjustment schedule
        store_timezone: Store's timezone for datetime calculations

    Returns:
        List of PriceEvent objects representing all price changes
    """
    events: list[PriceEvent] = []

    # Get products from schedule
    products_data = schedule.products.get("products", [])
    if not products_data:
        logger.warning(
            "Schedule has no products, cannot calculate events",
            schedule_id=str(schedule.id),
        )
        return events

    # Ensure schedule dates are timezone-aware
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

    # For daily/weekly repeats, if end_date is same as start_date, treat as no end
    effective_end_date = end_date
    if schedule.repeat_type in ["daily", "weekly", "monthly"]:
        if end_date and abs((end_date - start_date).total_seconds()) < 60:
            effective_end_date = None

    # Calculate dates to process
    dates_to_process = _calculate_dates_to_process(
        schedule, start_date, effective_end_date, store_timezone
    )

    # Process each date
    for date_obj in dates_to_process:
        # Process each time slot for this date
        for time_slot in schedule.time_slots:
            start_time_str = time_slot["start_time"]
            end_time_str = time_slot["end_time"]

            # Parse time strings (HH:MM format)
            start_hour, start_minute = map(int, start_time_str.split(":"))
            end_hour, end_minute = map(int, end_time_str.split(":"))

            # Create datetime objects for start and end of slot
            slot_start = store_timezone.localize(
                datetime.combine(
                    date_obj,
                    time(hour=start_hour, minute=start_minute, second=0, microsecond=0),
                )
            )

            slot_end = store_timezone.localize(
                datetime.combine(
                    date_obj,
                    time(hour=end_hour, minute=end_minute, second=0, microsecond=0),
                )
            )

            # Skip if slot_end is before slot_start (shouldn't happen, but safety check)
            if slot_end <= slot_start:
                logger.warning(
                    "Invalid time slot: end <= start",
                    schedule_id=str(schedule.id),
                    start_time=start_time_str,
                    end_time=end_time_str,
                )
                continue

            # Process each product
            for product_data in products_data:
                item_code = product_data["pc"]
                original_price = product_data.get("original_price")
                promotional_price_str = product_data.get("pp", "0")

                # Calculate promotional price
                if schedule.multiplier_percentage is not None:
                    # Use multiplier if provided
                    if original_price is not None:
                        promotional_price = original_price * (
                            1 + schedule.multiplier_percentage / 100
                        )
                    else:
                        # Fallback to provided price if no original_price
                        promotional_price = float(promotional_price_str)
                else:
                    # Use provided price
                    promotional_price = float(promotional_price_str)

                # Ensure we have original_price
                if original_price is None:
                    # Try to get from provided price (assume it's the original)
                    original_price = float(promotional_price_str)

                # Event 1: Apply promotional price at start of slot
                events.append(
                    PriceEvent(
                        item_code=item_code,
                        price=promotional_price,
                        effective_date=slot_start,
                        event_type="apply_promotion",
                        schedule_id=str(schedule.id) if schedule.id else None,
                    )
                )

                # Event 2: Restore original price at end of slot
                events.append(
                    PriceEvent(
                        item_code=item_code,
                        price=original_price,
                        effective_date=slot_end,
                        event_type="restore_original",
                        schedule_id=str(schedule.id) if schedule.id else None,
                    )
                )

    # Sort events by effective_date
    events.sort(key=lambda e: e.effective_date)

    logger.info(
        "Calculated price events for schedule",
        schedule_id=str(schedule.id),
        event_count=len(events),
        date_range=f"{start_date.date()} to {effective_end_date.date() if effective_end_date else 'indefinite'}",
    )

    return events


def _calculate_dates_to_process(
    schedule: PriceAdjustmentSchedule,
    start_date: datetime,
    end_date: datetime | None,
    store_timezone: pytz.BaseTzInfo,
) -> list[datetime.date]:
    """
    Calculate which dates need to be processed based on repeat type.

    Args:
        schedule: Price adjustment schedule
        start_date: Start date (timezone-aware)
        end_date: End date (timezone-aware, or None)
        store_timezone: Store's timezone

    Returns:
        List of date objects to process
    """
    dates: list[datetime.date] = []
    current_date = start_date.date()

    # Get current time in store timezone for filtering past dates
    now = datetime.now(store_timezone)
    current_time_date = now.date()

    if schedule.repeat_type == "none":
        # No repeat - just the start date (or dates within start/end range)
        if end_date:
            # Process all dates from start to end
            date = current_date
            while date <= end_date.date():
                dates.append(date)
                date += timedelta(days=1)
        else:
            # Just the start date
            dates.append(current_date)

    elif schedule.repeat_type == "daily":
        # Daily repeat - process all dates from start to end (or up to a reasonable limit)
        if end_date:
            date = current_date
            while date <= end_date.date():
                dates.append(date)
                date += timedelta(days=1)
        else:
            # No end date - process up to 365 days ahead (1 year)
            # This prevents creating too many events
            date = current_date
            max_date = current_date + timedelta(days=365)
            while date <= max_date:
                dates.append(date)
                date += timedelta(days=1)

    elif schedule.repeat_type == "weekly":
        # Weekly repeat - process dates on trigger_days only
        if not schedule.trigger_days:
            logger.warning(
                "Weekly repeat schedule has no trigger_days",
                schedule_id=str(schedule.id),
            )
            return dates

        # Convert trigger_days to weekday numbers (0=Monday, 6=Sunday)
        trigger_weekdays = [int(d) - 1 for d in schedule.trigger_days]  # Convert 1-7 to 0-6

        if end_date:
            date = current_date
            while date <= end_date.date():
                weekday = date.weekday()  # 0=Monday, 6=Sunday
                if weekday in trigger_weekdays:
                    dates.append(date)
                date += timedelta(days=1)
        else:
            # No end date - process up to 52 weeks ahead (1 year)
            date = current_date
            max_date = current_date + timedelta(days=365)
            while date <= max_date:
                weekday = date.weekday()
                if weekday in trigger_weekdays:
                    dates.append(date)
                date += timedelta(days=1)

    elif schedule.repeat_type == "monthly":
        # Monthly repeat - process same day of month each month
        if end_date:
            date = current_date
            while date <= end_date.date():
                # Check if this date is the same day of month as start_date
                if date.day == start_date.day:
                    dates.append(date)
                date += timedelta(days=1)
        else:
            # No end date - process up to 12 months ahead
            date = current_date
            for _ in range(12):
                dates.append(date)
                # Move to next month (same day)
                if date.month == 12:
                    date = date.replace(year=date.year + 1, month=1)
                else:
                    date = date.replace(month=date.month + 1)

    # Filter out past dates (only keep future dates)
    dates = [d for d in dates if d >= current_time_date]

    return dates
