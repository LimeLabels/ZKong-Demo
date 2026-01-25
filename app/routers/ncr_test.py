"""
NCR POS integration test router.
Provides endpoints to test NCR API calls against a local demo store.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
import structlog

from app.config import settings
from app.integrations.ncr.api_client import NCRAPIClient
from app.integrations.ncr.adapter import NCRIntegrationAdapter
from app.integrations.base import NormalizedProduct
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()
supabase_service = SupabaseService()

router = APIRouter(prefix="/api/ncr", tags=["NCR Integration"])


class CreateProductRequest(BaseModel):
    """Request model for creating a product."""
    item_code: str
    title: str
    price: Optional[float] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    department_id: Optional[str] = None
    category_id: Optional[str] = None
    store_mapping_id: Optional[str] = None  # Optional: if provided, will save to Supabase and queue for ESL


class CreateProductWithSyncRequest(BaseModel):
    """Request model for creating a product with Supabase/ESL sync."""
    item_code: str
    title: str
    price: Optional[float] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    department_id: Optional[str] = None
    category_id: Optional[str] = None
    store_mapping_id: str  # Required for sync


class UpdatePriceRequest(BaseModel):
    """Request model for updating a product price."""
    item_code: str
    price: float
    price_code: str = "REGULAR"
    currency: str = "USD"
    store_mapping_id: Optional[str] = None  # Optional: if provided, will save to Supabase and queue for ESL


class DeleteProductRequest(BaseModel):
    """Request model for deleting a product."""
    item_code: str
    department_id: Optional[str] = None
    category_id: Optional[str] = None
    store_mapping_id: Optional[str] = None  # Optional: if provided, will sync to database and ESL


@router.get("/config")
async def get_ncr_config():
    """Get current NCR configuration (for debugging)."""
    return {
        "base_url": settings.ncr_api_base_url,
        "organization": settings.ncr_organization or "(not set)",
        "enterprise_unit": settings.ncr_enterprise_unit or "(not set)",
        "department_id": settings.ncr_department_id,
        "category_id": settings.ncr_category_id,
        "has_shared_key": bool(settings.ncr_shared_key),
        "has_secret_key": bool(settings.ncr_secret_key),
    }


@router.post("/test/create-product")
async def test_create_product(request: CreateProductRequest):
    """
    Test creating a product in NCR.
    
    If store_mapping_id is provided, the product will also be:
    - Normalized and saved to Supabase
    - Queued for ESL (Hipoink) sync
    
    This endpoint calls the NCR API to create a product.
    """
    logger.info(
        "Testing NCR create product",
        item_code=request.item_code,
        title=request.title,
        store_mapping_id=request.store_mapping_id,
    )

    # If store_mapping_id is provided, use the adapter (includes Supabase/ESL sync)
    if request.store_mapping_id:
        try:
            # Get store mapping
            store_mapping = supabase_service.get_store_mapping_by_id(request.store_mapping_id)
            if not store_mapping:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Store mapping {request.store_mapping_id} not found",
                )
            
            # Create normalized product
            normalized_product = NormalizedProduct(
                source_id=request.item_code,
                title=request.title,
                barcode=request.barcode,
                sku=request.sku,
                price=request.price or 0.0,
                currency="USD",
            )
            
            # Use adapter to create product (includes NCR API + Supabase + ESL queue)
            adapter = NCRIntegrationAdapter()
            result = await adapter.create_product(
                normalized_product=normalized_product,
                store_mapping_config={
                    "id": store_mapping.id,
                    "metadata": store_mapping.metadata or {},
                },
            )
            
            logger.info("NCR create product with sync successful", result=result)
            return {
                "status": "success",
                "message": "Product created in NCR, saved to Supabase, and queued for ESL sync",
                "result": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error("NCR create product with sync failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create product: {str(e)}",
            )
    
    # Otherwise, just create in NCR directly (no Supabase/ESL sync)
    api_client = NCRAPIClient(
        base_url=settings.ncr_api_base_url,
        shared_key=settings.ncr_shared_key or None,
        secret_key=settings.ncr_secret_key or None,
        organization=settings.ncr_organization or None,
        enterprise_unit=settings.ncr_enterprise_unit or None,
    )

    try:
        result = await api_client.create_product(
            item_code=request.item_code,
            title=request.title,
            department_id=request.department_id or settings.ncr_department_id,
            category_id=request.category_id or settings.ncr_category_id,
            price=request.price,
            sku=request.sku,
            barcode=request.barcode,
        )

        logger.info("NCR create product successful", result=result)
        return {
            "status": "success",
            "message": "Product created successfully in NCR (not synced to Supabase/ESL)",
            "result": result,
            "note": "Provide store_mapping_id to enable Supabase/ESL sync",
        }

    except Exception as e:
        logger.error("NCR create product failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create product: {str(e)}",
        )
    finally:
        await api_client.close()


@router.post("/test/update-price")
async def test_update_price(request: UpdatePriceRequest):
    """
    Test updating a product price in NCR.
    
    If store_mapping_id is provided, the price update will also:
    - Update the product in Supabase database
    - Queue for ESL (Hipoink) sync
    
    This endpoint calls the NCR API to update a product's price.
    """
    logger.info(
        "Testing NCR update price",
        item_code=request.item_code,
        price=request.price,
        store_mapping_id=request.store_mapping_id,
    )

    # If store_mapping_id is provided, use the adapter (includes Supabase/ESL sync)
    if request.store_mapping_id:
        try:
            # Get store mapping
            store_mapping = supabase_service.get_store_mapping_by_id(request.store_mapping_id)
            if not store_mapping:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Store mapping {request.store_mapping_id} not found",
                )
            
            # Use adapter to update price (includes NCR API + Supabase + ESL queue)
            adapter = NCRIntegrationAdapter()
            result = await adapter.update_price(
                item_code=request.item_code,
                price=request.price,
                store_mapping_config={
                    "id": store_mapping.id,
                    "metadata": store_mapping.metadata or {},
                },
            )
            
            logger.info("NCR update price with sync successful", result=result)
            return {
                "status": "success",
                "message": "Price updated in NCR, saved to Supabase, and queued for ESL sync",
                "result": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error("NCR update price with sync failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update price: {str(e)}",
            )
    
    # Otherwise, just update price in NCR directly (no Supabase/ESL sync)
    if not settings.ncr_enterprise_unit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NCR_ENTERPRISE_UNIT must be set for price updates (or provide store_mapping_id)",
        )

    api_client = NCRAPIClient(
        base_url=settings.ncr_api_base_url,
        shared_key=settings.ncr_shared_key or None,
        secret_key=settings.ncr_secret_key or None,
        organization=settings.ncr_organization or None,
        enterprise_unit=settings.ncr_enterprise_unit,
    )

    try:
        result = await api_client.update_price(
            item_code=request.item_code,
            price=request.price,
            price_code=request.price_code,
            currency=request.currency,
        )

        logger.info("NCR update price successful", result=result)
        return {
            "status": "success",
            "message": "Price updated successfully in NCR (not synced to Supabase/ESL)",
            "result": result,
            "note": "Provide store_mapping_id to enable Supabase/ESL sync",
        }

    except Exception as e:
        logger.error("NCR update price failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update price: {str(e)}",
        )
    finally:
        await api_client.close()


@router.post("/test/delete-product")
async def test_delete_product(request: DeleteProductRequest):
    """
    Test deleting a product in NCR (sets status to INACTIVE).
    
    If store_mapping_id is provided, the deletion will also:
    - Queue product deletion in Supabase database
    - Queue for ESL (Hipoink) sync
    
    This endpoint calls the NCR API to mark a product as INACTIVE.
    """
    logger.info(
        "Testing NCR delete product",
        item_code=request.item_code,
        store_mapping_id=request.store_mapping_id,
    )

    # If store_mapping_id is provided, use the adapter (includes Supabase/ESL sync)
    if request.store_mapping_id:
        try:
            # Get store mapping
            store_mapping = supabase_service.get_store_mapping_by_id(request.store_mapping_id)
            if not store_mapping:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Store mapping {request.store_mapping_id} not found",
                )
            
            # Use adapter to delete product (includes NCR API + Supabase + ESL queue)
            adapter = NCRIntegrationAdapter()
            result = await adapter.delete_product(
                item_code=request.item_code,
                store_mapping_config={
                    "id": store_mapping.id,
                    "metadata": store_mapping.metadata or {},
                },
            )
            
            logger.info("NCR delete product with sync successful", result=result)
            return {
                "status": "success",
                "message": "Product deleted in NCR, queued for database deletion and ESL sync",
                "result": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error("NCR delete product with sync failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete product: {str(e)}",
            )
    
    # Otherwise, just delete in NCR directly (no Supabase/ESL sync)
    api_client = NCRAPIClient(
        base_url=settings.ncr_api_base_url,
        shared_key=settings.ncr_shared_key or None,
        secret_key=settings.ncr_secret_key or None,
        organization=settings.ncr_organization or None,
        enterprise_unit=settings.ncr_enterprise_unit or None,
    )

    try:
        result = await api_client.delete_product(
            item_code=request.item_code,
            department_id=request.department_id or settings.ncr_department_id,
            category_id=request.category_id or settings.ncr_category_id,
        )

        logger.info("NCR delete product successful", result=result)
        return {
            "status": "success",
            "message": "Product deleted (set to INACTIVE) in NCR (not synced to Supabase/ESL)",
            "result": result,
            "note": "Provide store_mapping_id to enable Supabase/ESL sync",
        }

    except Exception as e:
        logger.error("NCR delete product failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete product: {str(e)}",
        )
    finally:
        await api_client.close()


@router.get("/test/health")
async def test_ncr_health():
    """
    Test connectivity to the NCR API.
    
    Makes a simple GET request to check if the NCR API is reachable.
    """
    import httpx

    logger.info("Testing NCR API connectivity", base_url=settings.ncr_api_base_url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to hit the base URL or a health endpoint
            response = await client.get(settings.ncr_api_base_url)
            
            return {
                "status": "success",
                "message": "NCR API is reachable",
                "base_url": settings.ncr_api_base_url,
                "response_status": response.status_code,
            }

    except httpx.ConnectError as e:
        logger.warning("NCR API not reachable", error=str(e))
        return {
            "status": "error",
            "message": "NCR API is not reachable",
            "base_url": settings.ncr_api_base_url,
            "error": str(e),
        }
    except Exception as e:
        logger.error("NCR health check failed", error=str(e))
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "base_url": settings.ncr_api_base_url,
        }

