"""
Shopify integration adapter.
Implements BaseIntegrationAdapter for Shopify webhooks and data transformation.
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
from app.integrations.shopify.models import (
    ProductCreateWebhook,
    ProductUpdateWebhook,
    ProductDeleteWebhook,
    InventoryLevelsUpdateWebhook,
)
from app.integrations.shopify.transformer import ShopifyTransformer
from app.config import settings
from app.services.supabase_service import SupabaseService
from app.models.database import Product

logger = structlog.get_logger()


class ShopifyIntegrationAdapter(BaseIntegrationAdapter):
    """Shopify integration adapter implementing BaseIntegrationAdapter."""

    def __init__(self):
        """Initialize Shopify adapter."""
        self.transformer = ShopifyTransformer()
        self.supabase_service = SupabaseService()

    def get_name(self) -> str:
        """Return integration name."""
        return "shopify"

    def verify_signature(
        self, payload: bytes, signature: str, headers: Dict[str, str]
    ) -> bool:
        """
        Verify Shopify webhook signature using HMAC SHA256.

        Args:
            payload: Raw request body bytes
            signature: X-Shopify-Hmac-Sha256 header value
            headers: Request headers (not used for Shopify, but kept for interface consistency)

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            return False

        # Calculate HMAC
        calculated_hmac = base64.b64encode(
            hmac.new(
                settings.shopify_webhook_secret.encode("utf-8"), payload, hashlib.sha256
            ).digest()
        ).decode("utf-8")

        # Compare using secure comparison to prevent timing attacks
        return hmac.compare_digest(calculated_hmac, signature)

    def extract_store_id(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract Shopify store domain from webhook headers.

        Args:
            headers: Request headers
            payload: Webhook payload (not used for Shopify)

        Returns:
            Store domain if found, None otherwise
        """
        return self.transformer.extract_store_domain_from_webhook(headers)

    def transform_product(self, raw_data: Dict[str, Any]) -> List[NormalizedProduct]:
        """
        Transform Shopify product data to normalized format.

        Args:
            raw_data: Raw Shopify product webhook payload

        Returns:
            List of normalized products (one per variant)
        """
        # Parse as ProductCreateWebhook or ProductUpdateWebhook
        # Both have the same structure, so we can use either
        product_data = ProductCreateWebhook(**raw_data)
        return self.transformer.extract_variants_from_product(product_data)

    def transform_inventory(
        self, raw_data: Dict[str, Any]
    ) -> Optional[NormalizedInventory]:
        """
        Transform Shopify inventory data to normalized format.

        Args:
            raw_data: Raw Shopify inventory webhook payload

        Returns:
            Normalized inventory object
        """
        inventory_data = InventoryLevelsUpdateWebhook(**raw_data)
        return NormalizedInventory(
            inventory_item_id=str(inventory_data.inventory_item_id),
            location_id=str(inventory_data.location_id),
            available=inventory_data.available,
            updated_at=inventory_data.updated_at.isoformat()
            if inventory_data.updated_at
            else None,
        )

    def get_supported_events(self) -> List[str]:
        """Return list of supported Shopify webhook event types."""
        return [
            "products/create",
            "products/update",
            "products/delete",
            "inventory_levels/update",
        ]

    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle a Shopify webhook event.

        Args:
            event_type: Type of event (e.g., 'products/create')
            request: FastAPI Request object
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Response dictionary
        """
        # Route to appropriate handler based on event type
        if event_type == "products/create":
            return await self._handle_product_create(headers, payload)
        elif event_type == "products/update":
            return await self._handle_product_update(headers, payload)
        elif event_type == "products/delete":
            return await self._handle_product_delete(headers, payload)
        elif event_type == "inventory_levels/update":
            return await self._handle_inventory_update(headers, payload)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported event type: {event_type}",
            )

    async def _handle_product_create(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle products/create webhook."""
        # Validate payload structure (will raise if invalid)
        ProductCreateWebhook(**payload)

        # Extract store domain
        store_domain = self.extract_store_id(headers, payload)
        if not store_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found",
            )

        # Get store mapping
        store_mapping = self.supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first",
                    "endpoint": "/api/store-mappings/",
                },
            )

        # Transform Shopify product variants to normalized products
        normalized_products = self.transform_product(payload)

        created_products = []

        # Store each variant as a separate product
        for normalized in normalized_products:
            # Validate normalized product
            is_valid, errors = self.validate_normalized_product(normalized)

            # Create product record
            product = Product(
                source_system="shopify",
                source_id=normalized.source_id,
                source_variant_id=normalized.source_variant_id,
                source_store_id=store_domain,  # Multi-tenant isolation
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
            saved_product, changed = self.supabase_service.create_or_update_product(product)
            created_products.append(saved_product)

            # If valid, add to sync queue
            if is_valid:
                queue_item = self.supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="create",
                )
                if queue_item:
                    logger.info(
                        "Product queued for sync",
                        product_id=str(saved_product.id),
                        barcode=normalized.barcode,
                    )
                else:
                    logger.debug(
                        "Skipped duplicate queue item",
                        product_id=str(saved_product.id),
                        barcode=normalized.barcode,
                    )

        return {
            "status": "success",
            "message": f"Processed {len(created_products)} product(s)",
            "products": [{"id": str(p.id), "title": p.title} for p in created_products],
        }

    async def _handle_product_update(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle products/update webhook."""
        # Validate payload structure (will raise if invalid)
        ProductUpdateWebhook(**payload)

        store_domain = self.extract_store_id(headers, payload)
        if not store_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found",
            )

        store_mapping = self.supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first via POST /api/store-mappings/",
                },
            )

        normalized_products = self.transform_product(payload)

        updated_products = []

        for normalized in normalized_products:
            is_valid, errors = self.validate_normalized_product(normalized)

            product = Product(
                source_system="shopify",
                source_id=normalized.source_id,
                source_variant_id=normalized.source_variant_id,
                source_store_id=store_domain,  # Multi-tenant isolation
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

            saved_product, changed = self.supabase_service.create_or_update_product(product)
            updated_products.append(saved_product)

            if is_valid:
                queue_item = self.supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="update",
                )
                if not queue_item:
                    logger.debug(
                        "Skipped duplicate queue item for update",
                        product_id=str(saved_product.id),
                    )

        return {
            "status": "success",
            "message": f"Updated {len(updated_products)} product(s)",
            "products": [{"id": str(p.id), "title": p.title} for p in updated_products],
        }

    async def _handle_product_delete(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle products/delete webhook."""
        product_data = ProductDeleteWebhook(**payload)

        store_domain = self.extract_store_id(headers, payload)
        if not store_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shopify store domain not found",
            )

        store_mapping = self.supabase_service.get_store_mapping("shopify", store_domain)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"Store mapping not found for {store_domain}",
                    "message": "Please create a store mapping first via POST /api/store-mappings/",
                },
            )

        # Find all products with this source_id (all variants)
        source_id = str(product_data.id)
        products_to_delete = self.supabase_service.get_products_by_source_id(
            "shopify", source_id, store_domain  # Multi-tenant isolation
        )

        if not products_to_delete:
            logger.info(
                "No products found for deletion",
                source_id=str(product_data.id),
                store_domain=store_domain,
            )
            return {
                "status": "success",
                "message": "No products found to delete",
                "product_id": product_data.id,
                "deleted_count": 0,
            }

        # Queue each product variant for deletion
        queued_count = 0
        for product in products_to_delete:
            if not product.id:
                logger.warning(
                    "Product missing ID, skipping deletion queue",
                    source_id=product.source_id,
                )
                continue

            try:
                queue_item = self.supabase_service.add_to_sync_queue(
                    product_id=product.id,
                    store_mapping_id=store_mapping.id,  # type: ignore
                    operation="delete",
                )
                if not queue_item:
                    logger.debug(
                        "Skipped duplicate queue item for delete",
                        product_id=str(product.id),
                    )
                queued_count += 1
                logger.info(
                    "Product queued for deletion",
                    product_id=str(product.id),
                    source_id=product.source_id,
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
            "product_id": product_data.id,
            "deleted_count": queued_count,
            "total_variants": len(products_to_delete),
        }

    async def _handle_inventory_update(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle inventory_levels/update webhook."""
        inventory_data = InventoryLevelsUpdateWebhook(**payload)

        # Inventory updates might affect pricing or availability
        # For now, we'll log it - you can extend this to update products if needed
        logger.info(
            "Inventory level updated",
            inventory_item_id=inventory_data.inventory_item_id,
        )

        return {
            "status": "success",
            "message": "Inventory update received",
            "inventory_item_id": inventory_data.inventory_item_id,
        }
