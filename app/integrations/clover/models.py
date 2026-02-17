"""
Pydantic models for Clover webhook payloads and inventory item API responses.
"""

from typing import Any, Literal

from pydantic import BaseModel


class CloverWebhookUpdate(BaseModel):
    """Single update in a Clover webhook payload."""

    objectId: str  # e.g. "I:ITEM_ID" for inventory
    type: Literal["CREATE", "UPDATE", "DELETE"]
    ts: int  # Unix time in milliseconds


class CloverWebhookPayload(BaseModel):
    """Clover webhook payload: appId + merchants map to list of updates."""

    appId: str | None = None
    merchants: dict[str, list[CloverWebhookUpdate]] = {}

    class Config:
        extra = "allow"  # Allow verificationCode and other fields


class CloverWebhookVerification(BaseModel):
    """One-time verification POST when saving Webhook URL in dashboard."""

    verificationCode: str


class CloverItem(BaseModel):
    """
    Clover inventory item from REST API.
    Price is in cents (integer). id is the item identifier.
    """

    id: str | None = None
    name: str | None = None
    price: int | None = None  # Cents
    sku: str | None = None
    code: str | None = None  # Alternate/barcode field in some responses
    alternateName: str | None = None
    priceType: str | None = None
    defaultTaxRates: list[dict[str, Any]] | None = None
    cost: int | None = None  # cost

    class Config:
        extra = "allow"
