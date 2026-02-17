"""
NCR POS integration adapter.
Implements BaseIntegrationAdapter for NCR PRO Catalog API integration.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException, Request, status

from app.integrations.base import (
    BaseIntegrationAdapter,
    NormalizedInventory,
    NormalizedProduct,
)
from app.integrations.ncr.api_client import NCRAPIClient
from app.integrations.ncr.transformer import NCRTransformer
from app.models.database import PriceAdjustmentSchedule
from app.services.supabase_service import SupabaseService

logger = structlog.get_logger()


def make_json_serializable(obj: Any) -> Any:
    """Convert objects to JSON-serializable format."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Fallback: try to convert to string
        return str(obj)


class NCRIntegrationAdapter(BaseIntegrationAdapter):
    """NCR POS integration adapter implementing BaseIntegrationAdapter."""

    def __init__(self):
        """Initialize NCR adapter."""
        self.transformer = NCRTransformer()
        self.supabase_service = SupabaseService()

    def get_name(self) -> str:
        """Return integration name."""
        return "ncr"

    def verify_signature(self, payload: bytes, signature: str, headers: dict[str, str]) -> bool:
        """
        Verify signature for requests (not applicable for NCR API calls).

        Note: NCR API uses HMAC-SHA512 authentication for API requests, not webhook signatures.
        This method is required by BaseIntegrationAdapter but not used for NCR.

        Args:
            payload: Raw request body bytes
            signature: Signature header value
            headers: Request headers

        Returns:
            True (NCR doesn't use webhook signatures)
        """
        # NCR API uses HMAC-SHA512 for API authentication, not webhook signatures
        # This method is not used for NCR integration
        return True

    def extract_store_id(self, headers: dict[str, str], payload: dict[str, Any]) -> str | None:
        """
        Extract store identifier from webhook/event (not applicable for NCR).

        Note: NCR does not provide webhooks. This method is required by BaseIntegrationAdapter
        but returns None since NCR uses API-based integration with enterprise_unit identifiers
        stored in store mappings rather than webhook-based store identification.

        Args:
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            None (NCR doesn't use webhooks for store identification)
        """
        # NCR doesn't use webhooks, so store identification is done via
        # store mappings with enterprise_unit in metadata
        return None

    def transform_product(self, raw_data: dict[str, Any]) -> list[NormalizedProduct]:
        """
        Transform NCR product data to normalized format.

        Note: For outgoing API calls, we transform normalized products TO NCR format
        in the API client. This method is used for transforming NCR API responses.

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

    def transform_inventory(self, raw_data: dict[str, Any]) -> NormalizedInventory | None:
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

    def get_supported_events(self) -> list[str]:
        """
        Return list of supported event types.

        Note: NCR does not provide webhooks. This method returns an empty list.
        """
        return []

    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Handle webhook events (not supported by NCR).

        NCR does not provide webhooks. This method always returns 501 Not Implemented.

        Args:
            event_type: Type of event
            request: FastAPI Request object
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Response dictionary with error message
        """
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="NCR does not provide webhooks. Use API endpoints for product operations.",
        )

    async def create_product(
        self,
        normalized_product: NormalizedProduct,
        store_mapping_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a product in NCR, normalize it, save to Supabase, and queue for ESL sync.

        Args:
            normalized_product: Normalized product to create
            store_mapping_config: Store mapping configuration with NCR credentials

        Returns:
            Response dictionary with status, NCR result, product ID, and sync queue status
        """
        # Step 1: Extract NCR configuration from store mapping metadata
        ncr_config = store_mapping_config.get("metadata", {}) or {}

        # Step 2: Initialize NCR API client with credentials from store mapping
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Step 3: Get department and category from config or use defaults
            # These are required by NCR API for product creation
            department_id = ncr_config.get("department_id", "DEFAULT")
            category_id = ncr_config.get("category_id", "DEFAULT")

            # Step 4: Create product in NCR via API
            # Use barcode, sku, or source_id as item_code (priority order)
            actual_item_code = (
                normalized_product.barcode or normalized_product.sku or normalized_product.source_id
            )
            result = await api_client.create_product(
                item_code=actual_item_code,
                title=normalized_product.title,
                department_id=department_id,
                category_id=category_id,
                price=normalized_product.price,
                sku=normalized_product.sku,
                barcode=normalized_product.barcode,
            )

            # Step 5: Validate normalized product data (title, barcode/SKU, price)
            is_valid, errors = self.validate_normalized_product(normalized_product)

            # Step 6: Create product record for Supabase database
            # IMPORTANT: Use the actual NCR item_code as source_id so delete/update operations can find it
            from app.models.database import Product

            # Extract store identifier for multi-tenant isolation
            # Use source_store_id from config if available, otherwise extract enterprise_unit from metadata
            ncr_store_id = (
                store_mapping_config.get("source_store_id")
                or ncr_config.get("ncr_enterprise_unit")
                or ncr_config.get("enterprise_unit_id")
            )

            product = Product(
                source_system="ncr",
                source_id=actual_item_code,  # Use actual NCR item_code, not the original source_id
                source_variant_id=normalized_product.source_variant_id,
                source_store_id=ncr_store_id,  # Multi-tenant isolation
                title=normalized_product.title,
                barcode=normalized_product.barcode,
                sku=normalized_product.sku,
                price=normalized_product.price,
                currency=normalized_product.currency or "USD",
                image_url=normalized_product.image_url,
                raw_data=result,  # Store NCR API response as raw_data for reference
                normalized_data=normalized_product.to_dict(),
                status="validated" if is_valid else "pending",
                validation_errors={"errors": errors} if errors else None,
            )

            # Step 7: Save product to Supabase (upsert operation)
            saved_product, changed = self.supabase_service.create_or_update_product(product)

            # Step 8: If product is valid, changed, and store_mapping exists, queue for ESL sync
            # This ensures the product will be synced to electronic shelf labels (ESL)
            store_mapping_id = store_mapping_config.get("id")
            if is_valid and changed and store_mapping_id:
                queue_item = self.supabase_service.add_to_sync_queue(
                    product_id=saved_product.id,  # type: ignore
                    store_mapping_id=store_mapping_id,
                    operation="create",
                )
                if queue_item:
                    logger.info(
                        "NCR product queued for ESL sync",
                        product_id=str(saved_product.id),
                        barcode=normalized_product.barcode,
                        item_code=normalized_product.source_id,
                    )
                else:
                    logger.debug(
                        "Skipped duplicate queue item for NCR product",
                        product_id=str(saved_product.id),
                        item_code=normalized_product.source_id,
                    )

            return make_json_serializable(
                {
                    "status": "success",
                    "ncr_result": result,
                    "product_id": str(saved_product.id) if saved_product.id else None,
                    "queued_for_sync": is_valid and bool(store_mapping_id),
                }
            )
        finally:
            # Always close the API client connection
            await api_client.close()

    async def update_price(
        self,
        item_code: str,
        price: float,
        store_mapping_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update product price in NCR.

        This is the core price update method that updates the price of an existing
        product in NCR via the item-prices API endpoint. The price update is
        effective immediately and applies to the specified enterprise unit.

        Args:
            item_code: Item code of the product to update
            price: New price value (float)
            store_mapping_config: Store mapping configuration with NCR credentials

        Returns:
            Response dictionary with status, item_code, and updated price
        """
        # Extract NCR configuration from store mapping metadata
        ncr_config = store_mapping_config.get("metadata", {}) or {}

        # Initialize NCR API client with credentials from store mapping
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Update price in NCR via API
            # Uses PUT /item-prices endpoint with price data
            result = await api_client.update_price(
                item_code=item_code,
                price=price,
            )

            # If store_mapping has an ID, update database and queue for ESL sync
            store_mapping_id = store_mapping_config.get("id")
            if store_mapping_id:
                # Extract store identifier for multi-tenant isolation
                ncr_store_id = (
                    store_mapping_config.get("source_store_id")
                    or ncr_config.get("ncr_enterprise_unit")
                    or ncr_config.get("enterprise_unit_id")
                )

                # Find product in database (with multi-tenant filtering)
                existing_product = self.supabase_service.get_product_by_source(
                    "ncr", item_code, source_store_id=ncr_store_id
                )

                if existing_product:
                    # Update product price in database
                    existing_product.price = float(price)

                    # Also update normalized_data price (sync worker uses normalized_data first)
                    if existing_product.normalized_data:
                        existing_product.normalized_data["price"] = float(price)
                    else:
                        # If normalized_data doesn't exist, create it with updated price
                        existing_product.normalized_data = {
                            "source_id": existing_product.source_id,
                            "title": existing_product.title,
                            "barcode": existing_product.barcode,
                            "sku": existing_product.sku,
                            "price": float(price),
                            "currency": existing_product.currency or "USD",
                        }

                    updated_product, changed = self.supabase_service.create_or_update_product(
                        existing_product
                    )

                    # Queue for ESL sync (only if changed)
                    if updated_product.id and changed:
                        queue_item = self.supabase_service.add_to_sync_queue(
                            product_id=updated_product.id,
                            store_mapping_id=store_mapping_id,
                            operation="update",
                        )
                        if queue_item:
                            logger.info(
                                "NCR price update queued for ESL sync",
                                product_id=str(updated_product.id),
                                item_code=item_code,
                                price=price,
                            )
                        else:
                            logger.debug(
                                "Skipped duplicate queue item for NCR product update",
                                product_id=str(updated_product.id),
                                item_code=item_code,
                            )

                        return make_json_serializable(
                            {
                                "status": "success",
                                "item_code": item_code,
                                "price": float(price),
                                "product_id": str(updated_product.id)
                                if updated_product.id
                                else None,
                                "queued_for_sync": True,
                            }
                        )
                else:
                    logger.warning(
                        "Product not found in database for price update",
                        item_code=item_code,
                    )

            return make_json_serializable(result)
        finally:
            # Always close the API client connection
            await api_client.close()

    async def delete_product(
        self,
        item_code: str,
        store_mapping_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Delete a product in NCR by setting its status to INACTIVE.

        Note: NCR API doesn't have a physical DELETE endpoint. Instead, products
        are "deleted" by updating their status to INACTIVE, which hides them from
        active product listings but preserves the data.

        Args:
            item_code: Item code of the product to delete
            store_mapping_config: Store mapping configuration with NCR credentials

        Returns:
            Response dictionary with status, item_code, and deleted flag
        """
        # Extract NCR configuration from store mapping metadata
        ncr_config = store_mapping_config.get("metadata", {}) or {}

        # Initialize NCR API client with credentials from store mapping
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Get department and category from config (required for NCR API update)
            department_id = ncr_config.get("department_id", "DEFAULT")
            category_id = ncr_config.get("category_id", "DEFAULT")

            # Delete product by setting status to INACTIVE via API
            # This preserves the product data but marks it as inactive
            result = await api_client.delete_product(
                item_code=item_code,
                department_id=department_id,
                category_id=category_id,
            )

            # If store_mapping has an ID, queue for database deletion and ESL sync
            store_mapping_id = store_mapping_config.get("id")
            if store_mapping_id:
                # Find products with this source_id in the database
                # Try source_id first (the NCR item_code)
                # Extract store identifier for multi-tenant isolation
                ncr_store_id = (
                    store_mapping_config.get("source_store_id")
                    or ncr_config.get("ncr_enterprise_unit")
                    or ncr_config.get("enterprise_unit_id")
                )

                products_to_delete = self.supabase_service.get_products_by_source_id(
                    "ncr",
                    item_code,
                    ncr_store_id,  # Multi-tenant isolation
                )

                # If not found by source_id, try searching by barcode as fallback
                # (for products created before the fix where source_id might not match item_code)
                if not products_to_delete:
                    logger.info(
                        "Product not found by source_id, trying barcode search",
                        item_code=item_code,
                        source_system="ncr",
                    )
                    # Search by barcode - get all NCR products and filter
                    # Extract store identifier for multi-tenant isolation
                    ncr_store_id = (
                        store_mapping_config.get("source_store_id")
                        or ncr_config.get("ncr_enterprise_unit")
                        or ncr_config.get("enterprise_unit_id")
                    )

                    all_ncr_products = self.supabase_service.get_products_by_system(
                        "ncr", ncr_store_id
                    )  # Multi-tenant isolation
                    products_to_delete = [
                        p for p in all_ncr_products if p.barcode == item_code or p.sku == item_code
                    ]

                queued_count = 0
                for product in products_to_delete:
                    if product.id:
                        queue_item = self.supabase_service.add_to_sync_queue(
                            product_id=product.id,
                            store_mapping_id=store_mapping_id,
                            operation="delete",
                        )
                        if queue_item:
                            queued_count += 1
                        else:
                            logger.debug(
                                "Skipped duplicate queue item for NCR product delete",
                                product_id=str(product.id),
                            )
                        logger.info(
                            "NCR product queued for deletion and ESL sync",
                            product_id=str(product.id),
                            item_code=item_code,
                        )

                return make_json_serializable(
                    {
                        "status": "success",
                        "item_code": item_code,
                        "deleted": True,
                        "queued_for_sync": queued_count > 0,
                        "queued_count": queued_count,
                    }
                )

            return make_json_serializable(result)
        finally:
            # Always close the API client connection
            await api_client.close()

    async def pre_schedule_prices(
        self,
        schedule: PriceAdjustmentSchedule,
        store_mapping_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Pre-schedule all price changes for a schedule in NCR using effectiveDate.

        This method calculates all price events from the schedule and pre-schedules
        them in NCR. NCR will automatically apply these prices at the specified times,
        eliminating the need for constant polling.

        Args:
            schedule: Price adjustment schedule
            store_mapping_config: Store mapping configuration with NCR credentials

        Returns:
            Dictionary with scheduling results
        """
        import pytz

        from app.utils.price_schedule_calculator import calculate_all_price_events

        # Extract NCR configuration
        ncr_config = store_mapping_config.get("metadata", {}) or {}

        # Get store mapping to determine timezone
        store_mapping_id = store_mapping_config.get("id")
        if store_mapping_id:
            store_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping_id)
            if store_mapping:
                # Get timezone from store mapping
                if store_mapping.metadata and "timezone" in store_mapping.metadata:
                    try:
                        store_timezone = pytz.timezone(store_mapping.metadata["timezone"])
                    except Exception:
                        store_timezone = pytz.UTC
                else:
                    store_timezone = pytz.UTC
            else:
                store_timezone = pytz.UTC
        else:
            store_timezone = pytz.UTC

        # Calculate all price events
        try:
            price_events = calculate_all_price_events(schedule, store_timezone)
        except Exception as e:
            logger.error(
                "Failed to calculate price events",
                schedule_id=str(schedule.id) if schedule.id else None,
                error=str(e),
            )
            raise

        if not price_events:
            logger.warning(
                "No price events to schedule",
                schedule_id=str(schedule.id) if schedule.id else None,
            )
            return {
                "status": "success",
                "scheduled_count": 0,
                "failed_count": 0,
                "message": "No price events to schedule",
            }

        # Initialize NCR API client
        api_client = NCRAPIClient(
            base_url=ncr_config.get("ncr_base_url", "https://api.ncr.com/catalog"),
            shared_key=ncr_config.get("ncr_shared_key"),
            secret_key=ncr_config.get("ncr_secret_key"),
            organization=ncr_config.get("ncr_organization"),
            enterprise_unit=ncr_config.get("ncr_enterprise_unit"),
        )

        try:
            # Convert price events to format expected by API client
            price_events_data = []
            for event in price_events:
                # Convert datetime to ISO format string in UTC
                effective_date_utc = event.effective_date.astimezone(pytz.UTC)
                effective_date_str = effective_date_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                price_events_data.append(
                    {
                        "item_code": event.item_code,
                        "price": event.price,
                        "effective_date": effective_date_str,
                        "currency": "USD",
                    }
                )

            # Pre-schedule in NCR
            result = await api_client.pre_schedule_prices(price_events_data)

            logger.info(
                "Pre-scheduled prices in NCR",
                schedule_id=str(schedule.id) if schedule.id else None,
                scheduled_count=result["scheduled_count"],
                failed_count=result["failed_count"],
                total_count=result["total_count"],
            )

            return {
                "status": "success",
                "scheduled_count": result["scheduled_count"],
                "failed_count": result["failed_count"],
                "total_count": result["total_count"],
                "results": result["results"],
            }

        finally:
            await api_client.close()
