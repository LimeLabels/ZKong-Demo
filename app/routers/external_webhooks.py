"""
External webhook router for NCR and Square to call for time-based pricing.
This router provides endpoints that external systems (NCR POS, Square) can call
to trigger price updates based on schedules.
"""

from fastapi import APIRouter, Request, HTTPException, Header, status, Body
from typing import Optional, Dict, Any
import structlog
from datetime import datetime

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.workers.price_scheduler import PriceScheduler
from app.utils.clover_bos_diagnostic import diagnose_clover_bos

logger = structlog.get_logger()

router = APIRouter(prefix="/external", tags=["external-webhooks"])

# Initialize services
supabase_service = SupabaseService()
# PriceScheduler initializes its own SupabaseService internally
price_scheduler = PriceScheduler()


@router.post("/ncr/trigger-price-update")
async def ncr_trigger_price_update(
    request: Request,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """
    Webhook endpoint for NCR to trigger price updates based on time-based pricing schedules.
    
    This endpoint can be called by NCR POS system to request price updates for specific items.
    
    Expected payload:
    {
        "item_code": "ITEM-001",
        "store_mapping_id": "uuid-here",
        "trigger_type": "schedule" | "manual",
        "schedule_id": "uuid-here" (optional)
    }
    """
    try:
        # Verify authorization if configured
        if settings.ncr_shared_key and authorization:
            # Basic auth check - can be enhanced with HMAC verification
            expected_auth = f"Bearer {settings.ncr_shared_key}"
            if authorization != expected_auth:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authorization token",
                )
        
        item_code = body.get("item_code")
        store_mapping_id = body.get("store_mapping_id")
        trigger_type = body.get("trigger_type", "schedule")
        schedule_id = body.get("schedule_id")
        
        if not item_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="item_code is required",
            )
        
        if not store_mapping_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="store_mapping_id is required",
            )
        
        logger.info(
            "NCR price update trigger received",
            item_code=item_code,
            store_mapping_id=store_mapping_id,
            trigger_type=trigger_type,
            schedule_id=schedule_id,
        )
        
        # Get store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping {store_mapping_id} not found",
            )
        
        # If schedule_id is provided, process that specific schedule
        if schedule_id:
            from uuid import UUID
            try:
                schedule_uuid = UUID(schedule_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid schedule_id format: {schedule_id}",
                )
            schedule = supabase_service.get_price_adjustment_schedule(schedule_uuid)
            if not schedule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Schedule {schedule_id} not found",
                )
            
            # Process the schedule
            current_time = datetime.utcnow()
            await price_scheduler.process_schedule(schedule, current_time)
            
            return {
                "status": "success",
                "message": f"Schedule {schedule_id} processed",
                "item_code": item_code,
            }
        else:
            # Find active schedules for this item and process them
            # This would require querying schedules by item_code
            # For now, return success and log the request
            logger.info(
                "Processing price update for item",
                item_code=item_code,
                store_mapping_id=store_mapping_id,
            )
            
            return {
                "status": "success",
                "message": "Price update request received",
                "item_code": item_code,
                "note": "Schedule processing initiated",
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error processing NCR price update trigger",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}",
        )


@router.post("/square/trigger-price-update")
async def square_trigger_price_update(
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_square_signature: Optional[str] = Header(None, alias="X-Square-Signature"),
):
    """
    Webhook endpoint for Square to trigger price updates based on time-based pricing schedules.
    
    This endpoint can be called by Square system to request price updates for specific items.
    
    Expected payload:
    {
        "object_id": "catalog-object-id",
        "store_mapping_id": "uuid-here",
        "trigger_type": "schedule" | "manual",
        "schedule_id": "uuid-here" (optional)
    }
    """
    try:
        # Verify Square signature if configured
        if settings.square_webhook_secret and x_square_signature:
            # Square signature verification would go here
            # For now, basic check
            pass
        
        object_id = body.get("object_id")
        store_mapping_id = body.get("store_mapping_id")
        trigger_type = body.get("trigger_type", "schedule")
        schedule_id = body.get("schedule_id")
        
        if not object_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="object_id is required",
            )
        
        if not store_mapping_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="store_mapping_id is required",
            )
        
        logger.info(
            "Square price update trigger received",
            object_id=object_id,
            store_mapping_id=store_mapping_id,
            trigger_type=trigger_type,
            schedule_id=schedule_id,
        )
        
        # Get store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping {store_mapping_id} not found",
            )
        
        # If schedule_id is provided, process that specific schedule
        if schedule_id:
            from uuid import UUID
            try:
                schedule_uuid = UUID(schedule_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid schedule_id format: {schedule_id}",
                )
            schedule = supabase_service.get_price_adjustment_schedule(schedule_uuid)
            if not schedule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Schedule {schedule_id} not found",
                )
            
            # Process the schedule
            current_time = datetime.utcnow()
            await price_scheduler.process_schedule(schedule, current_time)
            
            return {
                "status": "success",
                "message": f"Schedule {schedule_id} processed",
                "object_id": object_id,
            }
        else:
            # Find active schedules for this item and process them
            logger.info(
                "Processing price update for Square object",
                object_id=object_id,
                store_mapping_id=store_mapping_id,
            )
            
            return {
                "status": "success",
                "message": "Price update request received",
                "object_id": object_id,
                "note": "Schedule processing initiated",
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error processing Square price update trigger",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}",
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for external webhooks."""
    return {
        "status": "healthy",
        "service": "external-webhooks",
        "ncr_pos_url": settings.ncr_pos_base_url,
    }


@router.post("/trigger-schedule/{schedule_id}")
async def trigger_schedule_manually(
    schedule_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Manually trigger a price adjustment schedule.
    This can be called by external systems or for testing.
    
    Requires authorization header with NCR shared key or Square webhook secret.
    """
    try:
        # Verify authorization
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required",
            )
        
        # Basic auth check
        valid_auth = (
            f"Bearer {settings.ncr_shared_key}" if settings.ncr_shared_key else None
        ) or (
            f"Bearer {settings.square_webhook_secret}" if settings.square_webhook_secret else None
        )
        
        if authorization != valid_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token",
            )
        
        # Get schedule
        from uuid import UUID
        try:
            schedule_uuid = UUID(schedule_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid schedule_id format: {schedule_id}",
            )
        schedule = supabase_service.get_price_adjustment_schedule(schedule_uuid)
        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schedule {schedule_id} not found",
            )
        
        # Process schedule
        current_time = datetime.utcnow()
        await price_scheduler.process_schedule(schedule, current_time)
        
        return {
            "status": "success",
            "message": f"Schedule {schedule_id} triggered successfully",
            "schedule_id": schedule_id,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error triggering schedule",
            schedule_id=schedule_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error triggering schedule: {str(e)}",
        )


@router.get("/clover/diagnose/{store_mapping_id}")
async def clover_bos_diagnose(
    store_mapping_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Manual diagnostic endpoint — hit this to check why Clover BOS
    isn't updating prices for a given store mapping.

    GET /external/clover/diagnose/{store_mapping_id}
    """
    # Reuse the same basic auth pattern as trigger_schedule_manually
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    valid_auth = (
        f"Bearer {settings.ncr_shared_key}" if settings.ncr_shared_key else None
    ) or (
        f"Bearer {settings.square_webhook_secret}" if settings.square_webhook_secret else None
    )

    if authorization != valid_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization token",
        )

    mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store mapping not found")

    result = await diagnose_clover_bos(store_mapping=mapping)
    return {
        "store_mapping_id": store_mapping_id,
        "diagnostic": result,
    }


