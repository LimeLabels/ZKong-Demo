"""
Square integration adapter.
Implements BaseIntegrationAdapter for Square webhooks and data transformation.
"""

import hmac
import hashlib
import base64
import httpx
import os
from typing import List, Dict, Any, Optional, Tuple
from fastapi import Request, HTTPException, status
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

        # 4. Process Creates and Updates
        api_source_ids = set()
        processed_products = []

        for item in all_items:
            item_id = item.get("id")
            api_source_ids.add(item_id)
            
            try:
                catalog_object = SquareCatalogObject(**item)
                normalized_variants = self.transformer.extract_variations_from_catalog_object(catalog_object)

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

    def _get_square_credentials(
        self, store_mapping: Any
    ) -> Optional[Tuple[str, str]]:
        """
        Get Square credentials from store mapping metadata.

        Args:
            store_mapping: Store mapping object

        Returns:
            Tuple of (merchant_id, access_token) if available, None otherwise
        """
        if not store_mapping:
            logger.debug("Store mapping is None, cannot get Square credentials")
            return None

        merchant_id = store_mapping.source_store_id  # Square merchant/location ID
        
        # Try to get access token from metadata first
        access_token = None
        if store_mapping.metadata:
            access_token = store_mapping.metadata.get("square_access_token")
        
        # Fallback to env var if DB token is missing
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
                update_payload = {
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