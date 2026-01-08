"""
FastAPI router for store mapping management.
Allows creating, listing, and managing store mappings without SQL.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID
import structlog
from app.models.database import StoreMapping
from app.services.supabase_service import SupabaseService
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/store-mappings", tags=["store-mappings"])
supabase_service = SupabaseService()


class CreateStoreMappingRequest(BaseModel):
    """Request model for creating a store mapping."""

    source_system: str  # e.g., 'shopify'
    source_store_id: str  # e.g., 'your-shop.myshopify.com'
    hipoink_store_code: str  # Store code for Hipoink API (required)
    is_active: bool = True
    metadata: dict = None


class StoreMappingResponse(BaseModel):
    """Response model for store mapping."""

    id: str
    source_system: str
    source_store_id: str
    hipoink_store_code: str
    is_active: bool
    metadata: Optional[dict] = None
    created_at: str
    updated_at: str


@router.post(
    "/", response_model=StoreMappingResponse, status_code=status.HTTP_201_CREATED
)
async def create_store_mapping(request: CreateStoreMappingRequest):
    """
    Create a new store mapping.

    This allows onboarding new stores without SQL queries.
    Example: Create a mapping for your Shopify store to Hipoink ESL store.
    """
    try:
        # Check if mapping already exists
        existing = supabase_service.get_store_mapping(
            request.source_system, request.source_store_id
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Store mapping already exists for {request.source_system}:{request.source_store_id}",
            )

        # Create new mapping
        mapping = StoreMapping(
            source_system=request.source_system,
            source_store_id=request.source_store_id,
            hipoink_store_code=request.hipoink_store_code,
            is_active=request.is_active,
            metadata=request.metadata,
        )

        created = supabase_service.create_store_mapping(mapping)

        logger.info(
            "Store mapping created",
            mapping_id=str(created.id),
            source_system=request.source_system,
            source_store_id=request.source_store_id,
        )

        return StoreMappingResponse(
            id=str(created.id),
            source_system=created.source_system,
            source_store_id=created.source_store_id,
            hipoink_store_code=created.hipoink_store_code,
            is_active=created.is_active,
            metadata=created.metadata,
            created_at=created.created_at.isoformat() if created.created_at else "",
            updated_at=created.updated_at.isoformat() if created.updated_at else "",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create store mapping: {str(e)}",
        )


@router.get("/", response_model=List[StoreMappingResponse])
async def list_store_mappings(source_system: str = None, is_active: bool = None):
    """
    List all store mappings.
    Optionally filter by source_system and is_active status.
    """
    try:
        # Get all mappings from Supabase
        # Note: We'll need to add a method to list all mappings in supabase_service
        # For now, we'll query directly

        query = supabase_service.client.table("store_mappings").select("*")

        if source_system:
            query = query.eq("source_system", source_system)
        if is_active is not None:
            query = query.eq("is_active", is_active)

        result = query.order("created_at", desc=True).execute()

        mappings = [
            StoreMappingResponse(
                id=str(item["id"]),
                source_system=item["source_system"],
                source_store_id=item["source_store_id"],
                hipoink_store_code=item.get("hipoink_store_code", ""),
                is_active=item["is_active"],
                metadata=item.get("metadata"),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
            for item in result.data
        ]

        return mappings

    except Exception as e:
        logger.error("Failed to list store mappings", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list store mappings: {str(e)}",
        )


@router.get("/{mapping_id}", response_model=StoreMappingResponse)
async def get_store_mapping(mapping_id: UUID):
    """Get a specific store mapping by ID."""
    try:
        mapping = supabase_service.get_store_mapping_by_id(mapping_id)

        if not mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {mapping_id}",
            )

        return StoreMappingResponse(
            id=str(mapping.id),
            source_system=mapping.source_system,
            source_store_id=mapping.source_store_id,
            hipoink_store_code=mapping.hipoink_store_code,
            is_active=mapping.is_active,
            metadata=mapping.metadata,
            created_at=mapping.created_at.isoformat() if mapping.created_at else "",
            updated_at=mapping.updated_at.isoformat() if mapping.updated_at else "",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get store mapping: {str(e)}",
        )


@router.put("/{mapping_id}", response_model=StoreMappingResponse)
async def update_store_mapping(mapping_id: UUID, request: CreateStoreMappingRequest):
    """Update an existing store mapping."""
    try:
        # Check if exists
        existing = supabase_service.get_store_mapping_by_id(mapping_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {mapping_id}",
            )

        # Update mapping
        update_data = request.dict(exclude_none=True)
        result = (
            supabase_service.client.table("store_mappings")
            .update(update_data)
            .eq("id", str(mapping_id))
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update store mapping",
            )

        updated = StoreMapping(**result.data[0])

        return StoreMappingResponse(
            id=str(updated.id),
            source_system=updated.source_system,
            source_store_id=updated.source_store_id,
            hipoink_store_code=updated.hipoink_store_code,
            is_active=updated.is_active,
            metadata=updated.metadata,
            created_at=updated.created_at.isoformat() if updated.created_at else "",
            updated_at=updated.updated_at.isoformat() if updated.updated_at else "",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update store mapping: {str(e)}",
        )


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store_mapping(mapping_id: UUID):
    """Delete a store mapping (soft delete by setting is_active=false)."""
    try:
        existing = supabase_service.get_store_mapping_by_id(mapping_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {mapping_id}",
            )

        # Soft delete
        supabase_service.client.table("store_mappings").update({"is_active": False}).eq(
            "id", str(mapping_id)
        ).execute()

        logger.info("Store mapping deactivated", mapping_id=str(mapping_id))

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete store mapping: {str(e)}",
        )


@router.get("/current", response_model=StoreMappingResponse)
async def get_current_store_mapping(shop: str = Query(..., description="Shop domain")):
    """Get current shop's store mapping."""
    try:
        mapping = supabase_service.get_store_mapping("shopify", shop)
        if not mapping:
            mapping = supabase_service.get_store_mapping_by_shop_domain(shop)
        
        if not mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found for shop: {shop}",
            )

        return StoreMappingResponse(
            id=str(mapping.id),
            source_system=mapping.source_system,
            source_store_id=mapping.source_store_id,
            hipoink_store_code=mapping.hipoink_store_code,
            is_active=mapping.is_active,
            metadata=mapping.metadata,
            created_at=mapping.created_at.isoformat() if mapping.created_at else "",
            updated_at=mapping.updated_at.isoformat() if mapping.updated_at else "",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get current store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get current store mapping: {str(e)}",
        )
