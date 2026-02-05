"""
Supabase service layer for database operations.
Handles CRUD operations for products, sync_queue, sync_log, and store_mappings.
"""

from typing import List, Optional, Dict, Any, Tuple
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

    def update_store_mapping_metadata(
        self, mapping_id: UUID, metadata: Dict[str, Any]
    ) -> Optional[StoreMapping]:
        """
        Merge and persist store mapping metadata (e.g. clover_last_sync_time, clover_poll_count).
        Existing metadata is preserved; provided keys are merged/overwritten.

        Args:
            mapping_id: Store mapping UUID
            metadata: Dict of keys to merge into existing metadata

        Returns:
            Updated StoreMapping or None if not found
        """
        try:
            existing = self.get_store_mapping_by_id(mapping_id)
            if not existing:
                return None
            merged = dict(existing.metadata or {})
            merged.update(metadata)
            result = (
                self.client.table("store_mappings")
                .update({"metadata": merged})
                .eq("id", str(mapping_id))
                .execute()
            )
            if result.data:
                return StoreMapping(**result.data[0])
            return None
        except Exception as e:
            logger.error(
                "Failed to update store mapping metadata",
                mapping_id=str(mapping_id),
                error=str(e),
            )
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

    def get_store_mapping_by_hipoink_code(
        self, source_system: str, hipoink_store_code: str
    ) -> Optional[StoreMapping]:
        """
        Get store mapping by source system and Hipoink store code.
        Used for onboarding to find existing mappings (1:1 relationship).

        Args:
            source_system: Source system name (e.g., 'ncr', 'square', 'shopify')
            hipoink_store_code: Hipoink ESL store code

        Returns:
            StoreMapping if found, None otherwise
        """
        try:
            result = (
                self.client.table("store_mappings")
                .select("*")
                .eq("source_system", source_system)
                .eq("hipoink_store_code", hipoink_store_code)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return StoreMapping(**result.data[0])
            return None
        except Exception as e:
            logger.error(
                "Failed to get store mapping by Hipoink code",
                source_system=source_system,
                hipoink_store_code=hipoink_store_code,
                error=str(e),
            )
            return None

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

    def create_or_update_product(self, product: Product) -> Tuple[Product, bool]:
        """
        Create or update product in database.
        Uses upsert based on source_system, source_id, and source_variant_id.
        
        Note: This method will NOT re-activate products that are marked as deleted.
        If a product is deleted, it will remain deleted and not be updated.

        Args:
            product: Product to create or update

        Returns:
            Tuple of (Product, changed: bool)
            - changed=True if product is new OR fields actually changed
            - changed=False if product exists and no fields changed
        """
        try:
            # Check if product exists (including deleted ones to check status)
            # CRITICAL: Pass source_store_id for multi-tenant isolation
            existing = self.get_product_by_source(
                product.source_system, 
                product.source_id, 
                product.source_variant_id,
                source_store_id=product.source_store_id,  # Multi-tenant isolation
                include_deleted=True
            )

            if existing:
                # Don't update products that are already marked as deleted
                if existing.status == "deleted":
                    logger.debug(
                        "Skipping update for deleted product",
                        product_id=str(existing.id),
                        source_system=product.source_system,
                        source_id=product.source_id,
                    )
                    return existing, False  # Return existing, no change
                
                # CHECK IF ACTUALLY CHANGED
                if not self._product_has_changed(existing, product):
                    logger.debug(
                        "Product unchanged, skipping update and queue",
                        product_id=str(existing.id),
                        source_system=product.source_system,
                        source_id=product.source_id,
                        source_variant_id=product.source_variant_id,
                    )
                    return existing, False  # Return existing, no change
                
                # Product has changed, update it
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
                    logger.debug(
                        "Product updated (changed)",
                        product_id=str(existing.id),
                        source_id=product.source_id,
                    )
                    return Product(**result.data[0]), True  # Updated = changed
                raise Exception("No data returned from update")
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
                    logger.debug(
                        "Product created (new)",
                        source_id=product.source_id,
                    )
                    return Product(**result.data[0]), True  # New = changed
                raise Exception("No data returned from insert")
        except Exception as e:
            logger.error("Failed to create or update product", error=str(e))
            raise

    def get_product_by_source(
        self,
        source_system: str,
        source_id: str,
        source_variant_id: Optional[str] = None,
        source_store_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Optional[Product]:
        """
        Get product by source system and IDs.
        
        Args:
            source_system: Source system name (e.g., 'square')
            source_id: Source product ID
            source_variant_id: Optional variant ID
            source_store_id: Merchant/store ID to filter by (CRITICAL for multi-tenant safety)
            include_deleted: If True, include products with status 'deleted' (default: False)
        
        Returns:
            Product object or None if not found
        """
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
            
            # CRITICAL: Filter by store for multi-tenant safety
            if source_store_id:
                query = query.eq("source_store_id", source_store_id)
            else:
                logger.warning(
                    "get_product_by_source called without source_store_id - may match products from other merchants!",
                    source_system=source_system,
                    source_id=source_id,
                )
            
            # Optionally include deleted products
            if not include_deleted:
                query = query.neq("status", "deleted")

            result = query.limit(1).execute()  # Use limit(1) instead of single() for safety

            if result.data and len(result.data) > 0:
                return Product(**result.data[0])
            return None
        except Exception as e:
            # Not found is expected for new products - don't log as error
            if "PGRST116" not in str(e):  # Suppress "The result contains 0 rows"
                logger.debug(
                    "Failed to get product by source (may not exist)",
                    source_system=source_system,
                    source_id=source_id,
                    source_variant_id=source_variant_id,
                    source_store_id=source_store_id,
                    error=str(e),
                )
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
        self, 
        source_system: str, 
        source_id: str, 
        source_store_id: Optional[str] = None,
        exclude_deleted: bool = True
    ) -> List[Product]:
        """
        Get all products by source system and source ID.
        Used to find all variants of a product when deleting.
        
        Args:
            source_system: Source system name (e.g., 'square')
            source_id: Source product ID
            source_store_id: Merchant/store ID to filter by (RECOMMENDED for multi-tenant safety)
            exclude_deleted: If True, exclude products with status 'deleted' (default: True)
        
        Returns:
            List of Product objects (all variants)
        """
        try:
            query = (
                self.client.table("products")
                .select("*")
                .eq("source_system", source_system)
                .eq("source_id", source_id)
            )
            
            # Filter by store for multi-tenant safety
            if source_store_id:
                query = query.eq("source_store_id", source_store_id)
            else:
                logger.warning(
                    "get_products_by_source_id called without source_store_id - may return products from other merchants!",
                    source_system=source_system,
                    source_id=source_id,
                )
            
            # Exclude deleted products by default to prevent re-queuing them for deletion
            if exclude_deleted:
                query = query.neq("status", "deleted")
            
            result = query.execute()

            if result.data:
                return [Product(**item) for item in result.data]
            return []
        except Exception as e:
            logger.error(
                "Failed to get products by source ID",
                source_system=source_system,
                source_id=source_id,
                source_store_id=source_store_id,
                error=str(e),
            )
            return []

    def get_products_by_system(
        self, 
        source_system: str, 
        source_store_id: Optional[str] = None,
        exclude_deleted: bool = True
    ) -> List[Product]:
        """
        Fetch products by source system, optionally filtered by store.
        
        Args:
            source_system: Source system name (e.g., 'square', 'shopify')
            source_store_id: Merchant/store ID to filter by (STRONGLY RECOMMENDED for multi-tenant safety)
            exclude_deleted: If True, exclude products with status 'deleted' (default: True)
        
        Returns:
            List of Product objects for that store
        """
        try:
            query = (
                self.client.table("products")
                .select("*")
                .eq("source_system", source_system)
            )
            
            # CRITICAL: Filter by store for multi-tenant isolation
            if source_store_id:
                query = query.eq("source_store_id", source_store_id)
            else:
                logger.warning(
                    "get_products_by_system called without source_store_id - returning ALL products across all merchants!",
                    source_system=source_system,
                    stack_info=True,  # Log stack trace to find caller
                )
            
            # Exclude deleted products by default to prevent re-processing them
            if exclude_deleted:
                query = query.neq("status", "deleted")
            
            result = query.execute()

            if result.data:
                return [Product(**item) for item in result.data]
            return []
        except Exception as e:
            logger.error(
                "Failed to get products by system",
                source_system=source_system,
                source_store_id=source_store_id,
                error=str(e),
            )
            return []

    def update_product_status(self, product_id: Any, status: str) -> None:
        """
        Update the status of a product (e.g., marking it as 'deleted').
        
        When marking as 'deleted', also clears SKU and barcode to allow reuse.
        This ensures deleted products don't block SKU/barcode reuse while preserving
        product history in the database.

        Args:
            product_id: Product UUID or string ID
            status: New status (e.g., 'deleted', 'pending', 'validated')
        """
        try:
            update_data = {"status": status}
            
            # When soft-deleting, clear SKU and barcode so they can be reused
            # This prevents unique constraint violations when reusing SKUs/barcodes
            if status == "deleted":
                update_data["sku"] = None
                update_data["barcode"] = None
                logger.debug(
                    "Clearing SKU and barcode for deleted product",
                    product_id=str(product_id),
                )
            
            self.client.table("products").update(update_data).eq(
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

    def _product_has_changed(self, existing: Product, new_product: Product) -> bool:
        """
        Check if product data has actually changed.
        Only compares fields that matter for Hipoink ESL sync.
        
        Args:
            existing: Existing product from database
            new_product: New product data from webhook/API
            
        Returns:
            True if product changed, False if identical
        """
        # Fields that matter for ESL display and sync
        sync_relevant_fields = [
            'title',           # Product name
            'barcode',         # Barcode for ESL
            'sku',             # SKU for ESL
            'price',           # Price (most common change)
            'currency',        # Currency (if price changes, currency might too)
            'image_url',       # Product image
            'status',          # Validation status (pending -> validated)
            'validation_errors'  # Validation state changes
        ]
        
        for field in sync_relevant_fields:
            existing_val = getattr(existing, field, None)
            new_val = getattr(new_product, field, None)
            
            # Handle None comparisons
            if existing_val is None and new_val is None:
                continue
            if existing_val is None or new_val is None:
                logger.debug(
                    "Product field changed (None comparison)",
                    field=field,
                    old=existing_val,
                    new=new_val,
                )
                return True
            
            # Compare values
            if existing_val != new_val:
                logger.debug(
                    "Product field changed",
                    field=field,
                    old=existing_val,
                    new=new_val,
                )
                return True
        
        # CRITICAL: Check normalized_data fields (f1-f4) for unit cost changes
        # Unit cost changes affect f1-f4 but may not change price
        existing_normalized = existing.normalized_data or {}
        new_normalized = new_product.normalized_data or {}
        
        # Check f1-f4 fields (unit cost and quantity fields)
        for field in ['f1', 'f2', 'f3', 'f4']:
            existing_val = existing_normalized.get(field)
            new_val = new_normalized.get(field)
            
            # Handle None comparisons
            if existing_val is None and new_val is None:
                continue
            if existing_val is None or new_val is None:
                logger.debug(
                    "Product normalized_data field changed (None comparison)",
                    field=field,
                    old=existing_val,
                    new=new_val,
                    product_id=str(existing.id) if existing.id else None,
                )
                return True
            
            # Compare values (as strings since they're stored as strings)
            if str(existing_val) != str(new_val):
                logger.debug(
                    "Product normalized_data field changed",
                    field=field,
                    old=existing_val,
                    new=new_val,
                    product_id=str(existing.id) if existing.id else None,
                )
                return True
        
        return False

    def delete_product(self, product_id: Any) -> bool:
        """
        Delete a product from the database.
        
        This method handles cascading deletes by removing related records first:
        - sync_log entries (via sync_queue_id)
        - sync_queue items
        - hipoink_products mappings
        - Finally, the product itself

        Args:
            product_id: Product UUID or string ID

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            product_id_str = str(product_id)
            
            # Step 1: Get all sync_queue items for this product to find sync_log entries
            try:
                sync_queue_items = (
                    self.client.table("sync_queue")
                    .select("id")
                    .eq("product_id", product_id_str)
                    .execute()
                )
                
                sync_queue_ids = [item["id"] for item in sync_queue_items.data] if sync_queue_items.data else []
                
                # Step 2: Delete sync_log entries for these sync_queue items
                if sync_queue_ids:
                    try:
                        for queue_id in sync_queue_ids:
                            self.client.table("sync_log").delete().eq("sync_queue_id", str(queue_id)).execute()
                        logger.debug("Cleaned up sync_log entries", product_id=product_id_str, count=len(sync_queue_ids))
                    except Exception as e:
                        logger.warning("Failed to clean up sync_log entries", product_id=product_id_str, error=str(e))
                
                # Step 3: Delete sync_queue items
                if sync_queue_ids:
                    self.client.table("sync_queue").delete().eq("product_id", product_id_str).execute()
                    logger.debug("Cleaned up sync_queue items", product_id=product_id_str, count=len(sync_queue_ids))
            except Exception as e:
                logger.warning("Failed to clean up sync_queue/sync_log items", product_id=product_id_str, error=str(e))
            
            # Step 4: Delete hipoink_products mappings
            try:
                self.client.table("hipoink_products").delete().eq("product_id", product_id_str).execute()
                logger.debug("Cleaned up hipoink_products mappings", product_id=product_id_str)
            except Exception as e:
                logger.warning("Failed to clean up hipoink_products mappings", product_id=product_id_str, error=str(e))
            
            # Step 5: Delete the product itself
            result = (
                self.client.table("products")
                .delete()
                .eq("id", product_id_str)
                .execute()
            )
            
            # Check if any rows were actually deleted
            deleted = result.data is not None and len(result.data) > 0 if isinstance(result.data, list) else result.data is not None
            
            if deleted:
                logger.info(
                    "Deleted product from database",
                    product_id=product_id_str,
                    deleted_count=len(result.data) if isinstance(result.data, list) else 1
                )
                return True
            else:
                # No rows deleted - product might not exist or already deleted
                logger.warning(
                    "No product deleted - product may not exist or already deleted",
                    product_id=product_id_str
                )
                return False
        except Exception as e:
            logger.error(
                "Failed to delete product from database",
                product_id=str(product_id),
                error=str(e),
                error_type=type(e).__name__,
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

    def get_product_by_source_variant_id(
        self, source_variant_id: str
    ) -> Optional[Product]:
        """
        Get product by source_variant_id (e.g., Square variation ID).
        
        Args:
            source_variant_id: The source system's variant ID
            
        Returns:
            Product if found, None otherwise
        """
        try:
            query = self.client.table("products").select("*").eq("source_variant_id", source_variant_id)
            result = query.limit(1).execute()
            
            if result.data and len(result.data) > 0:
                return Product(**result.data[0])
            return None
        except Exception as e:
            logger.error(
                "Failed to get product by source_variant_id", 
                source_variant_id=source_variant_id, 
                error=str(e)
            )
            return None

    # Sync Queue

    def get_existing_pending_queue_item(
        self, product_id: UUID, store_mapping_id: UUID, operation: str
    ) -> Optional[SyncQueueItem]:
        """
        Check if a pending queue item already exists for the same product, store, and operation.

        Args:
            product_id: Product UUID
            store_mapping_id: Store mapping UUID
            operation: Operation type ('create', 'update', 'delete')

        Returns:
            Existing SyncQueueItem if found, None otherwise
        """
        try:
            result = (
                self.client.table("sync_queue")
                .select("*")
                .eq("product_id", str(product_id))
                .eq("store_mapping_id", str(store_mapping_id))
                .eq("operation", operation)
                .eq("status", "pending")
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return SyncQueueItem(**result.data[0])
            return None
        except Exception as e:
            logger.warning(
                "Failed to check for existing pending queue item",
                error=str(e),
            )
            return None

    def add_to_sync_queue(
        self, product_id: UUID, store_mapping_id: UUID, operation: str
    ) -> Optional[SyncQueueItem]:
        """
        Add product to sync queue with deduplication.

        Checks if a pending queue item already exists for the same product,
        store mapping, and operation. If found, returns the existing item instead
        of creating a duplicate.

        Args:
            product_id: Product UUID
            store_mapping_id: Store mapping UUID
            operation: Operation type ('create', 'update', 'delete')

        Returns:
            Created or existing SyncQueueItem, or None if duplicate found
        """
        try:
            # Check for existing pending queue item
            existing = self.get_existing_pending_queue_item(
                product_id, store_mapping_id, operation
            )
            if existing:
                logger.debug(
                    "Skipping duplicate queue item",
                    product_id=str(product_id),
                    store_mapping_id=str(store_mapping_id),
                    operation=operation,
                    existing_queue_item_id=str(existing.id),
                )
                return existing

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
            
            schedules = [PriceAdjustmentSchedule(**item) for item in result.data]
            
            if schedules:
                logger.info(
                    "Found schedules due for trigger",
                    count=len(schedules),
                    schedule_ids=[str(s.id) for s in schedules],
                    next_trigger_times=[s.next_trigger_at.isoformat() if s.next_trigger_at else None for s in schedules],
                )
            
            return schedules
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
