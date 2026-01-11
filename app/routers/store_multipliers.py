"""
API router for store-wide price multipliers.
Allows applying percentage multipliers to all products in a store.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from uuid import UUID
import structlog
from pydantic import BaseModel, Field

from app.models.database import StoreMultiplier
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/store-multipliers", tags=["store-multipliers"])
supabase_service = SupabaseService()


# Request/Response Models
class CreateStoreMultiplierRequest(BaseModel):
    """Request model for creating a store multiplier."""

    store_mapping_id: UUID = Field(..., description="Store mapping UUID")
    multiplier_percentage: float = Field(
        ...,
        description="Percentage multiplier (e.g., 10.0 for 10% increase, -5.0 for 5% decrease)",
    )
    name: Optional[str] = Field(None, description="Optional name/description")
    product_selection: Optional[Dict[str, Any]] = Field(
        None,
        description="Filter criteria for products (e.g., {'source_system': 'shopify'})",
    )
    formula: Optional[str] = Field(
        None,
        description="Custom formula for price modification (defaults to: price * (1 + multiplier_percentage / 100))",
    )
    is_active: bool = Field(True, description="Whether multiplier is active")


class StoreMultiplierResponse(BaseModel):
    """Response model for store multiplier."""

    id: UUID
    store_mapping_id: UUID
    multiplier_percentage: float
    name: Optional[str] = None
    product_selection: Optional[Dict[str, Any]] = None
    formula: Optional[str] = None
    is_active: bool
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.post(
    "/",
    response_model=StoreMultiplierResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_multiplier(request: CreateStoreMultiplierRequest):
    """
    Create a store-wide price multiplier.

    This applies a percentage multiplier to all products (or filtered products) in a store.
    The multiplier is applied when syncing products to Hipoink.
    """
    try:
        # Validate store mapping exists
        store_mapping = supabase_service.get_store_mapping_by_id(
            request.store_mapping_id
        )
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {request.store_mapping_id}",
            )

        # Default formula if not provided
        formula = request.formula
        if not formula:
            formula = "price * (1 + multiplier_percentage / 100)"

        # Create multiplier
        multiplier = StoreMultiplier(
            store_mapping_id=request.store_mapping_id,
            multiplier_percentage=request.multiplier_percentage,
            name=request.name,
            product_selection=request.product_selection,
            formula=formula,
            is_active=request.is_active,
        )

        created = supabase_service.create_store_multiplier(multiplier)

        logger.info(
            "Created store multiplier",
            multiplier_id=str(created.id),
            store_mapping_id=str(request.store_mapping_id),
            multiplier_percentage=request.multiplier_percentage,
        )

        return StoreMultiplierResponse(
            id=created.id,  # type: ignore
            store_mapping_id=created.store_mapping_id,
            multiplier_percentage=created.multiplier_percentage,
            name=created.name,
            product_selection=created.product_selection,
            formula=created.formula,
            is_active=created.is_active,
            metadata=created.metadata,
            created_at=created.created_at.isoformat() if created.created_at else None,
            updated_at=created.updated_at.isoformat() if created.updated_at else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create store multiplier", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create store multiplier: {str(e)}",
        )


@router.get("/", response_model=List[StoreMultiplierResponse])
async def list_store_multipliers(
    store_mapping_id: Optional[UUID] = Query(
        None, description="Filter by store mapping ID"
    ),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """List store multipliers, optionally filtered by store mapping and active status."""
    try:
        multipliers = supabase_service.get_store_multipliers(
            store_mapping_id=store_mapping_id, is_active=is_active
        )

        return [
            StoreMultiplierResponse(
                id=m.id,  # type: ignore
                store_mapping_id=m.store_mapping_id,
                multiplier_percentage=m.multiplier_percentage,
                name=m.name,
                product_selection=m.product_selection,
                formula=m.formula,
                is_active=m.is_active,
                metadata=m.metadata,
                created_at=m.created_at.isoformat() if m.created_at else None,
                updated_at=m.updated_at.isoformat() if m.updated_at else None,
            )
            for m in multipliers
        ]

    except Exception as e:
        logger.error("Failed to list store multipliers", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list store multipliers: {str(e)}",
        )


@router.get("/{multiplier_id}", response_model=StoreMultiplierResponse)
async def get_store_multiplier(multiplier_id: UUID):
    """Get a store multiplier by ID."""
    multiplier = supabase_service.get_store_multiplier(multiplier_id)
    if not multiplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store multiplier not found: {multiplier_id}",
        )

    return StoreMultiplierResponse(
        id=multiplier.id,  # type: ignore
        store_mapping_id=multiplier.store_mapping_id,
        multiplier_percentage=multiplier.multiplier_percentage,
        name=multiplier.name,
        product_selection=multiplier.product_selection,
        formula=multiplier.formula,
        is_active=multiplier.is_active,
        metadata=multiplier.metadata,
        created_at=multiplier.created_at.isoformat() if multiplier.created_at else None,
        updated_at=multiplier.updated_at.isoformat() if multiplier.updated_at else None,
    )


@router.put("/{multiplier_id}", response_model=StoreMultiplierResponse)
async def update_store_multiplier(
    multiplier_id: UUID, request: CreateStoreMultiplierRequest
):
    """Update a store multiplier."""
    try:
        # Check if exists
        existing = supabase_service.get_store_multiplier(multiplier_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store multiplier not found: {multiplier_id}",
            )

        # Validate store mapping exists
        store_mapping = supabase_service.get_store_mapping_by_id(
            request.store_mapping_id
        )
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {request.store_mapping_id}",
            )

        # Default formula if not provided
        formula = request.formula
        if not formula:
            formula = "price * (1 + multiplier_percentage / 100)"

        # Prepare update data
        update_data: Dict[str, Any] = {
            "store_mapping_id": str(request.store_mapping_id),
            "multiplier_percentage": request.multiplier_percentage,
            "name": request.name,
            "product_selection": request.product_selection,
            "formula": formula,
            "is_active": request.is_active,
        }

        updated = supabase_service.update_store_multiplier(multiplier_id, update_data)

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update store multiplier",
            )

        logger.info("Updated store multiplier", multiplier_id=str(multiplier_id))

        return StoreMultiplierResponse(
            id=updated.id,  # type: ignore
            store_mapping_id=updated.store_mapping_id,
            multiplier_percentage=updated.multiplier_percentage,
            name=updated.name,
            product_selection=updated.product_selection,
            formula=updated.formula,
            is_active=updated.is_active,
            metadata=updated.metadata,
            created_at=updated.created_at.isoformat() if updated.created_at else None,
            updated_at=updated.updated_at.isoformat() if updated.updated_at else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update store multiplier", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update store multiplier: {str(e)}",
        )


@router.delete("/{multiplier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store_multiplier(multiplier_id: UUID):
    """Delete (deactivate) a store multiplier."""
    success = supabase_service.delete_store_multiplier(multiplier_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store multiplier not found: {multiplier_id}",
        )
    logger.info("Deleted store multiplier", multiplier_id=str(multiplier_id))
    return None
