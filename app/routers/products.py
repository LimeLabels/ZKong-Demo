"""
API router for product search and retrieval.
Allows searching products from Shopify or the database.
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends
from typing import List, Optional
from pydantic import BaseModel
import structlog
import httpx

from app.services.supabase_service import SupabaseService
from app.services.shopify_api_client import ShopifyAPIClient
from app.routers.auth import verify_token

logger = structlog.get_logger()

router = APIRouter(prefix="/api/products", tags=["products"])
supabase_service = SupabaseService()


class ProductSearchResult(BaseModel):
    """Product search result model."""

    id: str
    title: str
    barcode: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    variant_id: Optional[str] = None
    product_id: Optional[str] = None


@router.get("/search", response_model=List[ProductSearchResult])
async def search_products(
    shop: str = Query(..., description="Shop domain or merchant ID"),
    source_system: str = Query("shopify", description="Source system (shopify, square, ncr)"),
    q: Optional[str] = Query(None, description="Search query (barcode, SKU, or title)"),
    limit: int = Query(20, description="Maximum number of results"),
):
    """
    Search products - filtered by merchant for multi-tenant safety.
    """
    try:
        # Get store mapping to retrieve credentials and source_store_id
        store_mapping = supabase_service.get_store_mapping(source_system, shop)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store not found: {shop}",
            )
        
        # Get products filtered by source_store_id (CRITICAL for multi-tenant)
        products = supabase_service.get_products_by_system(
            source_system=source_system,
            source_store_id=store_mapping.source_store_id,  # Multi-tenant filter
        )
        
        # Apply search filter if provided
        if q:
            q_lower = q.lower()
            products = [
                p for p in products 
                if q_lower in (p.title or "").lower() 
                or q_lower in (p.barcode or "").lower()
                or q_lower in (p.sku or "").lower()
            ]
        
        # Return results
        results = [
            ProductSearchResult(
                id=str(p.id) if p.id else "",
                title=p.title,
                barcode=p.barcode,
                sku=p.sku,
                price=p.price,
                image_url=p.image_url,
                variant_id=p.source_variant_id,
                product_id=p.source_id,
            )
            for p in products[:limit]
        ]

        # Also search Shopify API for live data (only for Shopify stores)
        if source_system == "shopify" and store_mapping.metadata:
            access_token = store_mapping.metadata.get("shopify_access_token")
            if access_token:
                try:
                    async with ShopifyAPIClient(shop, access_token) as shopify_client:
                        # Use Shopify GraphQL or REST API to search products
                        search_query = q or ""
                        api_url = f"{shopify_client.base_url}/products.json"

                        params = {"limit": min(limit, 250)}
                        if search_query:
                            params["title"] = search_query

                        async with httpx.AsyncClient() as http_client:
                            response = await http_client.get(
                                api_url,
                                headers={"X-Shopify-Access-Token": access_token},
                                params=params,
                                timeout=30.0,
                            )
                            response.raise_for_status()
                            shopify_data = response.json()

                        # Merge Shopify results (avoid duplicates)
                        existing_ids = {r.product_id for r in results if r.product_id}

                        for product in shopify_data.get("products", [])[:limit]:
                            product_id = str(product.get("id", ""))

                            # Process each variant
                            for variant in product.get("variants", []):
                                variant_id = str(variant.get("id", ""))

                                # Skip if already in results
                                if product_id in existing_ids:
                                    continue

                                # Check if matches search query
                                if q:
                                    title_match = q.lower() in product.get("title", "").lower()
                                    barcode_match = (
                                        q.lower() in (variant.get("barcode") or "").lower()
                                    )
                                    sku_match = q.lower() in (variant.get("sku") or "").lower()

                                    if not (title_match or barcode_match or sku_match):
                                        continue

                                # Add image URL
                                image_url = None
                                if product.get("images"):
                                    image_url = product["images"][0].get("src")

                                results.append(
                                    ProductSearchResult(
                                        id=f"{product_id}_{variant_id}",
                                        title=f"{product.get('title', '')} - {variant.get('title', '')}",
                                        barcode=variant.get("barcode"),
                                        sku=variant.get("sku"),
                                        price=float(variant.get("price", 0))
                                        if variant.get("price")
                                        else None,
                                        image_url=image_url,
                                        variant_id=variant_id,
                                        product_id=product_id,
                                    )
                                )

                                existing_ids.add(product_id)

                                if len(results) >= limit:
                                    break

                            if len(results) >= limit:
                                break
                except Exception as e:
                    logger.warning(
                        "Failed to search Shopify API, using database results only",
                        error=str(e),
                    )

        # Limit results
        return results[:limit]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to search products", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search products: {str(e)}",
        )


@router.get("/my-products", response_model=List[ProductSearchResult])
async def get_my_products(
    q: Optional[str] = Query(None, description="Search query (barcode, SKU, or title)"),
    limit: int = Query(20, description="Maximum number of results"),
    user_data: dict = Depends(verify_token),
):
    """
    Get products for the authenticated user's store.
    Filters products by the user's connected store mapping.
    """
    user_id = user_data["user_id"]
    
    try:
        # Get user's store mapping
        result = (
            supabase_service.client.table("store_mappings")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        
        # Find store mapping for this user
        user_store_mapping = None
        for item in result.data:
            mapping = supabase_service.get_store_mapping_by_id(item["id"])
            if (
                mapping
                and mapping.metadata
                and mapping.metadata.get("user_id") == user_id
            ):
                user_store_mapping = mapping
                break
        
        if not user_store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No store mapping found for this user. Please complete onboarding.",
            )
        
        # Get products filtered by source_system and source_store_id
        products = supabase_service.get_products_by_system(
            source_system=user_store_mapping.source_system,
            source_store_id=user_store_mapping.source_store_id,  # CRITICAL filter
        )
        
        # Apply search filter if provided
        if q:
            q_lower = q.lower()
            products = [
                p for p in products 
                if q_lower in (p.title or "").lower() 
                or q_lower in (p.barcode or "").lower()
                or q_lower in (p.sku or "").lower()
            ]
        
        return [
            ProductSearchResult(
                id=str(p.id) if p.id else "",
                title=p.title,
                barcode=p.barcode,
                sku=p.sku,
                price=p.price,
                image_url=p.image_url,
                variant_id=p.source_variant_id,
                product_id=p.source_id,
            )
            for p in products[:limit]
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user products", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user products: {str(e)}",
        )
