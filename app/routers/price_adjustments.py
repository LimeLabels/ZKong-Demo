"""
API router for Hipoink price adjustment orders.
Allows creating time-based pricing schedules for products.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from uuid import UUID
import structlog
from pydantic import BaseModel, Field

from app.services.hipoink_client import HipoinkClient, HipoinkAPIError
from app.services.supabase_service import SupabaseService
from app.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/api/price-adjustments", tags=["price-adjustments"])

# Service instances
hipoink_client = HipoinkClient(
    client_id=getattr(settings, 'hipoink_client_id', 'default')
)
supabase_service = SupabaseService()


# Request/Response Models

class PriceAdjustmentProduct(BaseModel):
    """Product data for price adjustment."""
    pc: str = Field(..., description="Product code (barcode)")
    pp: str = Field(..., description="Product price (as string)")


class CreatePriceAdjustmentRequest(BaseModel):
    """Request model for creating a price adjustment order."""
    
    store_mapping_id: UUID = Field(..., description="Store mapping UUID")
    order_number: str = Field(..., description="Price adjustment order number")
    order_name: str = Field(..., description="Price adjustment order name")
    products: List[PriceAdjustmentProduct] = Field(..., description="Products to adjust")
    trigger_stores: Optional[List[str]] = Field(None, description="Store codes to trigger (optional)")
    trigger_days: Optional[List[str]] = Field(
        None, 
        description="Days of week: ['1']=Mon, ['2']=Tue, ['3']=Wed, ['4']=Thu, ['5']=Fri, ['6']=Sat, ['7']=Sun"
    )
    start_time: Optional[str] = Field(None, description="Start time in HH:MM format (e.g., '15:00')")
    end_time: Optional[str] = Field(None, description="End time in HH:MM format (e.g., '16:00')")


class PriceAdjustmentResponse(BaseModel):
    """Response model for price adjustment order."""
    success: bool
    error_code: int
    error_msg: Optional[str] = None
    order_number: str


@router.post("/create", response_model=PriceAdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_price_adjustment(request: CreatePriceAdjustmentRequest):
    """
    Create a price adjustment order in Hipoink.
    
    This allows scheduling price changes for specific days of the week and times.
    The price will automatically adjust at the start time and restore at the end time.
    """
    try:
        # Get store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(request.store_mapping_id)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {request.store_mapping_id}",
            )
        
        # Convert products to Hipoink format
        hipoink_products = [
            {"pc": p.pc, "pp": p.pp} for p in request.products
        ]
        
        # Create price adjustment order
        response = await hipoink_client.create_price_adjustment_order(
            store_code=store_mapping.hipoink_store_code,
            order_number=request.order_number,
            order_name=request.order_name,
            products=hipoink_products,
            trigger_stores=request.trigger_stores,
            trigger_days=request.trigger_days,
            start_time=request.start_time,
            end_time=request.end_time,
        )
        
        # Check response
        error_code = response.get("error_code", 1)
        error_msg = response.get("error_msg")
        
        if error_code != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Hipoink API error: {error_msg} (code: {error_code})",
            )
        
        return PriceAdjustmentResponse(
            success=True,
            error_code=error_code,
            error_msg=error_msg,
            order_number=request.order_number,
        )
        
    except HipoinkAPIError as e:
        logger.error("Hipoink API error creating price adjustment", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hipoink API error: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create price adjustment", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create price adjustment: {str(e)}",
        )

