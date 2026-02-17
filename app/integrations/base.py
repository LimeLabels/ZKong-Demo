"""
Base integration adapter interface.
All integrations must implement this interface to be compatible with the system.
"""

from abc import ABC, abstractmethod
from typing import Any

from fastapi import Request


class NormalizedProduct:
    """Normalized product data structure used across all integrations."""

    def __init__(
        self,
        source_id: str,
        source_variant_id: str | None = None,
        title: str = "",
        barcode: str | None = None,
        sku: str | None = None,
        price: float = 0.0,
        currency: str = "USD",
        image_url: str | None = None,
        **kwargs,
    ):
        self.source_id = source_id
        self.source_variant_id = source_variant_id
        self.title = title
        self.barcode = barcode
        self.sku = sku
        self.price = price
        self.currency = currency
        self.image_url = image_url
        self.extra_data = kwargs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for storage."""
        data = {
            "source_id": self.source_id,
            "source_variant_id": self.source_variant_id,
            "title": self.title,
            "barcode": self.barcode,
            "sku": self.sku,
            "price": self.price,
            "currency": self.currency,
            "image_url": self.image_url,
        }
        data.update(self.extra_data)
        return data


class NormalizedInventory:
    """Normalized inventory data structure used across all integrations."""

    def __init__(
        self,
        inventory_item_id: str,
        location_id: str | None = None,
        available: int | None = None,
        updated_at: str | None = None,
        **kwargs,
    ):
        self.inventory_item_id = inventory_item_id
        self.location_id = location_id
        self.available = available
        self.updated_at = updated_at
        self.extra_data = kwargs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        data = {
            "inventory_item_id": self.inventory_item_id,
            "location_id": self.location_id,
            "available": self.available,
            "updated_at": self.updated_at,
        }
        data.update(self.extra_data)
        return data


class BaseIntegrationAdapter(ABC):
    """Base class that all integrations must implement."""

    @abstractmethod
    def get_name(self) -> str:
        """
        Return integration name.

        Returns:
            Integration name (e.g., 'shopify', 'square', 'ncr')
        """
        pass

    @abstractmethod
    def verify_signature(self, payload: bytes, signature: str, headers: dict[str, str]) -> bool:
        """
        Verify webhook/event signature for authenticity.

        Args:
            payload: Raw webhook payload bytes
            signature: Signature string from headers
            headers: Request headers dictionary

        Returns:
            True if signature is valid, False otherwise
        """
        pass

    @abstractmethod
    def extract_store_id(self, headers: dict[str, str], payload: dict[str, Any]) -> str | None:
        """
        Extract store identifier from webhook/event.

        Args:
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Store identifier string, or None if not found
        """
        pass

    @abstractmethod
    def transform_product(self, raw_data: dict[str, Any]) -> list[NormalizedProduct]:
        """
        Transform integration-specific product data to normalized format.

        Args:
            raw_data: Raw product data from integration

        Returns:
            List of normalized products (one product may become multiple if variants)
        """
        pass

    @abstractmethod
    def transform_inventory(self, raw_data: dict[str, Any]) -> NormalizedInventory | None:
        """
        Transform integration-specific inventory data to normalized format.

        Args:
            raw_data: Raw inventory data from integration

        Returns:
            Normalized inventory object, or None if not applicable
        """
        pass

    @abstractmethod
    def get_supported_events(self) -> list[str]:
        """
        Return list of supported webhook/event types.

        Returns:
            List of event type strings (e.g., ['products/create', 'products/update'])
        """
        pass

    @abstractmethod
    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Handle a webhook event.

        Args:
            event_type: Type of event (e.g., 'products/create')
            request: FastAPI Request object
            headers: Request headers
            payload: Parsed webhook payload

        Returns:
            Response dictionary
        """
        pass

    async def subscribe_webhooks(self, store_config: dict[str, Any]) -> bool:
        """
        Subscribe to webhooks via integration's API (if applicable).

        Args:
            store_config: Store configuration including API credentials

        Returns:
            True if successful, False otherwise

        Note:
            Not all integrations support programmatic webhook subscription.
            Override this method if the integration supports it.
        """
        return False

    def validate_normalized_product(self, product: NormalizedProduct) -> tuple[bool, list[str]]:
        """
        Validate normalized product data.

        Args:
            product: Normalized product to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not product.title:
            errors.append("Title is required")

        if not product.barcode and not product.sku:
            errors.append("Barcode or SKU is required")

        if product.price is None or product.price < 0:
            errors.append("Price must be non-negative")

        return len(errors) == 0, errors
