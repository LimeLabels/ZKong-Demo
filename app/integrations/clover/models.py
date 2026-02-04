"""
Pydantic models for Clover webhook payloads and inventory item API responses.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Literal


class CloverWebhookUpdate(BaseModel):
    """Single update in a Clover webhook payload."""

    objectId: str  # e.g. "I:ITEM_ID" for inventory
    type: Literal["CREATE", "UPDATE", "DELETE"]
    ts: int  # Unix time in milliseconds


class CloverWebhookPayload(BaseModel):
    """Clover webhook payload: appId + merchants map to list of updates."""

    appId: Optional[str] = None
    merchants: Dict[str, List[CloverWebhookUpdate]] = {}

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

    id: Optional[str] = None
    name: Optional[str] = None
    price: Optional[int] = None  # Cents
    sku: Optional[str] = None
    code: Optional[str] = None  # Alternate/barcode field in some responses
    alternateName: Optional[str] = None
    priceType: Optional[str] = None
    defaultTaxRates: Optional[List[Dict[str, Any]]] = None
    cost: Optional[int] = None

    class Config:
        extra = "allow"
