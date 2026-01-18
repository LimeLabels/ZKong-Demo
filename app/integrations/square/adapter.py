"""
Square integration adapter.
Implements BaseIntegrationAdapter for Square webhooks and data transformation.
"""

import hmac
import hashlib
import base64
from typing import List, Dict, Any, Optional
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
        self, payload: bytes, signature: str, headers: Dict[str, str]
    ) -> bool:
        """
        Verify Square webhook signature using HMAC SHA256.

        Args:
            payload: Raw request body bytes
            signature: x-square-hmacsha256-signature header value
            headers: Request headers

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
            # Square uses HMAC SHA256 of the request body
            calculated_hmac = base64.b64encode(
                hmac.new(
                    settings.square_webhook_secret.encode("utf-8"),
                    payload,
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
        """Handle catalog.version.updated webhook."""
        # Validate payload structure
        CatalogVersionUpdatedWebhook(**payload)

        # Extract merchant/location ID
        merchant_id = self.extract_store_id(headers, payload)
        if not merchant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Square merchant/location ID not found in webhook",
            )

        # Get store mapping
        store_mapping = self.supabase_service.get_store_mapping("square", merchant_id)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for Square merchant {merchant_id}",
                    "message": "Please create a store mapping first",
                    "endpoint": "/api/store-mappings/",
                },
            )

        # Check if this is a deletion
        data = payload.get("data", {})
        obj = data.get("object", {})
        catalog_object_data = obj.get("catalog_object", {})
        is_deleted = catalog_object_data.get("is_deleted", False)

        if is_deleted:
            return await self._handle_catalog_delete(
                headers, payload, store_mapping, catalog_object_data
            )

        # Transform Square catalog object to normalized products
        normalized_products = self.transform_product(payload)

        if not normalized_products:
            logger.warning(
                "No products extracted from catalog update",
                merchant_id=merchant_id,
            )
            return {
                "status": "success",
                "message": "No products to process",
                "products": [],
            }

        processed_products = []

        # Store each variation as a separate product
        for normalized in normalized_products:
            # Validate normalized product
            is_valid, errors = self.validate_normalized_product(normalized)

            # Create product record
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
                raw_data=payload,
                normalized_data=normalized.to_dict(),
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None,
            )

            # Save to database
            saved_product = self.supabase_service.create_or_update_product(product)
            processed_products.append(saved_product)

            # If valid, add to sync queue
            if is_valid:
                self.supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="update",
                )
                logger.info(
                    "Square product queued for sync",
                    product_id=str(saved_product.id),
                    barcode=normalized.barcode,
                )

        return {
            "status": "success",
            "message": f"Processed {len(processed_products)} product(s)",
            "products": [
                {"id": str(p.id), "title": p.title} for p in processed_products
            ],
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