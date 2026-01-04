"""
Pydantic models for Supabase database tables.
These models represent the structure of data stored in Supabase.
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class StoreMapping(BaseModel):
    """Model for store_mappings table."""

    id: Optional[UUID] = None
    source_system: str
    source_store_id: str
    # Hipoink ESL System Configuration
    hipoink_store_code: str  # Store code for Hipoink API (required)
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Product(BaseModel):
    """Model for products table."""

    id: Optional[UUID] = None
    source_system: str
    source_id: str
    source_variant_id: Optional[str] = None
    title: str
    barcode: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    image_url: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    normalized_data: Optional[Dict[str, Any]] = None
    status: str = "pending"
    validation_errors: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SyncQueueItem(BaseModel):
    """Model for sync_queue table."""

    id: Optional[UUID] = None
    product_id: UUID
    store_mapping_id: UUID
    operation: str  # 'create', 'update', 'delete'
    status: str = "pending"  # pending, syncing, succeeded, failed
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    scheduled_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SyncLog(BaseModel):
    """Model for sync_log table."""

    id: Optional[UUID] = None
    sync_queue_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    store_mapping_id: Optional[UUID] = None
    operation: str
    status: str  # succeeded, failed
    hipoink_product_code: Optional[str] = None  # Hipoink product code (pc field)
    request_payload: Optional[Dict[str, Any]] = None
    response_payload: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None


class HipoinkProduct(BaseModel):
    """Model for hipoink_products table - tracks product mappings."""

    id: Optional[UUID] = None
    product_id: UUID
    store_mapping_id: UUID
    hipoink_product_code: str  # Product code (pc) in Hipoink
    last_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
