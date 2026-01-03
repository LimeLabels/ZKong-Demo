"""
API router for time-based pricing strategies.
Allows clients to create and manage pricing strategies for ZKong ESL system.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from datetime import datetime
from uuid import UUID
import structlog
from pydantic import BaseModel, Field

from app.services.strategy_service import StrategyService
from app.services.zkong_client import ZKongClient
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# Service instances
strategy_service = StrategyService()
zkong_client = ZKongClient()
supabase_service = SupabaseService()


# Request/Response Models


class ProductStrategyConfig(BaseModel):
    """Product configuration for strategy."""

    barcode: Optional[str] = Field(None, description="Product barcode (required if item_id not provided)")
    item_id: Optional[int] = Field(None, description="ZKong itemId (required if barcode not provided, for testing)")
    price: Optional[str] = Field(None, description="Activity price")
    member_price: Optional[str] = Field(None, description="Activity member price")
    original_price: Optional[str] = Field(None, description="Original price")
    promotion_text: Optional[str] = Field(None, description="Promotional text")
    unit: Optional[str] = Field(None, description="Sales unit")
    class_level: Optional[str] = Field(None, description="Product level")
    product_area: Optional[str] = Field(None, description="Origin")
    period_times: Optional[List[str]] = Field(
        None, description="Time windows for this product (HH:mm:ss format)"
    )
    cust_features: Optional[dict] = Field(
        None, description="Custom features (custFeature1-15)"
    )


class CreateStrategyRequest(BaseModel):
    """Request to create a new pricing strategy."""

    store_mapping_id: UUID = Field(..., description="Store mapping ID")
    name: str = Field(..., description="Strategy name")
    start_date: datetime = Field(..., description="Strategy start date")
    end_date: datetime = Field(..., description="Strategy end date")
    trigger_type: int = Field(
        ..., description="Trigger method: 1=Fixed period, 2=Always triggered"
    )
    period_type: int = Field(
        ..., description="Trigger cycle: 0=Daily, 1=Weekly, 2=Monthly"
    )
    period_value: List[int] = Field(..., description="Period value array")
    period_times: List[str] = Field(
        ...,
        description="Time windows (HH:mm:ss format, e.g., ['10:00:00', '22:00:00'])",
    )
    products: List[ProductStrategyConfig] = Field(
        ..., description="Products in strategy"
    )
    template_attr_category: str = Field(
        default="default", description="Template classification"
    )
    template_attr: str = Field(default="default", description="Template properties")
    select_field_name_num: Optional[List[int]] = Field(
        None,
        description="Optional field array (0-19), max 5 selections. "
        "0=sales unit, 1=Product level, 2=Origin, 3=Original price, etc.",
    )
    use_external_store_id: bool = Field(
        default=False, description="Use external store ID"
    )
    external_store_id: Optional[str] = Field(None, description="External store ID")


class StrategyResponse(BaseModel):
    """Response after creating a strategy."""

    success: bool
    message: str
    strategy_id: Optional[str] = None
    code: Optional[int] = None
    data: Optional[dict] = None


@router.post(
    "/create", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED
)
async def create_strategy(request: CreateStrategyRequest):
    """
    Create a new time-based pricing strategy.

    This endpoint creates a pricing strategy in ZKong that will automatically
    apply pricing rules based on time schedules (daily, weekly, or monthly).

    Example:
        - Daily happy hour: 5pm-7pm every day
        - Weekend sale: Saturday-Sunday, 10am-10pm
        - Monthly promotion: 1st-15th of month, all day
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

        if not store_mapping.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Store mapping is not active",
            )

        # Validate dates
        if request.start_date >= request.end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before end_date",
            )

        # Validate period_times format
        for time_str in request.period_times:
            try:
                parts = time_str.split(":")
                if len(parts) != 3:
                    raise ValueError
                int(parts[0])  # hour
                int(parts[1])  # minute
                int(parts[2])  # second
            except (ValueError, IndexError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid time format: {time_str}. Expected HH:mm:ss",
                )

        # Validate trigger_type
        if request.trigger_type not in [1, 2]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trigger_type must be 1 (Fixed period) or 2 (Always triggered)",
            )

        # Validate period_type
        if request.period_type not in [0, 1, 2]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="period_type must be 0 (Daily), 1 (Weekly), or 2 (Monthly)",
            )

        # Validate period_value based on period_type
        if request.period_type == 0:  # Daily
            if request.period_value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="period_value must be empty array for Daily (period_type=0)",
                )
        elif request.period_type == 1:  # Weekly
            if not all(1 <= v <= 7 for v in request.period_value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="period_value for Weekly must contain values 1-7 (1=Sunday, 7=Saturday)",
                )
        elif request.period_type == 2:  # Monthly
            if not all(1 <= v <= 31 for v in request.period_value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="period_value for Monthly must contain values 1-31 (day of month)",
                )

        # Convert products to dict format
        products_dict = [product.model_dump() for product in request.products]

        # Create strategy request
        # Note: period_times are assumed to be in client's local timezone (CT)
        # Strategy service will convert them to UTC for ZKong
        strategy_request = strategy_service.create_strategy_request(
            store_mapping=store_mapping,
            name=request.name,
            start_date=request.start_date,
            end_date=request.end_date,
            trigger_type=request.trigger_type,
            period_type=request.period_type,
            period_value=request.period_value,
            period_times=request.period_times,
            products=products_dict,
            template_attr_category=request.template_attr_category,
            template_attr=request.template_attr,
            select_field_name_num=request.select_field_name_num or [],
        )

        # Call ZKong API
        response = await zkong_client.create_strategy(
            strategy=strategy_request,
            use_external_store_id=request.use_external_store_id,
            external_store_id=request.external_store_id,
        )

        # Extract strategy ID from response if available
        strategy_id = None
        if response.data:
            # Handle different response formats
            if isinstance(response.data, dict):
                strategy_id = response.data.get("strategy_id") or response.data.get("strategyId") or response.data.get("id")
            elif isinstance(response.data, (int, str)):
                # Data might be the strategy ID directly
                strategy_id = str(response.data)

        logger.info(
            "Strategy created successfully",
            strategy_name=request.name,
            store_mapping_id=str(request.store_mapping_id),
            code=response.code,
        )

        return StrategyResponse(
            success=response.code == 200 or response.success is True,
            message=response.message,
            strategy_id=str(strategy_id) if strategy_id else None,
            code=response.code,
            data=response.data,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Failed to create strategy", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create strategy: {str(e)}",
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for strategies."""
    return {"status": "healthy", "service": "strategies"}
