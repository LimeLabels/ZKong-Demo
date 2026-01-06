"""
API router for time-based price adjustment schedules.
Manages scheduling price changes and triggers updates via product update endpoint.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import structlog
import pytz
from pydantic import BaseModel, Field

from app.services.hipoink_client import HipoinkClient
from app.services.supabase_service import SupabaseService
from app.models.database import PriceAdjustmentSchedule, StoreMapping
from app.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/api/price-adjustments", tags=["price-adjustments"])

# Service instances
hipoink_client = HipoinkClient(
    client_id=getattr(settings, "hipoink_client_id", "default")
)
supabase_service = SupabaseService()


# Request/Response Models


class PriceAdjustmentProduct(BaseModel):
    """Product data for price adjustment."""

    pc: str = Field(..., description="Product code (barcode)")
    pp: str = Field(..., description="Product price (as string)")
    original_price: Optional[float] = Field(
        None, description="Original price to restore later"
    )


class TimeSlot(BaseModel):
    """Time slot for price adjustment."""

    start_time: str = Field(..., description="Start time in HH:MM format")
    end_time: str = Field(..., description="End time in HH:MM format")


class CreatePriceAdjustmentRequest(BaseModel):
    """Request model for creating a price adjustment schedule."""

    store_mapping_id: UUID = Field(..., description="Store mapping UUID")
    name: str = Field(..., description="Schedule name")
    order_number: Optional[str] = Field(
        None, description="Order number (auto-generated if not provided)"
    )
    products: List[PriceAdjustmentProduct] = Field(
        ..., description="Products to adjust"
    )
    start_date: datetime = Field(..., description="Schedule start date")
    end_date: Optional[datetime] = Field(None, description="Schedule end date")
    repeat_type: str = Field(
        "none", description="Repeat type: none, daily, weekly, monthly"
    )
    trigger_days: Optional[List[str]] = Field(
        None,
        description="Days of week: ['1']=Mon, ['2']=Tue, ['3']=Wed, ['4']=Thu, ['5']=Fri, ['6']=Sat, ['7']=Sun",
    )
    trigger_stores: Optional[List[str]] = Field(
        None, description="Store codes to trigger (optional)"
    )
    time_slots: List[TimeSlot] = Field(
        ..., description="Time slots for price adjustments"
    )


class PriceAdjustmentResponse(BaseModel):
    """Response model for price adjustment schedule."""

    id: UUID
    name: str
    order_number: str
    is_active: bool
    next_trigger_at: Optional[datetime] = None
    created_at: datetime


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


def calculate_next_trigger_time(
    schedule: PriceAdjustmentSchedule,
    current_time: datetime,
    store_timezone: pytz.BaseTzInfo,
) -> Optional[datetime]:
    """
    Calculate the next trigger time for a schedule based on current time.
    All datetime operations are performed in the store's timezone.

    Args:
        schedule: Price adjustment schedule
        current_time: Current datetime (timezone-aware)
        store_timezone: Store's timezone

    Returns:
        Next trigger datetime (timezone-aware) or None if schedule is expired
    """
    # Ensure current_time is timezone-aware
    if current_time.tzinfo is None:
        current_time = store_timezone.localize(current_time)
    else:
        current_time = current_time.astimezone(store_timezone)

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
        # Find first time slot on start date
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

    # For repeat schedules, calculate next occurrence
    if schedule.repeat_type == "none":
        # No repeat - check if we're past the last time slot
        if schedule.time_slots:
            last_slot = schedule.time_slots[-1]
            # Use start_date's date for the last trigger time
            last_trigger = start_date.replace(
                hour=int(last_slot["end_time"].split(":")[0]),
                minute=int(last_slot["end_time"].split(":")[1]),
                second=0,
                microsecond=0,
            )
            if current_time > last_trigger:
                return None
            # Find next time slot on start_date
            # Use start_date's date, not current_time's date
            for slot in schedule.time_slots:
                slot_time = start_date.replace(
                    hour=int(slot["start_time"].split(":")[0]),
                    minute=int(slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                if slot_time > current_time:
                    return slot_time
            # If we're in the middle of a time slot, return the start of the current slot
            # This handles the case where schedule is created during an active time slot
            for slot in schedule.time_slots:
                slot_start = start_date.replace(
                    hour=int(slot["start_time"].split(":")[0]),
                    minute=int(slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                slot_end = start_date.replace(
                    hour=int(slot["end_time"].split(":")[0]),
                    minute=int(slot["end_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                if slot_start <= current_time <= slot_end:
                    return slot_start
        return None

    elif schedule.repeat_type == "daily":
        # Daily repeat - find next time slot today or tomorrow
        for slot in schedule.time_slots:
            slot_time = current_time.replace(
                hour=int(slot["start_time"].split(":")[0]),
                minute=int(slot["start_time"].split(":")[1]),
                second=0,
                microsecond=0,
            )
            if slot_time > current_time:
                return slot_time

        # No more slots today, use first slot tomorrow
        if schedule.time_slots:
            first_slot = schedule.time_slots[0]
            tomorrow = current_time + timedelta(days=1)
            return tomorrow.replace(
                hour=int(first_slot["start_time"].split(":")[0]),
                minute=int(first_slot["start_time"].split(":")[1]),
                second=0,
                microsecond=0,
            )

    elif schedule.repeat_type == "weekly":
        # Weekly repeat - find next occurrence based on trigger_days
        if not schedule.trigger_days:
            return None

        # Get current day of week (0=Monday, 6=Sunday)
        current_weekday = current_time.weekday()  # 0=Mon, 6=Sun
        # Convert to Hipoink format (1=Mon, 7=Sun)
        current_day = str(current_weekday + 1)

        # Find next day in trigger_days
        trigger_days_int = [int(d) for d in schedule.trigger_days]
        trigger_days_int.sort()

        # Check if today is a trigger day and there's a future time slot
        if current_day in schedule.trigger_days:
            for slot in schedule.time_slots:
                slot_time = current_time.replace(
                    hour=int(slot["start_time"].split(":")[0]),
                    minute=int(slot["start_time"].split(":")[1]),
                    second=0,
                    microsecond=0,
                )
                if slot_time > current_time:
                    return slot_time

        # Find next trigger day
        days_ahead = None
        for day in trigger_days_int:
            day_index = day - 1  # Convert to 0-based (0=Mon, 6=Sun)
            if day_index > current_weekday:
                days_ahead = day_index - current_weekday
                break

        if days_ahead is None:
            # Next occurrence is next week
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

    return None


@router.post(
    "/create",
    response_model=PriceAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_price_adjustment(request: CreatePriceAdjustmentRequest):
    """
    Create a price adjustment schedule.

    This creates a schedule that will trigger price changes at specified times.
    A background worker will check schedules and apply price changes via the product update endpoint.
    """
    try:
        # Get store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(
            request.store_mapping_id
        )
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {request.store_mapping_id}",
            )

        # Validate products
        if not request.products or len(request.products) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one product is required",
            )

        # Generate order number if not provided
        order_number = (
            request.order_number or f"PA-{int(datetime.utcnow().timestamp() * 1000)}"
        )

        # Prepare products data
        products_data = []
        for p in request.products:
            products_data.append(
                {
                    "pc": str(p.pc),
                    "pp": str(p.pp),
                    "original_price": p.original_price,
                }
            )

        # Prepare time slots
        time_slots_data = [
            {"start_time": ts.start_time, "end_time": ts.end_time}
            for ts in request.time_slots
        ]

        # Get store timezone
        store_timezone = get_store_timezone(store_mapping)

        # Get current time in store's timezone
        current_time = datetime.now(store_timezone)

        # Normalize request datetimes to store timezone
        start_date = request.start_date
        if start_date.tzinfo is None:
            # If naive, assume it's in store timezone
            start_date = store_timezone.localize(start_date)
        else:
            # Convert to store timezone
            start_date = start_date.astimezone(store_timezone)

        end_date = request.end_date
        if end_date is not None:
            if end_date.tzinfo is None:
                end_date = store_timezone.localize(end_date)
            else:
                end_date = end_date.astimezone(store_timezone)

        # Calculate next trigger time
        next_trigger = calculate_next_trigger_time(
            PriceAdjustmentSchedule(
                store_mapping_id=request.store_mapping_id,
                name=request.name,
                order_number=order_number,
                products={"products": products_data},
                start_date=start_date,
                end_date=end_date,
                repeat_type=request.repeat_type,
                trigger_days=request.trigger_days,
                trigger_stores=request.trigger_stores,
                time_slots=time_slots_data,
            ),
            current_time,
            store_timezone,
        )

        # Create schedule
        schedule = PriceAdjustmentSchedule(
            store_mapping_id=request.store_mapping_id,
            name=request.name,
            order_number=order_number,
            products={"products": products_data},
            start_date=start_date,
            end_date=end_date,
            repeat_type=request.repeat_type,
            trigger_days=request.trigger_days,
            trigger_stores=request.trigger_stores,
            time_slots=time_slots_data,
            is_active=True,
            next_trigger_at=next_trigger,
        )

        created_schedule = supabase_service.create_price_adjustment_schedule(schedule)

        logger.info(
            "Created price adjustment schedule",
            schedule_id=str(created_schedule.id),
            order_number=order_number,
            next_trigger_at=next_trigger.isoformat() if next_trigger else None,
        )

        return PriceAdjustmentResponse(
            id=created_schedule.id,  # type: ignore
            name=created_schedule.name,
            order_number=created_schedule.order_number,
            is_active=created_schedule.is_active,
            next_trigger_at=created_schedule.next_trigger_at,
            created_at=created_schedule.created_at or datetime.now(pytz.UTC),  # type: ignore
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create price adjustment schedule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create price adjustment schedule: {str(e)}",
        )


@router.get("/{schedule_id}", response_model=PriceAdjustmentSchedule)
async def get_price_adjustment(schedule_id: UUID):
    """Get a price adjustment schedule by ID."""
    schedule = supabase_service.get_price_adjustment_schedule(schedule_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price adjustment schedule not found: {schedule_id}",
        )
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price_adjustment(schedule_id: UUID):
    """Delete (deactivate) a price adjustment schedule."""
    success = supabase_service.delete_price_adjustment_schedule(schedule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price adjustment schedule not found: {schedule_id}",
        )
