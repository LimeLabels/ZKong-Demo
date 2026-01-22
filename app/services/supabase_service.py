"""
Supabase service layer for database operations.
Handles CRUD operations for products, sync_queue, sync_log, and store_mappings.
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from supabase import create_client, Client
import structlog
import json
from app.config import settings
from app.models.database import (
    Product,
    SyncQueueItem,
    SyncLog,
    StoreMapping,
    HipoinkProduct,
    PriceAdjustmentSchedule,
)

logger = structlog.get_logger()


class SupabaseService:
    """Service for interacting with Supabase database."""

    def __init__(self):
        """Initialize Supabase client."""
        self.client: Client = create_client(
            settings.supabase_url, settings.supabase_service_key
        )
    
    def _serialize_datetimes(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively convert datetime objects to ISO format strings.
        Also converts UUID objects to strings.
        
        Args:
            data: Dictionary that may contain datetime/UUID objects
            
        Returns:
            Dictionary with datetime/UUID objects converted to strings
        """
        if isinstance(data, dict):
            return {k: self._serialize_datetimes(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_datetimes(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, UUID):
            return str(data)
        else:
            return data

    # Store Mappings

    def get_store_mapping(
        self, source_system: str, source_store_id: str
    ) -> Optional[StoreMapping]:
        """
        Get store mapping by source system and store ID.

        Args:
            source_system: Source system name (e.g., 'shopify')
            source_store_id: Source store identifier

        Returns:
            StoreMapping if found, None otherwise
        """
        try:
            # Don't use .single() - it throws exception on 0 rows
            # Instead, use .limit(1) and check results
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("source_system", source_system)
                .eq("source_store_id", source_store_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return StoreMapping(**result.data[0])
            return None
        except Exception as e:
            logger.error(
                "Failed to get store mapping",
                source_system=source_system,
                source_store_id=source_store_id,
                error=str(e),
            )
            return None

    def get_store_mapping_by_id(self, mapping_id: UUID) -> Optional[StoreMapping]:
        """Get store mapping by UUID."""
        try:
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("id", str(mapping_id))
                .single()
                .execute()
            )

            if result.data:
                return StoreMapping(**result.data)
            return None
        except Exception as e:
            if "No rows" in str(e) or "Could not find" in str(e):
                return None
            logger.error("Failed to get store mapping by ID", error=str(e))
            return None

    def create_store_mapping(self, mapping: StoreMapping) -> StoreMapping:
        """Create a new store mapping."""
        try:
            result = (
                self.client.table("store_mappings")
                .insert(mapping.dict(exclude_none=True, exclude={"id"}))
                .execute()
            )

            if result.data:
                return StoreMapping(**result.data[0])
            raise Exception("No data returned from insert")
        except Exception as e:
            logger.error("Failed to create store mapping", error=str(e))
            raise

    def update_store_mapping_oauth_token(
        self, mapping_id: UUID, shop_domain: str, access_token: str
    ) -> Optional[StoreMapping]:
        """
        Update store mapping with Shopify OAuth token.

        Args:
            mapping_id: Store mapping UUID
            shop_domain: Shopify shop domain
            access_token: Shopify access token

        Returns:
            Updated StoreMapping or None if not found
        """
        try:
            # Get existing mapping
            existing = self.get_store_mapping_by_id(mapping_id)
            if not existing:
                return None

            # Update metadata
            metadata = existing.metadata or {}
            metadata["shopify_shop_domain"] = shop_domain
            metadata["shopify_access_token"] = access_token
            metadata["shopify_oauth_installed_at"] = datetime.utcnow().isoformat()

            result = (
                self.client.table("store_mappings")
                .update({"metadata": metadata})
                .eq("id", str(mapping_id))
                .execute()
            )

            if result.data:
                return StoreMapping(**result.data[0])
            return None
        except Exception as e:
            logger.error("Failed to update store mapping OAuth token", error=str(e))
            return None

    def get_store_mappings_by_source_system(
        self, source_system: str
    ) -> List[StoreMapping]:
        """
        Get all active store mappings for a source system.

        Args:
            source_system: Source system name (e.g., 'ncr', 'square', 'shopify')

        Returns:
            List of StoreMapping objects
        """
        try:
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("source_system", source_system)
                .eq("is_active", True)
                .execute()
            )

            return [StoreMapping(**row) for row in result.data] if result.data else []
        except Exception as e:
            logger.error(
                "Failed to get store mappings by source system",
                source_system=source_system,
                error=str(e),
            )
            return []

    def get_store_mapping_by_shop_domain(
        self, shop_domain: str
    ) -> Optional[StoreMapping]:
        """
        Get store mapping by Shopify shop domain.
        Searches in metadata field.

        Args:
            shop_domain: Shopify shop domain (e.g., 'myshop.myshopify.com')

        Returns:
            StoreMapping if found, None otherwise
        """
        try:
            # Query store mappings where metadata contains shop_domain
            # Note: This is a simplified query - may need adjustment based on Supabase capabilities
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("source_system", "shopify")
                .eq("is_active", True)
                .execute()
            )

            # Filter in Python since Supabase JSON queries can be tricky
            for item in result.data:
                mapping = StoreMapping(**item)
                if (
                    mapping.metadata
                    and mapping.metadata.get("shopify_shop_domain") == shop_domain
                ):
                    return mapping
                # Also check source_store_id as fallback
                if mapping.source_store_id == shop_domain:
                    return mapping

            return None
        except Exception as e:
            logger.error("Failed to get store mapping by shop domain", error=str(e))
            return None

    # Products

    def create_or_update_product(self, product: Product) -> Product:
        """
        Create or update product in database.
        Uses upsert based on source_system, source_id, and source_variant_id.

        Args:
            product: Product to create or update

        Returns:
            Created or updated Product
        """
        try:
            # Check if product exists
            existing = self.get_product_by_source(
                product.source_system, product.source_id, product.source_variant_id
            )

            if existing:
                # Update existing product
                # Use model_dump with json mode for Pydantic v2, or dict() with manual serialization
                try:
                    # Try Pydantic v2 style first
                    update_data = product.model_dump(
                        mode='json', exclude_none=True, exclude={"id", "created_at"}
                    )
                except AttributeError:
                    # Fallback to Pydantic v1 with manual datetime serialization
                    update_data = product.dict(
                        exclude_none=True, exclude={"id", "created_at"}
                    )
                    # Convert datetime objects to ISO format strings
                    update_data = self._serialize_datetimes(update_data)
                
                result = (
                    self.client.table("products")
                    .update(update_data)
                    .eq("id", existing.id)
                    .execute()
                )

                if result.data:
                    return Product(**result.data[0])
            else:
                # Create new product
                try:
                    # Try Pydantic v2 style first
                    insert_data = product.model_dump(
                        mode='json', exclude_none=True, exclude={"id"}
                    )
                except AttributeError:
                    # Fallback to Pydantic v1 with manual datetime serialization
                    insert_data = product.dict(exclude_none=True, exclude={"id"})
                    # Convert datetime objects to ISO format strings
                    insert_data = self._serialize_datetimes(insert_data)
                
                result = (
                    self.client.table("products")
                    .insert(insert_data)
                    .execute()
                )

                if result.data:
                    return Product(**result.data[0])

            raise Exception("No data returned from upsert")
        except Exception as e:
            logger.error("Failed to create/update product", error=str(e))
            raise

    def get_product_by_source(
        self,
        source_system: str,
        source_id: str,
        source_variant_id: Optional[str] = None,
    ) -> Optional[Product]:
        """Get product by source system and IDs."""
        try:
            query = (
                self.client.table("products")
                .select("*")
                .eq("source_system", source_system)
                .eq("source_id", source_id)
            )

            if source_variant_id:
                query = query.eq("source_variant_id", source_variant_id)
            else:
                query = query.is_("source_variant_id", "null")

            result = query.single().execute()

            if result.data:
                return Product(**result.data)
            return None
        except Exception as e:
            # Not found is expected for new products - don't log as error
            error_str = str(e)
            if any(
                phrase in error_str
                for phrase in [
                    "No rows",
                    "Could not find",
                    "PGRST116",
                    "result contains 0 rows",
                    "Cannot coerce the result to a single JSON object",
                ]
            ):
                # Product doesn't exist - this is normal for create operations
                return None
            # Only log actual errors (network issues, etc.)
            logger.error("Failed to get product by source", error=str(e))
            return None

    def get_product(self, product_id: UUID) -> Optional[Product]:
        """Get product by UUID."""
        try:
            result = (
                self.client.table("products")
                .select("*")
                .eq("id", str(product_id))
                .single()
                .execute()
            )

            if result.data:
                return Product(**result.data)
            return None
        except Exception as e:
            logger.error(
                "Failed to get product", product_id=str(product_id), error=str(e)
            )
            return None

    def get_products_by_source_id(
        self, source_system: str, source_id: str
    ) -> List[Product]:
        """
        Get all products by source system and source ID.
        Used to find all variants of a product when deleting.

        Args:
            source_system: Source system name (e.g., 'shopify')
            source_id: Source product ID

        Returns:
            List of Product objects (all variants)
        """
        try:
            result = (
                self.client.table("products")
                .select("*")
                .eq("source_system", source_system)
                .eq("source_id", source_id)
                .execute()
            )

            if result.data:
                return [Product(**item) for item in result.data]
            return []
        except Exception as e:
            logger.error(
                "Failed to get products by source ID",
                source_system=source_system,
                source_id=source_id,
                error=str(e),
            )
            return []

    def get_products_by_system(self, source_system: str) -> List[Product]:
        """
        Fetch all products belonging to a specific integration (e.g., 'square').
        Used for deletion detection by comparing DB vs API products.

        Args:
            source_system: Source system name (e.g., 'square', 'shopify')

        Returns:
            List of Product objects
        """
        try:
            result = (
                self.client.table("products")
                .select("*")
                .eq("source_system", source_system)
                .execute()
            )

            if result.data:
                return [Product(**item) for item in result.data]
            return []
        except Exception as e:
            logger.error(
                "Failed to get products by system",
                source_system=source_system,
                error=str(e),
            )
            return []

    def update_product_status(self, product_id: Any, status: str) -> None:
        """
        Update the status of a product (e.g., marking it as 'deleted').

        Args:
            product_id: Product UUID or string ID
            status: New status (e.g., 'deleted', 'pending', 'validated')
        """
        try:
            self.client.table("products").update({"status": status}).eq(
                "id", str(product_id)
            ).execute()
            logger.debug("Updated product status", product_id=str(product_id), status=status)
        except Exception as e:
            logger.error(
                "Failed to update product status",
                product_id=str(product_id),
                status=status,
                error=str(e),
            )

    def delete_product(self, product_id: Any) -> bool:
        """
        Delete a product from the database.

        Args:
            product_id: Product UUID or string ID

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            result = (
                self.client.table("products")
                .delete()
                .eq("id", str(product_id))
                .execute()
            )
            logger.info("Deleted product from database", product_id=str(product_id))
            return True
        except Exception as e:
            logger.error(
                "Failed to delete product from database",
                product_id=str(product_id),
                error=str(e),
            )
            return False

    def get_product_by_barcode(
        self, barcode: str, store_mapping_id: Optional[UUID] = None
    ) -> Optional[Product]:
        """
        Get product by barcode.
        Optionally filter by store_mapping_id if multiple stores have same barcode.

        Args:
            barcode: Product barcode
            store_mapping_id: Optional store mapping ID to filter results

        Returns:
            Product if found, None otherwise
        """
        try:
            query = self.client.table("products").select("*").eq("barcode", barcode)

            # If store_mapping_id provided, we need to join with hipoink_products
            # For now, just get the first product with this barcode
            # In the future, we could join with hipoink_products to filter by store

            result = query.limit(1).execute()

            if result.data and len(result.data) > 0:
                return Product(**result.data[0])
            return None
        except Exception as e:
            logger.error(
                "Failed to get product by barcode", barcode=barcode, error=str(e)
            )
            return None

    # Sync Queue

    def add_to_sync_queue(
        self, product_id: UUID, store_mapping_id: UUID, operation: str
    ) -> SyncQueueItem:
        """
        Add product to sync queue.

        Args:
            product_id: Product UUID
            store_mapping_id: Store mapping UUID
            operation: Operation type ('create', 'update', 'delete')

        Returns:
            Created SyncQueueItem
        """
        try:
            queue_item = SyncQueueItem(
                product_id=product_id,
                store_mapping_id=store_mapping_id,
                operation=operation,
                status="pending",
            )

            # Convert UUIDs to strings for JSON serialization
            insert_data = queue_item.dict(exclude_none=True, exclude={"id"})
            insert_data["product_id"] = str(insert_data["product_id"])
            insert_data["store_mapping_id"] = str(insert_data["store_mapping_id"])

            result = self.client.table("sync_queue").insert(insert_data).execute()

            if result.data:
                return SyncQueueItem(**result.data[0])
            raise Exception("No data returned from insert")
        except Exception as e:
            logger.error("Failed to add to sync queue", error=str(e))
            raise

    def get_pending_sync_queue_items(self, limit: int = 10) -> List[SyncQueueItem]:
        """
        Get pending items from sync queue.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of pending SyncQueueItem
        """
        try:
            result = (
                self.client.table("sync_queue")
                .select("*")
                .eq("status", "pending")
                .order("scheduled_at", desc=False)
                .limit(limit)
                .execute()
            )

            return [SyncQueueItem(**item) for item in result.data]
        except Exception as e:
            logger.error("Failed to get pending sync queue items", error=str(e))
            return []

    def update_sync_queue_status(
        self,
        queue_item_id: UUID,
        status: str,
        error_message: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
    ) -> Optional[SyncQueueItem]:
        """Update sync queue item status."""
        try:
            update_data: Dict[str, Any] = {"status": status}

            if error_message:
                update_data["error_message"] = error_message
            if error_details:
                update_data["error_details"] = error_details
            if retry_count is not None:
                update_data["retry_count"] = retry_count

            if status in ["succeeded", "failed"]:
                from datetime import datetime

                update_data["processed_at"] = datetime.utcnow().isoformat()

            result = (
                self.client.table("sync_queue")
                .update(update_data)
                .eq("id", str(queue_item_id))
                .execute()
            )

            if result.data:
                return SyncQueueItem(**result.data[0])
            return None
        except Exception as e:
            logger.error("Failed to update sync queue status", error=str(e))
            return None

    # Sync Log

    def create_sync_log(self, log_entry: SyncLog) -> SyncLog:
        """Create sync log entry for audit trail."""
        try:
            # Convert UUIDs to strings for JSON serialization
            insert_data = log_entry.dict(exclude_none=True, exclude={"id"})
            if insert_data.get("sync_queue_id"):
                insert_data["sync_queue_id"] = str(insert_data["sync_queue_id"])
            if insert_data.get("product_id"):
                insert_data["product_id"] = str(insert_data["product_id"])
            if insert_data.get("store_mapping_id"):
                insert_data["store_mapping_id"] = str(insert_data["store_mapping_id"])

            result = self.client.table("sync_log").insert(insert_data).execute()

            if result.data:
                return SyncLog(**result.data[0])
            raise Exception("No data returned from insert")
        except Exception as e:
            logger.error("Failed to create sync log", error=str(e))
            raise

    # Hipoink Products

    def create_or_update_hipoink_product(
        self, hipoink_product: HipoinkProduct
    ) -> HipoinkProduct:
        """Create or update Hipoink product mapping."""
        try:
            # Check if mapping exists
            result = (
                self.client.table("hipoink_products")
                .select("*")
                .eq("product_id", str(hipoink_product.product_id))
                .eq("store_mapping_id", str(hipoink_product.store_mapping_id))
                .execute()
            )

            if result.data and len(result.data) > 0:
                # Update existing
                update_data = hipoink_product.dict(
                    exclude_none=True, exclude={"id", "created_at"}
                )
                # Convert UUIDs to strings
                if update_data.get("product_id"):
                    update_data["product_id"] = str(update_data["product_id"])
                if update_data.get("store_mapping_id"):
                    update_data["store_mapping_id"] = str(
                        update_data["store_mapping_id"]
                    )

                result = (
                    self.client.table("hipoink_products")
                    .update(update_data)
                    .eq("id", result.data[0]["id"])
                    .execute()
                )

                if result.data:
                    return HipoinkProduct(**result.data[0])
            else:
                # Create new
                insert_data = hipoink_product.dict(exclude_none=True, exclude={"id"})
                # Convert UUIDs to strings
                if insert_data.get("product_id"):
                    insert_data["product_id"] = str(insert_data["product_id"])
                if insert_data.get("store_mapping_id"):
                    insert_data["store_mapping_id"] = str(
                        insert_data["store_mapping_id"]
                    )

                result = (
                    self.client.table("hipoink_products").insert(insert_data).execute()
                )

                if result.data:
                    return HipoinkProduct(**result.data[0])

            raise Exception("No data returned from upsert")
        except Exception as e:
            logger.error("Failed to create/update Hipoink product", error=str(e))
            raise

    def get_hipoink_product_by_product_id(
        self, product_id: UUID, store_mapping_id: UUID
    ) -> Optional[HipoinkProduct]:
        """Get Hipoink product mapping by product ID and store mapping."""
        try:
            result = (
                self.client.table("hipoink_products")
                .select("*")
                .eq("product_id", str(product_id))
                .eq("store_mapping_id", str(store_mapping_id))
                .single()
                .execute()
            )

            if result.data:
                return HipoinkProduct(**result.data)
            return None
        except Exception as e:
            if "No rows" in str(e) or "Could not find" in str(e):
                return None
            logger.error("Failed to get Hipoink product", error=str(e))
            return None

    def delete_hipoink_product_mapping(
        self, product_id: str, store_mapping_id: str
    ) -> bool:
        """
        Delete a Hipoink product mapping record.
        
        Args:
            product_id: The product UUID
            store_mapping_id: The store mapping UUID
            
        Returns:
            True if deleted, False if not found
        """
        try:
            response = (
                self.client.table("hipoink_products")
                .delete()
                .eq("product_id", str(product_id))
                .eq("store_mapping_id", str(store_mapping_id))
                .execute()
            )
            
            deleted_count = len(response.data) if response.data else 0
            logger.info(
                "Deleted Hipoink product mapping",
                product_id=str(product_id),
                store_mapping_id=str(store_mapping_id),
                deleted_count=deleted_count,
            )
            return deleted_count > 0
            
        except Exception as e:
            logger.error(
                "Failed to delete Hipoink product mapping",
                product_id=str(product_id),
                store_mapping_id=str(store_mapping_id),
                error=str(e),
            )
            return False

    # Price Adjustment Schedules

    def create_price_adjustment_schedule(
        self, schedule: PriceAdjustmentSchedule
    ) -> PriceAdjustmentSchedule:
        """Create a new price adjustment schedule."""
        try:
            insert_data = schedule.dict(exclude_none=True, exclude={"id"})
            # Convert UUIDs to strings
            if insert_data.get("store_mapping_id"):
                insert_data["store_mapping_id"] = str(insert_data["store_mapping_id"])

            # Convert datetime objects to ISO format strings for JSON serialization
            datetime_fields = [
                "start_date",
                "end_date",
                "last_triggered_at",
                "next_trigger_at",
                "created_at",
                "updated_at",
            ]
            for field in datetime_fields:
                if field in insert_data and insert_data[field] is not None:
                    if isinstance(insert_data[field], datetime):
                        insert_data[field] = insert_data[field].isoformat()

            result = (
                self.client.table("price_adjustment_schedules")
                .insert(insert_data)
                .execute()
            )

            if result.data:
                return PriceAdjustmentSchedule(**result.data[0])
            raise Exception("No data returned from insert")
        except Exception as e:
            logger.error("Failed to create price adjustment schedule", error=str(e))
            raise

    def get_price_adjustment_schedule(
        self, schedule_id: UUID
    ) -> Optional[PriceAdjustmentSchedule]:
        """Get price adjustment schedule by ID."""
        try:
            result = (
                self.client.table("price_adjustment_schedules")
                .select("*")
                .eq("id", str(schedule_id))
                .single()
                .execute()
            )

            if result.data:
                return PriceAdjustmentSchedule(**result.data)
            return None
        except Exception as e:
            if "No rows" in str(e) or "Could not find" in str(e):
                return None
            logger.error("Failed to get price adjustment schedule", error=str(e))
            return None

    def get_active_price_adjustment_schedules(
        self, limit: int = 100
    ) -> List[PriceAdjustmentSchedule]:
        """Get all active price adjustment schedules."""
        try:
            result = (
                self.client.table("price_adjustment_schedules")
                .select("*")
                .eq("is_active", True)
                .order("next_trigger_at", desc=False)
                .limit(limit)
                .execute()
            )

            return [PriceAdjustmentSchedule(**item) for item in result.data]
        except Exception as e:
            logger.error(
                "Failed to get active price adjustment schedules", error=str(e)
            )
            return []

    def get_schedules_due_for_trigger(
        self, current_time: datetime
    ) -> List[PriceAdjustmentSchedule]:
        """
        Get schedules that are due to be triggered.
        Returns schedules where next_trigger_at <= current_time and is_active=True.
        """
        try:
            result = (
                self.client.table("price_adjustment_schedules")
                .select("*")
                .eq("is_active", True)
                .lte("next_trigger_at", current_time.isoformat())
                .order("next_trigger_at", desc=False)
                .execute()
            )

            return [PriceAdjustmentSchedule(**item) for item in result.data]
        except Exception as e:
            logger.error("Failed to get schedules due for trigger", error=str(e))
            return []

    def update_price_adjustment_schedule(
        self, schedule_id: UUID, update_data: Dict[str, Any]
    ) -> Optional[PriceAdjustmentSchedule]:
        """Update a price adjustment schedule."""
        try:
            # Convert UUIDs to strings if present
            if update_data.get("store_mapping_id"):
                update_data["store_mapping_id"] = str(update_data["store_mapping_id"])

            # Convert datetime objects to ISO format strings for JSON serialization
            datetime_fields = [
                "start_date",
                "end_date",
                "last_triggered_at",
                "next_trigger_at",
                "created_at",
                "updated_at",
            ]
            for field in datetime_fields:
                if field in update_data and update_data[field] is not None:
                    if isinstance(update_data[field], datetime):
                        update_data[field] = update_data[field].isoformat()

            result = (
                self.client.table("price_adjustment_schedules")
                .update(update_data)
                .eq("id", str(schedule_id))
                .execute()
            )

            if result.data:
                return PriceAdjustmentSchedule(**result.data[0])
            return None
        except Exception as e:
            logger.error("Failed to update price adjustment schedule", error=str(e))
            return None

    def delete_price_adjustment_schedule(self, schedule_id: UUID) -> bool:
        """Delete a price adjustment schedule (soft delete by setting is_active=False)."""
        try:
            result = (
                self.client.table("price_adjustment_schedules")
                .update({"is_active": False})
                .eq("id", str(schedule_id))
                .execute()
            )

            return result.data is not None and len(result.data) > 0
        except Exception as e:
            logger.error("Failed to delete price adjustment schedule", error=str(e))
            return False
