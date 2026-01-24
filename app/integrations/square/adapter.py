"""
Square integration adapter.
Implements BaseIntegrationAdapter for Square webhooks and data transformation.
"""

import hmac
import hashlib
import base64
import httpx
import os
import asyncio
from typing import List, Dict, Any, Optional
from fastapi import Request, HTTPException, status
from uuid import UUID
import structlog

from app.integrations.base import (
    BaseIntegrationAdapter,
    NormalizedProduct,
    NormalizedInventory,
)
from app.integrations.square.models import (
    CatalogVersionUpdatedWebhook,
    InventoryCountUpdatedWebhook,
    SquareCatalogObject,
)
from app.integrations.square.transformer import SquareTransformer
from app.config import settings
from app.services.supabase_service import SupabaseService
from app.models.database import Product

logger = structlog.get_logger()


class SquareIntegrationAdapter(BaseIntegrationAdapter):
    """Square integration adapter implementing BaseIntegrationAdapter."""

    def __init__(self):
        """Initialize Square adapter."""
        self.transformer = SquareTransformer()
        self.supabase_service = SupabaseService()

    def get_name(self) -> str:
        """Return integration name."""
        return "square"

    def verify_signature(
        self, payload: bytes, signature: str, headers: Dict[str, str], request_url: Optional[str] = None
    ) -> bool:
        """
        Verify Square webhook signature using HMAC SHA256.

        Args:
            payload: Raw request body bytes
            signature: x-square-hmacsha256-signature header value
            headers: Request headers
            request_url: Full request URL (optional, will construct if not provided)

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            logger.warning("No signature provided for Square webhook")
            return False

        if not settings.square_webhook_secret:
            logger.warning("SQUARE_WEBHOOK_SECRET not configured")
            # For basic version, return True if no secret configured
            return True

        try:
            # Square uses HMAC SHA256 of (notification_url + payload)
            # Square does NOT send x-square-notification-url header
            # We must use the actual request URL (from request.url)
            
            if request_url:
                # Use provided request URL
                notification_url = request_url
            else:
                # Fallback: construct from APP_BASE_URL + webhook path
                # This is less reliable but works if URL structure matches
                base_url = settings.app_base_url
                notification_url = f"{base_url}/webhooks/square"
                logger.warning(
                    "No request_url provided, using constructed URL",
                    constructed_url=notification_url,
                )

            # CRITICAL: Force HTTPS if Railway passes HTTP (SSL termination issue)
            # Square signs with HTTPS, so we must use HTTPS for verification
            if notification_url.startswith("http://"):
                notification_url = notification_url.replace("http://", "https://", 1)
                logger.info(
                    "Converted notification URL from HTTP to HTTPS for signature verification",
                    original_url=request_url,
                    converted_url=notification_url,
                )

            # Square signature = HMAC-SHA256(notification_url + payload)
            full_payload = notification_url.encode("utf-8") + payload

            calculated_hmac = base64.b64encode(
                hmac.new(
                    settings.square_webhook_secret.encode("utf-8"),
                    full_payload,
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            # Compare using secure comparison to prevent timing attacks
            return hmac.compare_digest(calculated_hmac, signature)
        except Exception as e:
            logger.error("Error verifying Square signature", error=str(e))
            return False

    def extract_store_id(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract Square merchant/location ID from webhook.

        Args:
            headers: Request headers
            payload: Webhook payload

        Returns:
            Merchant ID if found, None otherwise
        """
        return self.transformer.extract_location_id_from_webhook(headers, payload)

    def transform_product(self, raw_data: Dict[str, Any]) -> List[NormalizedProduct]:
        """
        Transform Square webhook payload to normalized products.

        Args:
            raw_data: Webhook payload dict

        Returns:
            List of normalized products
        """
        # Extract catalog object from webhook data
        data = raw_data.get("data", {})
        obj = data.get("object", {})
        catalog_object_data = obj.get("catalog_object", {})

        if not catalog_object_data:
            logger.warning("No catalog_object in webhook payload")
            return []

        # Create SquareCatalogObject from data
        catalog_object = SquareCatalogObject(**catalog_object_data)

        # Transform to normalized products
        return self.transformer.extract_variations_from_catalog_object(catalog_object)

    def transform_inventory(
        self, raw_data: Dict[str, Any]
    ) -> Optional[NormalizedInventory]:
        """
        Transform Square inventory webhook to normalized inventory.

        Args:
            raw_data: Webhook payload dict

        Returns:
            Normalized inventory or None
        """
        # For basic version, return None (inventory sync not critical)
        return None

    def validate_normalized_product(
        self, product: NormalizedProduct
    ) -> tuple[bool, List[str]]:
        """
        Validate normalized product data.

        Args:
            product: Normalized product

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        return self.transformer.validate_normalized_product(product)

    async def _fetch_measurement_units(
        self,
        access_token: str,
        measurement_unit_ids: List[str],
        base_url: str,
    ) -> Dict[str, dict]:
        """
        Fetch CatalogMeasurementUnit objects from Square API.

        Args:
            access_token: Square OAuth access token
            measurement_unit_ids: List of measurement unit IDs to fetch
            base_url: Square API base URL (sandbox or production)

        Returns:
            Dict mapping measurement_unit_id -> unit data
        """
        if not measurement_unit_ids:
            return {}

        try:
            url = f"{base_url}/v2/catalog/batch-retrieve"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "object_ids": measurement_unit_ids,
                        "include_related_objects": False,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

            cache = {}
            for obj in data.get("objects", []):
                if obj.get("type") == "MEASUREMENT_UNIT":
                    oid = obj.get("id")
                    if oid:
                        cache[oid] = {
                            "measurement_unit_data": obj.get("measurement_unit_data", {})
                        }
            logger.info(
                "Fetched measurement units from Square",
                unit_count=len(cache),
                requested_count=len(measurement_unit_ids),
            )
            return cache
        except Exception as e:
            logger.warning(
                "Failed to fetch measurement units from Square",
                error=str(e),
                unit_ids=measurement_unit_ids[:5],
            )
            return {}

    async def sync_all_products_from_square(
        self,
        merchant_id: str,
        access_token: str,
        store_mapping_id: UUID,
        base_url: str,
    ) -> Dict[str, Any]:
        """
        Fetch all products from Square Catalog API and sync to database.
        
        This function is called during initial onboarding to sync all existing
        products from Square to the database and queue them for Hipoink sync.
        
        Args:
            merchant_id: Square merchant ID
            access_token: Square OAuth access token
            store_mapping_id: Store mapping UUID
            base_url: Square API base URL (sandbox or production)
        
        Returns:
            Dict with sync statistics (total_items, products_created, products_updated, errors)
        """
        logger.info(
            "Starting initial product sync from Square",
            merchant_id=merchant_id,
            store_mapping_id=str(store_mapping_id),
        )
        
        # 1. Fetch all items with pagination
        all_items = []
        cursor = None
        page_count = 0
        
        async with httpx.AsyncClient() as client:
            while True:
                page_count += 1
                url = f"{base_url}/v2/catalog/list?types=ITEM"
                if cursor:
                    url += f"&cursor={cursor}"
                
                try:
                    response = await client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        timeout=30.0,
                    )
                    
                    if response.status_code != 200:
                        logger.error(
                            "Square API error during pagination",
                            status=response.status_code,
                            body=response.text,
                            page=page_count,
                        )
                        break
                    
                    data = response.json()
                    items = data.get("objects", [])
                    all_items.extend(items)
                    
                    logger.debug(
                        "Fetched page of items",
                        page=page_count,
                        items_in_page=len(items),
                        total_items_so_far=len(all_items),
                    )
                    
                    cursor = data.get("cursor")
                    if not cursor:
                        break  # No more pages
                    
                    # Rate limiting: wait 100ms between requests
                    await asyncio.sleep(0.1)
                    
                except httpx.TimeoutException:
                    logger.error("Timeout fetching Square catalog page", page=page_count)
                    break
                except Exception as e:
                    logger.error(
                        "Error fetching Square catalog",
                        page=page_count,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    break
        
        logger.info(
            "Finished fetching items from Square",
            total_items=len(all_items),
            total_pages=page_count,
        )
        
        if not all_items:
            return {
                "status": "success",
                "total_items": 0,
                "products_created": 0,
                "products_updated": 0,
                "queued_for_sync": 0,
                "errors": 0,
                "message": "No items found in Square catalog",
            }
        
        # 2. Collect measurement unit IDs
        measurement_unit_ids = set()
        for item in all_items:
            item_data = item.get("item_data") or {}
            variations = item_data.get("variations") or []
            for var in variations:
                var_data = var.get("item_variation_data") or {}
                unit_id = var_data.get("measurement_unit_id")
                if unit_id:
                    measurement_unit_ids.add(unit_id)
        
        # 3. Fetch measurement units in batch
        measurement_units_cache: Dict[str, dict] = {}
        if measurement_unit_ids:
            measurement_units_cache = await self._fetch_measurement_units(
                access_token=access_token,
                measurement_unit_ids=list(measurement_unit_ids),
                base_url=base_url,
            )
            logger.info(
                "Fetched measurement units",
                unit_count=len(measurement_units_cache),
                requested_count=len(measurement_unit_ids),
            )
        
        # 4. Process each item
        products_created = 0
        products_updated = 0
        errors = 0
        queued_count = 0
        
        for item in all_items:
            item_id = item.get("id")
            
            try:
                catalog_object = SquareCatalogObject(**item)
                normalized_variants = self.transformer.extract_variations_from_catalog_object(
                    catalog_object,
                    measurement_units_cache=measurement_units_cache,
                )
                
                for normalized in normalized_variants:
                    # Validate
                    is_valid, validation_errors = self.validate_normalized_product(normalized)
                    
                    # Check if product already exists
                    existing = self.supabase_service.get_product_by_source(
                        source_system="square",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                    )
                    
                    # Create or update product
                    product = Product(
                        source_system="square",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                        title=normalized.title,
                        barcode=normalized.barcode,
                        sku=normalized.sku,
                        price=normalized.price,
                        currency=normalized.currency,
                        image_url=normalized.image_url,
                        raw_data={"item_data": item},
                        normalized_data=normalized.to_dict(),
                        status="validated" if is_valid else "pending",
                        validation_errors={"errors": validation_errors} if validation_errors else None,
                    )
                    
                    saved = self.supabase_service.create_or_update_product(product)
                    
                    if existing:
                        products_updated += 1
                    else:
                        products_created += 1
                    
                    # Add to sync queue if valid
                    if is_valid and store_mapping_id:
                        try:
                            self.supabase_service.add_to_sync_queue(
                                product_id=saved.id,  # type: ignore
                                store_mapping_id=store_mapping_id,
                                operation="create",  # Use "create" for initial sync
                            )
                            queued_count += 1
                        except Exception as e:
                            logger.error(
                                "Failed to add product to sync queue",
                                product_id=str(saved.id),
                                error=str(e),
                            )
                
            except Exception as e:
                logger.error(
                    "Error processing item",
                    item_id=item_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                errors += 1
        
        logger.info(
            "Initial product sync completed",
            merchant_id=merchant_id,
            total_items=len(all_items),
            products_created=products_created,
            products_updated=products_updated,
            queued_for_sync=queued_count,
            errors=errors,
        )
        
        return {
            "status": "success",
            "total_items": len(all_items),
            "products_created": products_created,
            "products_updated": products_updated,
            "queued_for_sync": queued_count,
            "errors": errors,
        }

    def get_supported_events(self) -> List[str]:
        """Return list of supported Square webhook events."""
        return [
            "catalog.version.updated",
            "inventory.count.updated",
            "order.created",
            "order.updated",
        ]

    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle a Square webhook event.

        Args:
            event_type: Type of event (e.g., 'catalog.version.updated')
            request: FastAPI Request object
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Response dictionary
        """
        # Route to appropriate handler based on event type
        if event_type == "catalog.version.updated":
            return await self._handle_catalog_update(headers, payload)
        elif event_type == "inventory.count.updated":
            return await self._handle_inventory_update(headers, payload)
        elif event_type == "order.created" or event_type == "order.updated":
            return await self._handle_order_event(headers, payload, event_type)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported event type: {event_type}",
            )

    async def _handle_catalog_update(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle catalog update with pagination, safe token retrieval, 
        and deletion detection.
        """
        # Validate payload structure
        CatalogVersionUpdatedWebhook(**payload)

        merchant_id = self.extract_store_id(headers, payload)
        if not merchant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Merchant ID missing",
            )

        # 1. Safe Token Retrieval (Fix for Potential Crash)
        store_mapping = self.supabase_service.get_store_mapping("square", merchant_id)
        access_token = None
        store_mapping_id = None

        if store_mapping:
            store_mapping_id = store_mapping.id
            if store_mapping.metadata:
                access_token = store_mapping.metadata.get("square_access_token")
        
        # Fallback to env var if DB token is missing
        if not access_token:
            access_token = os.getenv("SQUARE_ACCESS_TOKEN")

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No access token found",
            )

        # 2. Get existing products from DB to detect deletions later
        existing_products = self.supabase_service.get_products_by_system("square")
        db_source_ids = {p.source_id for p in existing_products if p.source_id}

        # 3. Fetch EVERYTHING from Square (Handling Pagination)
        base_url = "https://connect.squareupsandbox.com" if settings.square_environment == "sandbox" else "https://connect.squareup.com"
        all_items = []
        cursor = None
        
        async with httpx.AsyncClient() as client:
            while True:
                url = f"{base_url}/v2/catalog/list?types=ITEM"
                if cursor:
                    url += f"&cursor={cursor}"
                
                response = await client.get(
                    url, 
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error("Square API Error", status=response.status_code, body=response.text)
                    break
                    
                data = response.json()
                all_items.extend(data.get("objects", []))
                
                cursor = data.get("cursor")
                if not cursor:
                    break

        # 3b. Extract measurement_unit_ids from all items and fetch CatalogMeasurementUnit objects
        measurement_unit_ids: set = set()
        for item in all_items:
            item_data = item.get("item_data") or {}
            variations = item_data.get("variations") or []
            for var in variations:
                var_data = var.get("item_variation_data") or {}
                unit_id = var_data.get("measurement_unit_id")
                if unit_id:
                    measurement_unit_ids.add(unit_id)

        measurement_units_cache: Dict[str, dict] = {}
        if measurement_unit_ids:
            measurement_units_cache = await self._fetch_measurement_units(
                access_token=access_token,
                measurement_unit_ids=list(measurement_unit_ids),
                base_url=base_url,
            )

        # 4. Process Creates and Updates
        api_source_ids = set()
        processed_products = []

        for item in all_items:
            item_id = item.get("id")
            api_source_ids.add(item_id)
            
            try:
                catalog_object = SquareCatalogObject(**item)
                normalized_variants = self.transformer.extract_variations_from_catalog_object(
                    catalog_object, measurement_units_cache=measurement_units_cache
                )

                for normalized in normalized_variants:
                    is_valid, errors = self.validate_normalized_product(normalized)
                    
                    product = Product(
                        source_system="square",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                        title=normalized.title,
                        barcode=normalized.barcode,
                        sku=normalized.sku,
                        price=normalized.price,
                        currency=normalized.currency,
                        image_url=normalized.image_url,
                        raw_data={"item_data": item},
                        normalized_data=normalized.to_dict(),
                        status="validated" if is_valid else "pending",
                        validation_errors={"errors": errors} if errors else None,
                    )

                    saved = self.supabase_service.create_or_update_product(product)
                    processed_products.append(saved)

                    # Add to sync queue for ESL update
                    if is_valid and store_mapping_id:
                        self.supabase_service.add_to_sync_queue(
                            product_id=saved.id,  # type: ignore
                            store_mapping_id=store_mapping_id,  # type: ignore
                            operation="update"
                        )
            except Exception as e:
                logger.error("Error processing item", item_id=item_id, error=str(e))

        # 5. Handle Deletions (Sync & Destroy)
        # If it's in our DB but NOT in the API response, it was deleted in Square
        deleted_source_ids = db_source_ids - api_source_ids
        for source_id in deleted_source_ids:
            prods_to_mark = [p for p in existing_products if p.source_id == source_id]
            for p in prods_to_mark:
                # 1. Update status in DB
                self.supabase_service.update_product_status(p.id, "deleted")  # type: ignore
                # 2. Tell ESL system to clear this tag
                if store_mapping_id:
                    self.supabase_service.add_to_sync_queue(
                        product_id=p.id,  # type: ignore
                        store_mapping_id=store_mapping_id,  # type: ignore
                        operation="delete"
                    )

        return {
            "status": "success",
            "updated": len(processed_products),
            "deleted": len(deleted_source_ids)
        }

    async def _handle_catalog_delete(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        store_mapping: Any,
        catalog_object_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle catalog object deletion."""
        source_id = catalog_object_data.get("id")

        if not source_id:
            return {
                "status": "success",
                "message": "No source_id in deletion payload",
                "deleted_count": 0,
            }

        # Find all products with this source_id
        products_to_delete = self.supabase_service.get_products_by_source_id(
            "square", source_id
        )

        if not products_to_delete:
            logger.info(
                "No products found for deletion",
                source_id=source_id,
            )
            return {
                "status": "success",
                "message": "No products found to delete",
                "source_id": source_id,
                "deleted_count": 0,
            }

        # Queue each product for deletion
        queued_count = 0
        for product in products_to_delete:
            if not product.id:
                continue

            try:
                self.supabase_service.add_to_sync_queue(
                    product_id=product.id,
                    store_mapping_id=store_mapping.id,
                    operation="delete",
                )
                queued_count += 1
                logger.info(
                    "Square product queued for deletion",
                    product_id=str(product.id),
                    source_id=source_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to queue product for deletion",
                    product_id=str(product.id),
                    error=str(e),
                )

        return {
            "status": "success",
            "message": f"Queued {queued_count} product(s) for deletion",
            "source_id": source_id,
            "deleted_count": queued_count,
        }

    async def _handle_inventory_update(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle inventory.count.updated webhook."""
        # Validate payload
        InventoryCountUpdatedWebhook(**payload)

        # Log inventory update (basic implementation)
        logger.info(
            "Square inventory update received",
            merchant_id=payload.get("merchant_id"),
            event_id=payload.get("event_id"),
        )

        # For basic version, just acknowledge the webhook
        return {
            "status": "success",
            "message": "Inventory update acknowledged",
        }

    async def _handle_order_event(
        self, headers: Dict[str, str], payload: Dict[str, Any], event_type: str
    ) -> Dict[str, Any]:
        """
        Handle order.created and order.updated webhooks.
        
        Currently acknowledges receipt. Future: Extract order items to update
        "Last Sold" date on ESL tags or track popularity metrics.
        """
        merchant_id = payload.get("merchant_id")
        event_id = payload.get("event_id")

        logger.info(
            "Square order webhook received",
            event_type=event_type,
            merchant_id=merchant_id,
            event_id=event_id,
        )

        # Extract order data for future use (currently just logging)
        data = payload.get("data", {})
        obj = data.get("object", {})
        order_data = obj.get("order", {})

        if order_data:
            order_id = order_data.get("id")
            location_id = order_data.get("location_id")
            # Future: Extract line items and update product last_sold timestamps

            logger.debug(
                "Order details extracted",
                order_id=order_id,
                location_id=location_id,
            )

        # Acknowledge receipt (prevents Square from retrying)
        return {
            "status": "success",
            "message": f"Order event {event_type} acknowledged",
        }