"""
API router for product search and retrieval.
Allows searching products from Shopify or the database.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from pydantic import BaseModel
import structlog
import httpx

from app.services.supabase_service import SupabaseService
from app.services.shopify_api_client import ShopifyAPIClient

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
    shop: str = Query(..., description="Shop domain"),
    q: Optional[str] = Query(None, description="Search query (barcode, SKU, or title)"),
    limit: int = Query(20, description="Maximum number of results"),
):
    """
    Search products from Shopify or database.
    Searches by barcode, SKU, or product title.
    """
    try:
        # Get store mapping to retrieve Shopify credentials
        store_mapping = supabase_service.get_store_mapping("shopify", shop)
        if not store_mapping:
            store_mapping = supabase_service.get_store_mapping_by_shop_domain(shop)

        if not store_mapping or not store_mapping.metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found for shop: {shop}",
            )

        access_token = store_mapping.metadata.get("shopify_access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Shopify access token not found. Please complete OAuth flow.",
            )

        # Search in database first (faster)
        results = []

        if q:
            # Search database by title (case-insensitive)
            # Supabase Python client uses ilike for case-insensitive search
            db_results = (
                supabase_service.client.table("products")
                .select("*")
                .ilike("title", f"%{q}%")
                .limit(limit)
                .execute()
            )

            for item in db_results.data:
                results.append(
                    ProductSearchResult(
                        id=item.get("id", ""),
                        title=item.get("title", ""),
                        barcode=item.get("barcode"),
                        sku=item.get("sku"),
                        price=item.get("price"),
                        image_url=item.get("image_url"),
                        variant_id=item.get("source_variant_id"),
                        product_id=item.get("source_id"),
                    )
                )

        # Also search Shopify API for live data
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
