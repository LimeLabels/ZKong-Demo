"""
NCR POS integration adapter.
Implements BaseIntegrationAdapter for NCR PRO Catalog API integration.
"""

from typing import List, Dict, Any, Optional
from fastapi import Request, HTTPException, status
import structlog

from app.integrations.base import (
    BaseIntegrationAdapter,
    NormalizedProduct,
    NormalizedInventory,
)
from app.integrations.ncr.transformer import NCRTransformer
from app.integrations.ncr.api_client import NCRAPIClient
from app.config import settings
from app.services.supabase_service import SupabaseService
from app.models.database import Product

logger = structlog.get_logger()


class NCRIntegrationAdapter(BaseIntegrationAdapter):
    """NCR POS integration adapter implementing BaseIntegrationAdapter."""

    def __init__(self):
        """Initialize NCR adapter."""
        self.transformer = NCRTransformer()
        self.supabase_service = SupabaseService()

    def get_name(self) -> str:
        """Return integration name."""
        return "ncr"

    def verify_signature(
        self, payload: bytes, signature: str, headers: Dict[str, str]
    ) -> bool:
        """
        Verify NCR webhook signature (if applicable).
        
        Note: NCR may use OAuth or other authentication methods.
        For now, we'll return True if signature is present or if we're using API key auth.

        Args:
            payload: Raw request body bytes
            signature: Signature header value
            headers: Request headers

        Returns:
            True if signature is valid or not required, False otherwise
        """
        # NCR API typically uses OAuth Bearer tokens, not webhook signatures
        # If webhooks are implemented later, add signature verification here
        # For now, return True as API calls use OAuth
        return True

    def extract_store_id(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract NCR enterprise unit/store identifier from headers or payload.

        Args:
            headers: Request headers
            payload: Webhook payload (if applicable)

        Returns:
            Enterprise unit ID if found, None otherwise
        """
        # Check headers first
        enterprise_unit = (
            headers.get("nep-enterprise-unit")
            or headers.get("nep-enterprise-unit-id")
            or headers.get("enterprise-unit-id")
        )

        if enterprise_unit:
            return enterprise_unit

        # Check payload
        if payload:
            return (
                payload.get("enterpriseUnitId")
                or payload.get("enterprise_unit_id")
                or payload.get("store_id")
            )

        return None

    def transform_product(self, raw_data: Dict[str, Any]) -> List[NormalizedProduct]:
        """
        Transform NCR product data to normalized format.
        
        Note: This is for incoming webhooks/data. For outgoing API calls,
        we transform normalized products TO NCR format in the API client.

        Args:
            raw_data: Raw NCR product data

        Returns:
            List of normalized products
        """
        # Extract item code (primary identifier)
        item_code = raw_data.get("itemId", {}).get("itemCode") or raw_data.get("itemCode")
        
        # Extract title from short description
        # MultiLanguageTextData uses a "values" array with LocalizedTextData
        short_desc = raw_data.get("shortDescription", {})
        title = ""
        if isinstance(short_desc, dict):
            values = short_desc.get("values", [])
            if values:
                # Find en-US locale or use first value
                for val in values:
                    if val.get("locale") == "en-US":
                        title = val.get("value", "")
                        break
                if not title and values:
                    title = values[0].get("value", "")
        
        # Extract SKU
        sku = raw_data.get("sku")
        
        # Extract barcode from package identifiers
        barcode = None
        package_ids = raw_data.get("packageIdentifiers", [])
        if package_ids:
            # Find UPC/EAN barcode
            for pkg_id in package_ids:
                if pkg_id.get("type") in ["UPC", "EAN", "GTIN"]:
                    barcode = pkg_id.get("value")
                    break

        # Extract price (would need to fetch from item-prices endpoint)
        price = raw_data.get("price")  # May not be in item data

        normalized = NormalizedProduct(
            source_id=item_code or "",
            source_variant_id=None,  # NCR doesn't use variants like Shopify
            title=title,
            barcode=barcode,
            sku=sku,
            price=price or 0.0,
            currency="USD",
            image_url=None,  # NCR items may not have image URLs in catalog
        )

        return [normalized]

    def transform_inventory(
        self, raw_data: Dict[str, Any]
    ) -> Optional[NormalizedInventory]:
        """
        Transform NCR inventory data to normalized format.

        Args:
            raw_data: Raw NCR inventory data

        Returns:
            Normalized inventory object or None if not applicable
        """
        # NCR catalog API may not have inventory endpoints
        # Return None for now
        return None

    def get_supported_events(self) -> List[str]:
        """Return list of supported event types."""
        # NCR integration uses direct API calls, not webhooks
        # Return empty list or add webhook event types if NCR supports them
        return []

    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle a webhook event (if NCR supports webhooks).

        Args:
            event_type: Type of event
            request: FastAPI Request object
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Response dictionary
        """
        # NCR integration primarily uses direct API calls
        # If webhooks are implemented, handle them here
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="NCR webhooks not yet implemented",
        )

    async def create_product(
        self,
        normalized_product: NormalizedProduct,
        store_mapping_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create a product in NCR, normalize it, save to Supabase, and queue for ESL sync.

        Args:
            normalized_product: Normalized product to create
            store_mapping_config: Store mapping configuration with NCR credentials

        Returns:
            Response dictionary
        """
        # Extract NCR configuration from store mapping
        ncr_config = store_mapping_config.get("metadata", {}) or {}
        
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Get department and category from config or use defaults
            department_id = ncr_config.get("department_id", "DEFAULT")
            category_id = ncr_config.get("category_id", "DEFAULT")

            # Create product in NCR
            result = await api_client.create_product(
                item_code=normalized_product.barcode or normalized_product.sku or normalized_product.source_id,
                title=normalized_product.title,
                department_id=department_id,
                category_id=category_id,
                price=normalized_product.price,
                sku=normalized_product.sku,
                barcode=normalized_product.barcode,
            )

            # Validate normalized product
            is_valid, errors = self.validate_normalized_product(normalized_product)
            
            # Create product record for Supabase
            from app.models.database import Product
            
            product = Product(
                source_system="ncr",
                source_id=normalized_product.source_id,
                source_variant_id=normalized_product.source_variant_id,
                title=normalized_product.title,
                barcode=normalized_product.barcode,
                sku=normalized_product.sku,
                price=normalized_product.price,
                currency=normalized_product.currency or "USD",
                image_url=normalized_product.image_url,
                raw_data=result,  # Store NCR API response as raw_data
                normalized_data=normalized_product.to_dict(),
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None,
            )

            # Save to Supabase
            saved_product = self.supabase_service.create_or_update_product(product)
            
            # If valid and store_mapping has an ID, add to sync queue for ESL
            store_mapping_id = store_mapping_config.get("id")
            if is_valid and store_mapping_id:
                self.supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping_id,
                    operation="create",
                )
                logger.info(
                    "NCR product queued for ESL sync",
                    product_id=str(saved_product.id),
                    barcode=normalized_product.barcode,
                    item_code=normalized_product.source_id,
                )

            return {
                "status": "success",
                "ncr_result": result,
                "product_id": str(saved_product.id) if saved_product.id else None,
                "queued_for_sync": is_valid and bool(store_mapping_id),
            }
        finally:
            await api_client.close()

    async def update_price(
        self,
        item_code: str,
        price: float,
        store_mapping_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update product price in NCR.

        Args:
            item_code: Item code
            price: New price
            store_mapping_config: Store mapping configuration

        Returns:
            Response dictionary
        """
        ncr_config = store_mapping_config.get("metadata", {}) or {}
        
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            result = await api_client.update_price(
                item_code=item_code,
                price=price,
            )
            return result
        finally:
            await api_client.close()

    async def delete_product(
        self,
        item_code: str,
        store_mapping_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Delete a product in NCR (sets status to INACTIVE).

        Args:
            item_code: Item code to delete
            store_mapping_config: Store mapping configuration

        Returns:
            Response dictionary
        """
        ncr_config = store_mapping_config.get("metadata", {}) or {}
        
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Get department and category from config
            department_id = ncr_config.get("department_id", "DEFAULT")
            category_id = ncr_config.get("category_id", "DEFAULT")

            result = await api_client.delete_product(
                item_code=item_code,
                department_id=department_id,
                category_id=category_id,
            )
            return result
        finally:
            await api_client.close()

