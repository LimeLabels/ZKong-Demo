"""
Supabase service layer for database operations.
Handles CRUD operations for products, sync_queue, sync_log, and store_mappings.
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from supabase import create_client, Client
import structlog
from app.config import settings
from app.models.database import (
    Product,
    SyncQueueItem,
    SyncLog,
    StoreMapping,
    HipoinkProduct,
)

logger = structlog.get_logger()


class SupabaseService:
    """Service for interacting with Supabase database."""

    def __init__(self):
        """Initialize Supabase client."""
        self.client: Client = create_client(
            settings.supabase_url, settings.supabase_service_key
        )

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
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("source_system", source_system)
                .eq("source_store_id", source_store_id)
                .eq("is_active", True)
                .single()
                .execute()
            )

            if result.data:
                return StoreMapping(**result.data)
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
                update_data = product.dict(
                    exclude_none=True, exclude={"id", "created_at"}
                )
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
                result = (
                    self.client.table("products")
                    .insert(product.dict(exclude_none=True, exclude={"id"}))
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
