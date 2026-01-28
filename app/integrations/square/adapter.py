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
from typing import List, Dict, Any, Optional, Tuple
from fastapi import Request, HTTPException, status
from uuid import UUID, uuid4
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
from app.services.slack_service import get_slack_service
from app.models.database import Product, StoreMapping

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

    async def _ensure_valid_token(
        self, store_mapping: StoreMapping
    ) -> Optional[str]:
        """
        Ensure store mapping has a valid, non-expiring access token.
        Refreshes token if expiring soon.

        Args:
            store_mapping: Store mapping to check/refresh token for

        Returns:
            Valid access token or None if refresh failed
        """
        from app.integrations.square.token_refresh import SquareTokenRefreshService

        token_refresh_service = SquareTokenRefreshService()

        # Check if token is expiring soon
        expires_at = None
        if store_mapping.metadata:
            expires_at = store_mapping.metadata.get("square_expires_at")

        if token_refresh_service.is_token_expiring_soon(expires_at):
            logger.info(
                "Token expiring soon, refreshing before API call",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )

            # Refresh token
            success, updated_mapping = (
                await token_refresh_service.refresh_token_and_update(store_mapping)
            )

            if success and updated_mapping:
                # Use updated mapping
                store_mapping = updated_mapping
                logger.info(
                    "Token refreshed successfully before API call",
                    store_mapping_id=str(store_mapping.id),
                )
            else:
                logger.error(
                    "Failed to refresh token before API call",
                    store_mapping_id=str(store_mapping.id),
                )
                return None

        # Get access token from (possibly updated) store mapping
        if store_mapping.metadata:
            return store_mapping.metadata.get("square_access_token")

        return None

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
            access_token: Square OAuth access token (optional if store_mapping_id provided)
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
        
        # If access_token not provided, get from store mapping and ensure it's valid
        if not access_token and store_mapping_id:
            store_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping_id)
            if store_mapping:
                # Ensure valid token (auto-refresh if needed)
                access_token = await self._ensure_valid_token(store_mapping)
                if not access_token:
                    raise Exception("Failed to obtain valid access token")
            else:
                raise Exception(f"Store mapping not found: {store_mapping_id}")
        
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
                    
                    # Check if product already exists (with multi-tenant filtering)
                    existing = self.supabase_service.get_product_by_source(
                        source_system="square",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                        source_store_id=merchant_id,  # Multi-tenant isolation
                    )
                    
                    # Create or update product
                    product = Product(
                        source_system="square",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                        source_store_id=merchant_id,  # Multi-tenant isolation
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
                    
                    saved, changed = self.supabase_service.create_or_update_product(product)
                    
                    if existing:
                        products_updated += 1
                    else:
                        products_created += 1
                    
                    # Add to sync queue if valid and not already synced to Hipoink
                    if is_valid and store_mapping_id:
                        # Check if product already has a Hipoink mapping for this store
                        existing_hipoink = self.supabase_service.get_hipoink_product_by_product_id(
                            saved.id,  # type: ignore
                            store_mapping_id,
                        )
                        
                        if existing_hipoink:
                            logger.debug(
                                "Skipping queue - product already synced to Hipoink",
                                product_id=str(saved.id),
                                store_mapping_id=str(store_mapping_id),
                                hipoink_product_code=existing_hipoink.hipoink_product_code,
                            )
                        else:
                            try:
                                queue_item = self.supabase_service.add_to_sync_queue(
                                    product_id=saved.id,  # type: ignore
                                    store_mapping_id=store_mapping_id,
                                    operation="create",  # Use "create" for initial sync
                                )
                                if queue_item:
                                    queued_count += 1
                                else:
                                    logger.debug(
                                        "Skipped duplicate queue item",
                                        product_id=str(saved.id),
                                        store_mapping_id=str(store_mapping_id),
                                    )
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
        Handle catalog update with hybrid approach:
        - If webhook payload contains catalog_object: process only that item (optimized)
        - If webhook payload doesn't contain catalog_object: fall back to full sync (safe)
        
        This method ensures webhooks always work while optimizing performance when possible.
        """
        # Validate payload structure
        CatalogVersionUpdatedWebhook(**payload)

        merchant_id = self.extract_store_id(headers, payload)
        if not merchant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Merchant ID missing",
            )

        # 1. Get store mapping
        store_mapping = self.supabase_service.get_store_mapping("square", merchant_id)
        store_mapping_id = None
        access_token = None

        if store_mapping:
            store_mapping_id = store_mapping.id
            access_token = await self._ensure_valid_token(store_mapping)
        
        if not access_token:
            access_token = os.getenv("SQUARE_ACCESS_TOKEN")

        if not access_token:
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message="No access token found",
                    api_name="square",
                    merchant_id=merchant_id,
                    status_code=401,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No access token found",
            )

        base_url = "https://connect.squareupsandbox.com" if settings.square_environment == "sandbox" else "https://connect.squareup.com"

        use_fallback = False

        # 2. Try to extract catalog_object from webhook payload (OPTIMIZED PATH)
        webhook_data = payload.get("data", {})
        webhook_object = webhook_data.get("object", {})
        catalog_object_data = webhook_object.get("catalog_object", {})

        if not catalog_object_data:
            catalog_object_data = webhook_data.get("catalog_object", {})

        # If we have catalog_object in webhook, process only that item (OPTIMIZED)
        if catalog_object_data and catalog_object_data.get("id"):
            object_type = catalog_object_data.get("type")
            object_id = catalog_object_data.get("id")
            is_deleted = catalog_object_data.get("is_deleted", False)

            # Handle deletion
            if is_deleted:
                source_id = object_id
                products_to_delete = self.supabase_service.get_products_by_source_id(
                    "square", source_id, source_store_id=merchant_id
                )
                deleted_count = 0
                for product in products_to_delete:
                    if not product.id:
                        continue
                    if store_mapping_id:
                        queue_item = self.supabase_service.add_to_sync_queue(
                            product_id=product.id,
                            store_mapping_id=store_mapping_id,
                            operation="delete",
                        )
                        if queue_item:
                            deleted_count += 1
                            logger.info(
                                "Product queued for deletion (optimized path)",
                                product_id=str(product.id),
                                source_id=source_id,
                            )
                return {
                    "status": "success",
                    "updated": 0,
                    "deleted": deleted_count,
                    "optimized": True,
                }

            # Fetch the specific item from Square API
            item_to_process = None
            async with httpx.AsyncClient() as client:
                if object_type == "ITEM":
                    retrieve_url = f"{base_url}/v2/catalog/object/{object_id}"
                    response = await client.get(
                        retrieve_url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=30.0,
                    )
                    if response.status_code != 200:
                        logger.warning(
                            "Failed to fetch item from Square API, falling back to full sync",
                            status=response.status_code,
                            object_id=object_id,
                        )
                        use_fallback = True
                    else:
                        data = response.json()
                        item_to_process = data.get("object", {})
                        
                elif object_type == "ITEM_VARIATION":
                    retrieve_url = f"{base_url}/v2/catalog/object/{object_id}"
                    response = await client.get(
                        retrieve_url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=30.0,
                    )
                    if response.status_code != 200:
                        logger.warning(
                            "Failed to fetch variation, falling back to full sync",
                            status=response.status_code,
                            object_id=object_id,
                        )
                        use_fallback = True
                    else:
                        variation_data = response.json()
                        variation_object = variation_data.get("object", {})
                        variation_data_dict = variation_object.get("item_variation_data", {})
                        parent_item_id = variation_data_dict.get("item_id")
                        
                        if not parent_item_id:
                            logger.warning(
                                "Variation has no parent item_id, falling back to full sync",
                                variation_id=object_id,
                            )
                            use_fallback = True
                        else:
                            retrieve_url = f"{base_url}/v2/catalog/object/{parent_item_id}"
                            response = await client.get(
                                retrieve_url,
                                headers={"Authorization": f"Bearer {access_token}"},
                                timeout=30.0,
                            )
                            if response.status_code != 200:
                                logger.warning(
                                    "Failed to fetch parent item, falling back to full sync",
                                    status=response.status_code,
                                    parent_item_id=parent_item_id,
                                )
                                use_fallback = True
                            else:
                                data = response.json()
                                item_to_process = data.get("object", {})

            # If we successfully got the item, process it (OPTIMIZED PATH)
            if not use_fallback and item_to_process:
                measurement_unit_ids: set = set()
                item_data = item_to_process.get("item_data") or {}
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

                processed_products = []
                normalized_variants = []
                
                try:
                    catalog_object = SquareCatalogObject(**item_to_process)
                    normalized_variants = self.transformer.extract_variations_from_catalog_object(
                        catalog_object, measurement_units_cache=measurement_units_cache
                    )

                    all_variants_processed = True
                    
                    for normalized in normalized_variants:
                        try:
                            is_valid, errors = self.validate_normalized_product(normalized)
                            
                            # Get existing product BEFORE updating (for logging unit cost changes)
                            existing_product = None
                            try:
                                existing_products = self.supabase_service.get_products_by_source_id(
                                    "square", normalized.source_id, source_store_id=merchant_id
                                )
                                for ep in existing_products:
                                    if str(ep.source_variant_id) == str(normalized.source_variant_id):
                                        existing_product = ep
                                        break
                            except Exception:
                                pass  # Ignore errors when fetching existing product
                            
                            product = Product(
                                source_system="square",
                                source_id=normalized.source_id,
                                source_variant_id=normalized.source_variant_id,
                                source_store_id=merchant_id,
                                title=normalized.title,
                                barcode=normalized.barcode,
                                sku=normalized.sku,
                                price=normalized.price,
                                currency=normalized.currency,
                                image_url=normalized.image_url,
                                raw_data={"item_data": item_to_process},
                                normalized_data=normalized.to_dict(),
                                status="validated" if is_valid else "pending",
                                validation_errors={"errors": errors} if errors else None,
                            )
                            
                            saved, changed = self.supabase_service.create_or_update_product(product)
                            processed_products.append(saved)

                            # Enhanced logging for unit cost changes
                            if existing_product and existing_product.normalized_data:
                                old_f2 = existing_product.normalized_data.get("f2")  # Price per unit (per-item)
                                old_f4 = existing_product.normalized_data.get("f4")  # Price per ounce (weight-based)
                                new_f2 = normalized.f2
                                new_f4 = normalized.f4
                                
                                if old_f2 != new_f2 or old_f4 != new_f4:
                                    logger.info(
                                        "Unit cost change detected in webhook",
                                        product_id=str(saved.id) if saved.id else None,
                                        source_id=normalized.source_id,
                                        old_f2=old_f2,
                                        new_f2=new_f2,
                                        old_f4=old_f4,
                                        new_f4=new_f4,
                                        price_changed=(existing_product.price != normalized.price),
                                    )

                            if is_valid and changed and store_mapping_id:
                                queue_item = self.supabase_service.add_to_sync_queue(
                                    product_id=saved.id,
                                    store_mapping_id=store_mapping_id,
                                    operation="update"
                                )
                                if queue_item:
                                    logger.info(
                                        "Product queued for update (optimized path)",
                                        product_id=str(saved.id),
                                        source_id=normalized.source_id,
                                    )
                                else:
                                    logger.debug(
                                        "Skipped duplicate queue item (optimized path)",
                                        product_id=str(saved.id),
                                    )
                        except Exception as variant_error:
                            logger.error(
                                "Error processing variant, will fallback to full sync",
                                variant_id=normalized.source_variant_id if 'normalized' in locals() else None,
                                error=str(variant_error),
                            )
                            all_variants_processed = False
                            use_fallback = True
                            break

                    if all_variants_processed and normalized_variants and len(processed_products) == len(normalized_variants):
                        logger.info(
                            "Successfully processed item via optimized path",
                            object_id=object_id,
                            variants_processed=len(processed_products),
                        )
                        return {
                            "status": "success",
                            "updated": len(processed_products),
                            "deleted": 0,
                            "optimized": True,
                        }
                    elif processed_products:
                        logger.warning(
                            "Partial processing detected, falling back to full sync",
                            expected_variants=len(normalized_variants),
                            processed_count=len(processed_products),
                            object_id=object_id,
                        )
                        use_fallback = True
                        
                except Exception as e:
                    logger.error(
                        "Error processing item from webhook, falling back to full sync",
                        object_id=object_id,
                        error=str(e),
                    )
                    use_fallback = True

        # 3. FALLBACK: Full sync
        if use_fallback or not catalog_object_data:
            logger.info(
                "Using full sync fallback",
                reason="webhook_missing_object" if not catalog_object_data else "optimization_failed",
                has_catalog_object=bool(catalog_object_data),
            )

            existing_products = self.supabase_service.get_products_by_system("square", merchant_id)
            db_source_ids = {p.source_id for p in existing_products if p.source_id}

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
                        try:
                            slack_service = get_slack_service()
                            await slack_service.send_api_error_alert(
                                error_message=f"Square API error: {response.status_code} - {response.text[:200]}",
                                api_name="square",
                                merchant_id=merchant_id,
                                status_code=response.status_code,
                            )
                        except Exception as slack_error:
                            logger.warning("Failed to send Slack alert", error=str(slack_error))
                        break
                        
                    data = response.json()
                    all_items.extend(data.get("objects", []))
                    
                    cursor = data.get("cursor")
                    if not cursor:
                        break

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
                            source_store_id=merchant_id,
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

                        saved, changed = self.supabase_service.create_or_update_product(product)
                        processed_products.append(saved)

                        if is_valid and changed and store_mapping_id:
                            queue_item = self.supabase_service.add_to_sync_queue(
                                product_id=saved.id,
                                store_mapping_id=store_mapping_id,
                                operation="update"
                            )
                            if not queue_item:
                                logger.debug(
                                    "Skipped duplicate queue item for update (fallback path)",
                                    product_id=str(saved.id),
                                )
                except Exception as e:
                    logger.error("Error processing item", item_id=item_id, error=str(e))

            deleted_source_ids = db_source_ids - api_source_ids
            for source_id in deleted_source_ids:
                prods_to_mark = [p for p in existing_products if p.source_id == source_id]
                for p in prods_to_mark:
                    if store_mapping_id:
                        queue_item = self.supabase_service.add_to_sync_queue(
                            product_id=p.id,
                            store_mapping_id=store_mapping_id,
                            operation="delete"
                        )
                        if not queue_item:
                            logger.debug(
                                "Skipped duplicate queue item for delete (fallback path)",
                                product_id=str(p.id),
                            )

            return {
                "status": "success",
                "updated": len(processed_products),
                "deleted": len(deleted_source_ids),
                "optimized": False,
            }
        
        return {
            "status": "success",
            "updated": 0,
            "deleted": 0,
            "optimized": False,
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

        # Extract merchant_id for multi-tenant isolation
        merchant_id = store_mapping.source_store_id if store_mapping else None
        if not merchant_id:
            merchant_id = self.extract_store_id(headers, payload)

        # Find all products with this source_id (filtered by merchant for multi-tenant safety)
        products_to_delete = self.supabase_service.get_products_by_source_id(
            "square", source_id, source_store_id=merchant_id  # Multi-tenant isolation
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
                queue_item = self.supabase_service.add_to_sync_queue(
                    product_id=product.id,
                    store_mapping_id=store_mapping.id,
                    operation="delete",
                )
                if queue_item:
                    queued_count += 1
                else:
                    logger.debug(
                        "Skipped duplicate queue item for delete",
                        product_id=str(product.id),
                    )
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

    async def _get_square_credentials(
        self, store_mapping: Any
    ) -> Optional[Tuple[str, str]]:
        """
        Get Square credentials from store mapping metadata.
        Ensures token is valid and refreshes if necessary.

        Args:
            store_mapping: Store mapping object

        Returns:
            Tuple of (merchant_id, access_token) if available, None otherwise
        """
        if not store_mapping:
            logger.debug("Store mapping is None, cannot get Square credentials")
            return None

        merchant_id = store_mapping.source_store_id  # Square merchant/location ID
        
        # Ensure valid token (auto-refresh if needed)
        # This handles checking expiration and refreshing if needed
        access_token = await self._ensure_valid_token(store_mapping)
        
        # Fallback to env var if DB token is missing (and couldn't be refreshed)
        if not access_token:
            access_token = os.getenv("SQUARE_ACCESS_TOKEN")

        if not access_token:
            logger.warning(
                "Square access token not found in store mapping metadata or environment",
                store_mapping_id=str(store_mapping.id) if store_mapping else None,
                merchant_id=merchant_id,
            )
            return None

        return (merchant_id, access_token)

    async def update_catalog_object_price(
        self,
        object_id: str,
        price: float,
        access_token: str,
    ) -> Dict[str, Any]:
        """
        Update a catalog object's price in Square.

        Args:
            object_id: Square catalog object ID (variation ID)
            price: New price as float (e.g., 10.99)
            access_token: Square access token

        Returns:
            API response dictionary

        Raises:
            Exception: If API call fails
        """
        try:
            # Determine base URL based on environment
            base_url = (
                "https://connect.squareupsandbox.com"
                if settings.square_environment == "sandbox"
                else "https://connect.squareup.com"
            )

            # Convert price to cents (Square uses smallest currency unit)
            price_cents = int(round(price * 100))

            # Get current catalog object to preserve all fields
            async with httpx.AsyncClient() as client:
                # First, retrieve the current object
                retrieve_url = f"{base_url}/v2/catalog/object/{object_id}"
                retrieve_response = await client.get(
                    retrieve_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
                retrieve_response.raise_for_status()
                retrieve_data = retrieve_response.json()

                catalog_object = retrieve_data.get("object", {})
                if not catalog_object:
                    raise Exception(f"Catalog object {object_id} not found")

                # Update the price_money in item_variation_data
                # Square catalog objects should be ITEM_VARIATION for price updates
                # Prices are stored on ITEM_VARIATION objects
                object_type = catalog_object.get("type")
                
                if object_type != "ITEM_VARIATION":
                    logger.warning(
                        "Catalog object is not a variation, cannot update price directly",
                        object_id=object_id,
                        type=object_type,
                    )
                    raise Exception(
                        f"Object {object_id} is type '{object_type}', expected ITEM_VARIATION. Use variation ID instead."
                    )
                
                # Update price_money for the variation
                item_variation_data = catalog_object.get("item_variation_data", {})
                if not item_variation_data:
                    raise Exception(f"Item variation data not found for object {object_id}")
                
                item_variation_data["price_money"] = {
                    "amount": price_cents,
                    "currency": "USD",
                }
                catalog_object["item_variation_data"] = item_variation_data

                # Update the catalog object
                update_url = f"{base_url}/v2/catalog/object"
                
                # Generate idempotency key for Square API
                idempotency_key = str(uuid4())
                
                update_payload = {
                    "idempotency_key": idempotency_key,
                    "object": catalog_object,
                }

                update_response = await client.post(
                    update_url,
                    json=update_payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
                update_response.raise_for_status()

                result = update_response.json()
                logger.info(
                    "Updated Square catalog object price",
                    object_id=object_id,
                    price=price,
                    price_cents=price_cents,
                )

                return result

        except httpx.HTTPStatusError as e:
            error_msg = f"Square API error: {e.response.status_code}"
            if e.response.text:
                try:
                    error_data = e.response.json()
                    error_msg += f" - {error_data}"
                except Exception:
                    error_msg += f" - {e.response.text}"

            # Provide specific guidance for common errors
            if e.response.status_code == 401:
                error_msg += " (Unauthorized - check access token)"
            elif e.response.status_code == 404:
                error_msg += " (Not found - check object ID)"

            logger.error(
                "Failed to update Square catalog object price",
                object_id=object_id,
                status_code=e.response.status_code,
                error=error_msg,
            )
            raise Exception(error_msg) from e
        except Exception as e:
            logger.error(
                "Failed to update Square catalog object price",
                object_id=object_id,
                error=str(e),
            )
            raise