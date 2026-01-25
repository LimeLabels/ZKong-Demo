"""
NCR Product Sync Worker.
Polls NCR API to discover products created directly in NCR POS (MART interface).
Compares with database and syncs new/updated products.
"""

import asyncio
import structlog
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.integrations.ncr.adapter import NCRIntegrationAdapter
from app.integrations.ncr.api_client import NCRAPIClient
from app.integrations.base import NormalizedProduct
from app.models.database import StoreMapping, Product

logger = structlog.get_logger()


class NCRSyncWorker:
    """
    Worker that polls NCR API to discover products created directly in NCR POS.
    """

    def __init__(self):
        """Initialize NCR sync worker."""
        self.supabase_service = SupabaseService()
        self.running = False
        self.check_interval_seconds = 60  # Poll every 1 minute

    async def start(self):
        """Start the NCR sync worker loop."""
        self.running = True
        logger.info("NCR sync worker started", interval_seconds=self.check_interval_seconds)

        while self.running:
            try:
                await self.sync_ncr_products()
            except Exception as e:
                logger.error("Error in NCR sync worker loop", error=str(e))

            # Wait before next check
            await asyncio.sleep(self.check_interval_seconds)

    async def stop(self):
        """Stop the NCR sync worker."""
        self.running = False
        logger.info("NCR sync worker stopped")

    async def sync_ncr_products(self):
        """
        Sync products from NCR API to database.
        Fetches all items from NCR and compares with database.
        """
        try:
            # Get all NCR store mappings
            store_mappings = self.supabase_service.get_store_mappings_by_source_system("ncr")
            
            if not store_mappings:
                logger.debug("No NCR store mappings found, skipping sync")
                return

            logger.info(
                "Starting NCR product sync",
                store_mapping_count=len(store_mappings),
            )

            # Process each store mapping
            for store_mapping in store_mappings:
                try:
                    await self.sync_store_products(store_mapping)
                except Exception as e:
                    logger.error(
                        "Failed to sync products for store mapping",
                        store_mapping_id=str(store_mapping.id),
                        error=str(e),
                    )
                    # Continue with other store mappings even if one fails
                    continue

        except Exception as e:
            logger.error("Error syncing NCR products", error=str(e))

    async def sync_store_products(self, store_mapping: StoreMapping):
        """
        Sync products for a specific store mapping.

        Args:
            store_mapping: Store mapping with NCR configuration
        """
        # Extract NCR configuration from store mapping metadata
        ncr_config = store_mapping.metadata or {}
        
        # Initialize NCR API client
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Fetch all items from NCR API
            logger.info(
                "Fetching items from NCR API",
                store_mapping_id=str(store_mapping.id),
            )
            
            ncr_items = await self.fetch_all_ncr_items(api_client)
            
            logger.info(
                "Fetched items from NCR",
                store_mapping_id=str(store_mapping.id),
                item_count=len(ncr_items),
            )

            # Get existing products from database for this store
            existing_products = self.supabase_service.get_products_by_system("ncr")
            existing_item_codes = {
                p.source_id: p for p in existing_products if p.source_id
            }

            # Process each NCR item
            new_count = 0
            updated_count = 0
            
            for ncr_item in ncr_items:
                try:
                    # Extract item code (primary identifier)
                    item_code = (
                        ncr_item.get("itemId", {}).get("itemCode")
                        or ncr_item.get("itemCode")
                    )
                    
                    if not item_code:
                        logger.warning("NCR item missing itemCode", item=ncr_item)
                        continue

                    # Check if product exists in database
                    existing_product = existing_item_codes.get(item_code)
                    
                    # Transform NCR item to normalized product
                    ncr_adapter = NCRIntegrationAdapter()
                    normalized_products = ncr_adapter.transform_product(ncr_item)
                    
                    if not normalized_products:
                        logger.warning(
                            "Failed to transform NCR item",
                            item_code=item_code,
                        )
                        continue

                    normalized_product = normalized_products[0]
                    
                    # Fetch current price from NCR API (respects effectiveDate)
                    # This ensures we get the actual current price, including scheduled prices
                    try:
                        current_price_data = await api_client.get_item_price(item_code)
                        if current_price_data and "price" in current_price_data:
                            current_price = float(current_price_data["price"])
                            normalized_product.price = current_price
                        else:
                            # Fallback to price from item data if available
                            if normalized_product.price is None or normalized_product.price == 0:
                                normalized_product.price = ncr_item.get("price") or 0.0
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch price from NCR API, using item data",
                            item_code=item_code,
                            error=str(e),
                        )
                        # Fallback to price from item data if available
                        if normalized_product.price is None or normalized_product.price == 0:
                            normalized_product.price = ncr_item.get("price") or 0.0
                    
                    # Create or update product in database
                    is_new = existing_product is None
                    
                    if is_new:
                        # New product - create it
                        product = Product(
                            source_system="ncr",
                            source_id=item_code,
                            source_variant_id=normalized_product.source_variant_id,
                            title=normalized_product.title,
                            barcode=normalized_product.barcode,
                            sku=normalized_product.sku,
                            price=normalized_product.price or 0.0,
                            currency=normalized_product.currency or "USD",
                            image_url=normalized_product.image_url,
                            raw_data=ncr_item,
                            normalized_data=normalized_product.to_dict(),
                            status="validated",
                        )
                        
                        saved_product = self.supabase_service.create_or_update_product(product)
                        
                        # Queue for ESL sync
                        if saved_product.id and store_mapping.id:
                            self.supabase_service.add_to_sync_queue(
                                product_id=saved_product.id,
                                store_mapping_id=store_mapping.id,
                                operation="create",
                            )
                            new_count += 1
                            logger.info(
                                "New NCR product discovered and queued for sync",
                                item_code=item_code,
                                product_id=str(saved_product.id),
                            )
                    else:
                        # Existing product - check if it needs updating
                        # Compare key fields to see if product changed
                        needs_update = False
                        
                        if normalized_product.title != existing_product.title:
                            needs_update = True
                        if normalized_product.barcode != existing_product.barcode:
                            needs_update = True
                        if normalized_product.sku != existing_product.sku:
                            needs_update = True
                        # Check if price changed (within tolerance)
                        # This detects both scheduled price activations and manual changes
                        price_diff = abs((normalized_product.price or 0) - (existing_product.price or 0))
                        if price_diff > 0.01:
                            needs_update = True
                            logger.info(
                                "Price change detected",
                                item_code=item_code,
                                old_price=existing_product.price,
                                new_price=normalized_product.price,
                                difference=price_diff,
                            )
                        
                        if needs_update:
                            # Update product
                            existing_product.title = normalized_product.title
                            existing_product.barcode = normalized_product.barcode
                            existing_product.sku = normalized_product.sku
                            existing_product.price = normalized_product.price or 0.0
                            existing_product.currency = normalized_product.currency or "USD"
                            existing_product.image_url = normalized_product.image_url
                            existing_product.raw_data = ncr_item
                            existing_product.normalized_data = normalized_product.to_dict()
                            
                            updated_product = self.supabase_service.create_or_update_product(existing_product)
                            
                            # Queue for ESL sync
                            if updated_product.id and store_mapping.id:
                                self.supabase_service.add_to_sync_queue(
                                    product_id=updated_product.id,
                                    store_mapping_id=store_mapping.id,
                                    operation="update",
                                )
                                updated_count += 1
                                logger.info(
                                    "NCR product updated and queued for sync",
                                    item_code=item_code,
                                    product_id=str(updated_product.id),
                                )

                except Exception as e:
                    logger.error(
                        "Failed to process NCR item",
                        item_code=item_code if 'item_code' in locals() else "unknown",
                        error=str(e),
                    )
                    continue

            logger.info(
                "Completed NCR product sync for store mapping",
                store_mapping_id=str(store_mapping.id),
                new_products=new_count,
                updated_products=updated_count,
                total_items=len(ncr_items),
            )

        finally:
            await api_client.close()

    async def fetch_all_ncr_items(self, api_client: NCRAPIClient) -> List[Dict[str, Any]]:
        """
        Fetch all items from NCR API.
        Uses pagination to get all items.

        Args:
            api_client: Initialized NCR API client

        Returns:
            List of NCR item dictionaries
        """
        all_items = []
        page_number = 0
        page_size = 200  # NCR API default page size
        
        while True:
            try:
                # Use the list_items method from API client
                data = await api_client.list_items(
                    page_number=page_number,
                    page_size=page_size,
                )
                
                # Extract items from response
                # NCR API response structure: { "content": [...], "totalPages": ..., ... }
                items = data.get("content", []) or data.get("items", []) or []
                all_items.extend(items)
                
                # Check if there are more pages
                total_pages = data.get("totalPages") or data.get("total_pages")
                if total_pages and page_number >= total_pages - 1:
                    break
                
                # Check if we got fewer items than page size (last page)
                if len(items) < page_size:
                    break
                
                page_number += 1
                
            except Exception as e:
                logger.error(
                    "Error fetching NCR items",
                    page_number=page_number,
                    error=str(e),
                )
                break
        
        return all_items


async def run_ncr_sync_worker():
    """
    Main entry point for running the NCR sync worker.
    Creates an NCRSyncWorker instance and starts it.
    """
    worker = NCRSyncWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down NCR sync worker")
    finally:
        await worker.stop()

