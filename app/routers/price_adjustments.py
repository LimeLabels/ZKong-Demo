"""
API router for time-based price adjustment schedules.
Manages scheduling price changes and triggers updates via product update endpoint.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional, Dict, Any
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

    # For repeat schedules (daily, weekly, monthly), ignore end_date if it's the same as start_date
    # This allows the schedule to repeat indefinitely
    # The frontend often sets end_date = start_date as a placeholder
    effective_end_date = end_date
    if schedule.repeat_type in ["daily", "weekly", "monthly"]:
        if end_date and abs((end_date - start_date).total_seconds()) < 60:
            # end_date is same as start_date (within 1 minute) - treat as no end date for repeats
            effective_end_date = None

    # Check if schedule has ended (only for non-repeat or if end_date is actually set)
    if effective_end_date and current_time > effective_end_date:
        return None

    # Check if schedule hasn't started yet - always return first time slot on start date
    if current_time < start_date:
        # Find first time slot on start date
        if schedule.time_slots:
            first_slot = schedule.time_slots[0]
            start_date_only = start_date.date()
            slot_hour = int(first_slot["start_time"].split(":")[0])
            slot_minute = int(first_slot["start_time"].split(":")[1])
            start_datetime = store_timezone.localize(
                datetime.combine(
                    start_date_only,
                    datetime.min.time().replace(hour=slot_hour, minute=slot_minute),
                )
            )
            return start_datetime
        return start_date

    # For repeat schedules, calculate next occurrence
    if schedule.repeat_type == "none":
        # No repeat - check if we're past the last time slot
        if schedule.time_slots:
            last_slot = schedule.time_slots[-1]
            # Use start_date's date for the last trigger time
            start_date_only = start_date.date()
            last_trigger_hour = int(last_slot["end_time"].split(":")[0])
            last_trigger_minute = int(last_slot["end_time"].split(":")[1])
            last_trigger = store_timezone.localize(
                datetime.combine(
                    start_date_only,
                    datetime.min.time().replace(
                        hour=last_trigger_hour, minute=last_trigger_minute
                    ),
                )
            )
            if current_time > last_trigger:
                return None
            # Find next time slot on start_date
            # Use start_date's date, not current_time's date
            for slot in schedule.time_slots:
                slot_hour = int(slot["start_time"].split(":")[0])
                slot_minute = int(slot["start_time"].split(":")[1])
                slot_time = store_timezone.localize(
                    datetime.combine(
                        start_date_only,
                        datetime.min.time().replace(hour=slot_hour, minute=slot_minute),
                    )
                )
                if slot_time > current_time:
                    return slot_time
            # If we're in the middle of a time slot, return the start of the current slot
            # This handles the case where schedule is created during an active time slot
            for slot in schedule.time_slots:
                slot_start_hour = int(slot["start_time"].split(":")[0])
                slot_start_minute = int(slot["start_time"].split(":")[1])
                slot_end_hour = int(slot["end_time"].split(":")[0])
                slot_end_minute = int(slot["end_time"].split(":")[1])
                slot_start = store_timezone.localize(
                    datetime.combine(
                        start_date_only,
                        datetime.min.time().replace(
                            hour=slot_start_hour, minute=slot_start_minute
                        ),
                    )
                )
                slot_end = store_timezone.localize(
                    datetime.combine(
                        start_date_only,
                        datetime.min.time().replace(
                            hour=slot_end_hour, minute=slot_end_minute
                        ),
                    )
                )
                if slot_start <= current_time <= slot_end:
                    return slot_start
        return None

    elif schedule.repeat_type == "daily":
        # Daily repeat - find next time slot
        # If we're on or after start_date, check today's time slots first
        # Use start_date's date if we're on the start date, otherwise use current_time's date
        if current_time.date() == start_date.date():
            # On start date - use start_date's date
            check_date = start_date.date()
        else:
            # After start date - use current_time's date
            check_date = current_time.date()

        # First, try to find a time slot on check_date that's in the future
        for slot in schedule.time_slots:
            slot_hour = int(slot["start_time"].split(":")[0])
            slot_minute = int(slot["start_time"].split(":")[1])
            slot_time = store_timezone.localize(
                datetime.combine(
                    check_date,
                    datetime.min.time().replace(hour=slot_hour, minute=slot_minute),
                )
            )
            if slot_time > current_time:
                return slot_time

        # No more slots on check_date, use first slot tomorrow
        if schedule.time_slots:
            first_slot = schedule.time_slots[0]
            tomorrow = check_date + timedelta(days=1)
            slot_hour = int(first_slot["start_time"].split(":")[0])
            slot_minute = int(first_slot["start_time"].split(":")[1])
            return store_timezone.localize(
                datetime.combine(
                    tomorrow,
                    datetime.min.time().replace(hour=slot_hour, minute=slot_minute),
                )
            )

        # Fallback: if no time slots, return None
        return None

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

        # Calculate next trigger time - always set to first time slot on start_date
        # We assume the user creates the schedule before it needs to trigger
        next_trigger = None
        if time_slots_data:
            first_slot = time_slots_data[0]
            start_date_only = start_date.date()
            slot_hour = int(first_slot["start_time"].split(":")[0])
            slot_minute = int(first_slot["start_time"].split(":")[1])
            next_trigger = store_timezone.localize(
                datetime.combine(
                    start_date_only,
                    datetime.min.time().replace(hour=slot_hour, minute=slot_minute),
                )
            )
        else:
            # No time slots, use start_date
            next_trigger = start_date

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


@router.get("/", response_model=List[PriceAdjustmentSchedule])
async def list_price_adjustments(
    store_mapping_id: Optional[UUID] = Query(
        None, description="Filter by store mapping ID"
    ),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """List price adjustment schedules, optionally filtered by store mapping and active status."""
    try:
        if store_mapping_id:
            # Get schedules for specific store mapping
            result = (
                supabase_service.client.table("price_adjustment_schedules")
                .select("*")
                .eq("store_mapping_id", str(store_mapping_id))
            )

            if is_active is not None:
                result = result.eq("is_active", is_active)

            result = result.order("created_at", desc=True).execute()

            schedules = [PriceAdjustmentSchedule(**item) for item in result.data]
        else:
            # Get all active schedules
            schedules = supabase_service.get_active_price_adjustment_schedules(
                limit=100
            )

            if is_active is not None:
                schedules = [s for s in schedules if s.is_active == is_active]

        return schedules

    except Exception as e:
        logger.error("Failed to list price adjustment schedules", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list price adjustment schedules: {str(e)}",
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


@router.put("/{schedule_id}", response_model=PriceAdjustmentSchedule)
async def update_price_adjustment(
    schedule_id: UUID,
    request: CreatePriceAdjustmentRequest,
):
    """Update a price adjustment schedule."""
    try:
        # Check if schedule exists
        existing = supabase_service.get_price_adjustment_schedule(schedule_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Price adjustment schedule not found: {schedule_id}",
            )

        # Get store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(
            request.store_mapping_id
        )
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {request.store_mapping_id}",
            )

        # Prepare update data
        update_data: Dict[str, Any] = {
            "name": request.name,
            "products": {
                "products": [
                    {
                        "pc": str(p.pc),
                        "pp": str(p.pp),
                        "original_price": p.original_price,
                    }
                    for p in request.products
                ]
            },
            "start_date": request.start_date.isoformat()
            if isinstance(request.start_date, datetime)
            else request.start_date,
            "repeat_type": request.repeat_type,
            "time_slots": [
                {"start_time": ts.start_time, "end_time": ts.end_time}
                for ts in request.time_slots
            ],
        }

        if request.end_date:
            update_data["end_date"] = (
                request.end_date.isoformat()
                if isinstance(request.end_date, datetime)
                else request.end_date
            )

        if request.trigger_days:
            update_data["trigger_days"] = request.trigger_days

        if request.trigger_stores:
            update_data["trigger_stores"] = request.trigger_stores

        # Calculate next trigger time
        store_timezone = get_store_timezone(store_mapping)
        current_time = datetime.now(store_timezone)

        # Create temporary schedule object for calculation
        temp_schedule = PriceAdjustmentSchedule(**existing.dict(), **update_data)

        next_trigger = calculate_next_trigger_time(
            temp_schedule, current_time, store_timezone
        )

        if next_trigger:
            update_data["next_trigger_at"] = next_trigger.isoformat()
            update_data["is_active"] = True
        else:
            update_data["next_trigger_at"] = None

        # Update schedule
        updated = supabase_service.update_price_adjustment_schedule(
            schedule_id, update_data
        )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update price adjustment schedule",
            )

        logger.info("Updated price adjustment schedule", schedule_id=str(schedule_id))
        return updated

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update price adjustment schedule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update price adjustment schedule: {str(e)}",
        )


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price_adjustment(schedule_id: UUID):
    """Delete (deactivate) a price adjustment schedule."""
    success = supabase_service.delete_price_adjustment_schedule(schedule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price adjustment schedule not found: {schedule_id}",
        )
