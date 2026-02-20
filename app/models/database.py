"""
Pydantic models for Supabase database tables.
These models represent the structure of data stored in Supabase.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class StoreMapping(BaseModel):
    """Model for store_mappings table."""

    id: UUID | None = None
    source_system: str
    source_store_id: str
    # Hipoink ESL System Configuration
    hipoink_store_code: str | None = None  # Store code for Hipoink API (optional until onboarded)
    is_active: bool = True
    user_email: str | None = None  # Email of connected user
    metadata: dict[str, Any] | None = None  # Can store timezone, Shopify credentials, etc.
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Product(BaseModel):
    """Model for products table."""

    id: UUID | None = None
    source_system: str
    source_id: str
    source_variant_id: str | None = None
    source_store_id: str | None = (
        None  # Merchant/store ID for multi-tenant isolation (merchant_id for Square, shop_domain for Shopify)
    )
    title: str
    barcode: str | None = None
    sku: str | None = None
    price: float | None = None
    currency: str = "USD"
    image_url: str | None = None
    raw_data: dict[str, Any] | None = None
    normalized_data: dict[str, Any] | None = None
    status: str = "pending"
    validation_errors: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SyncQueueItem(BaseModel):
    """Model for sync_queue table."""

    id: UUID | None = None
    product_id: UUID
    store_mapping_id: UUID
    operation: str  # 'create', 'update', 'delete'
    status: str = "pending"  # pending, syncing, succeeded, failed
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    scheduled_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SyncLog(BaseModel):
    """Model for sync_log table."""

    id: UUID | None = None
    sync_queue_id: UUID | None = None
    product_id: UUID | None = None
    store_mapping_id: UUID | None = None
    operation: str
    status: str  # succeeded, failed
    hipoink_product_code: str | None = None  # Hipoink product code (pc field)
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None


class HipoinkProduct(BaseModel):
    """Model for hipoink_products table - tracks product mappings."""

    id: UUID | None = None
    product_id: UUID
    store_mapping_id: UUID
    hipoink_product_code: str  # Product code (pc) in Hipoink
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PriceAdjustmentSchedule(BaseModel):
    """Model for price_adjustment_schedules table - time-based pricing schedules."""

    id: UUID | None = None
    store_mapping_id: UUID
    name: str  # Schedule name
    order_number: str  # Unique order number for tracking
    products: dict[
        str, Any
    ]  # JSON: List of {"pc": "barcode", "pp": price, "original_price": price}
    start_date: datetime  # Schedule start date
    end_date: datetime | None = None  # Schedule end date (optional)
    repeat_type: str = "none"  # none, daily, weekly, monthly
    trigger_days: list | None = None  # Days of week: [1,2,3] = Mon, Tue, Wed (1=Mon, 7=Sun)
    trigger_stores: list | None = None  # Store codes to trigger
    time_slots: list  # List of {"start_time": "09:00", "end_time": "17:00"}
    multiplier_percentage: float | None = (
        None  # Percentage multiplier (e.g., 10.0 for 10% increase, -5.0 for 5% decrease)
    )
    is_active: bool = True
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
