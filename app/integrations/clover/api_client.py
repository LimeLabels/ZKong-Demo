"""
Clover REST API client for inventory items.
Uses limit/offset pagination. Base URL from clover_environment (sandbox vs production).
Supports list_items, list_items_modified_since (polling), and list_all_item_ids (ghost cleanup).
"""

import asyncio
import httpx
import structlog
from typing import Dict, Any, Optional, List

from app.config import settings

logger = structlog.get_logger()

# Default page size for list_items (Clover limit/offset)
DEFAULT_LIMIT = 100
# Delay between paginated requests to avoid rate limits (seconds)
PAGINATION_DELAY_SECONDS = 0.15


class CloverAPIError(Exception):
    """Raised when Clover API returns an error."""

    def __init__(self, status_code: int, message: str, body: Optional[str] = None):
        self.status_code = status_code
        self.message = message
        self.body = body
        super().__init__(f"Clover API error {status_code}: {message}")


class CloverAPIClient:
    """Async client for Clover REST API (items only)."""

    def __init__(
        self,
        access_token: str,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the Clover API client.

        Args:
            access_token: Bearer token (merchant API token or OAuth access token).
            base_url: Override base URL. If None, uses settings.clover_environment.
        """
        self.access_token = access_token
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            if settings.clover_environment == "sandbox":
                self.base_url = "https://apisandbox.dev.clover.com"
            else:
                self.base_url = "https://api.clover.com"
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
        # access_token must be the plaintext Clover OAuth access token (adapter passes decrypted token from decrypt_tokens_from_storage).
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_items(self, merchant_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all items for a merchant using limit/offset pagination.

        GET /v3/merchants/{mId}/items?limit=100&offset=0

        Args:
            merchant_id: Clover merchant ID (mId).

        Returns:
            List of item dicts (raw API shape).
        """
        all_items: List[Dict[str, Any]] = []
        offset = 0
        client = await self._get_client()

        while True:
            url = f"{self.base_url}/v3/merchants/{merchant_id}/items"
            params = {"limit": DEFAULT_LIMIT, "offset": offset}
            try:
                response = await client.get(
                    url,
                    headers=self._headers(),
                    params=params,
                )
            except httpx.RequestError as e:
                logger.error(
                    "Clover API request failed",
                    merchant_id=merchant_id,
                    offset=offset,
                    error=str(e),
                )
                raise CloverAPIError(0, str(e)) from e

            if response.status_code != 200:
                logger.error(
                    "Clover API error",
                    status_code=response.status_code,
                    body=response.text[:500],
                    merchant_id=merchant_id,
                )
                raise CloverAPIError(
                    response.status_code,
                    f"GET items failed: {response.status_code}",
                    body=response.text,
                )

            data = response.json()
            elements = data.get("elements") if isinstance(data, dict) else []
            if not elements:
                break
            all_items.extend(elements)
            if len(elements) < DEFAULT_LIMIT:
                break
            offset += DEFAULT_LIMIT
            await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        return all_items

    async def get_item(
        self, merchant_id: str, item_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a single item by ID.

        GET /v3/merchants/{mId}/items/{itemId}

        Args:
            merchant_id: Clover merchant ID (mId).
            item_id: Clover item ID (with or without "I:" prefix; prefix is stripped).

        Returns:
            Item dict or None if not found.
        """
        raw_id = str(item_id).strip()
        if raw_id.upper().startswith("I:"):
            raw_id = raw_id[2:].strip()
        if not raw_id:
            return None

        client = await self._get_client()
        url = f"{self.base_url}/v3/merchants/{merchant_id}/items/{raw_id}"
        try:
            response = await client.get(url, headers=self._headers())
        except httpx.RequestError as e:
            logger.error(
                "Clover API get_item request failed",
                merchant_id=merchant_id,
                item_id=raw_id,
                error=str(e),
            )
            raise CloverAPIError(0, str(e)) from e

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.error(
                "Clover API error get_item",
                status_code=response.status_code,
                body=response.text[:500],
                merchant_id=merchant_id,
                item_id=raw_id,
            )
            raise CloverAPIError(
                response.status_code,
                f"GET item failed: {response.status_code}",
                body=response.text,
            )

        return response.json()

    async def update_item(
        self,
        merchant_id: str,
        item_id: str,
        price_cents: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Update an item's price (and optionally other fields).

        POST /v3/merchants/{mId}/items/{itemId}
        Clover v3 Inventory API requires POST (not PATCH) to update an existing item.
        Price must be in cents. Clover API expects integer cents (e.g., $20.99 = 2099).

        Args:
            merchant_id: Clover merchant ID (mId).
            item_id: Clover item ID (with or without "I:" prefix; prefix is stripped).
            price_cents: Price in cents (e.g., 2099 for $20.99).
            **kwargs: Optional extra fields to send (e.g., name, cost, priceWithoutVat).

        Returns:
            Updated item dict from API response.

        Raises:
            CloverAPIError: On non-2xx response.
        """
        raw_id = str(item_id).strip()
        if raw_id.upper().startswith("I:"):
            raw_id = raw_id[2:].strip()
        if not raw_id:
            raise CloverAPIError(0, "item_id is required and cannot be empty after stripping I: prefix")

        client = await self._get_client()
        url = f"{self.base_url}/v3/merchants/{merchant_id}/items/{raw_id}"
        body: Dict[str, Any] = {"price": price_cents, **kwargs}
        try:
            response = await client.post(
                url,
                headers=self._headers(),
                json=body,
            )
        except httpx.RequestError as e:
            logger.error(
                "Clover API update_item request failed",
                merchant_id=merchant_id,
                item_id=raw_id,
                error=str(e),
            )
            raise CloverAPIError(0, str(e)) from e

        if response.status_code != 200:
            logger.error(
                "Clover API error update_item",
                status_code=response.status_code,
                body=response.text[:500],
                merchant_id=merchant_id,
                item_id=raw_id,
            )
            raise CloverAPIError(
                response.status_code,
                f"POST item failed: {response.status_code}",
                body=response.text,
            )

        return response.json()

    async def list_items_modified_since(
        self,
        merchant_id: str,
        modified_since: int,
        limit: int = DEFAULT_LIMIT,
    ) -> List[Dict[str, Any]]:
        """
        Fetch items modified since timestamp (incremental sync for polling).

        GET /v3/merchants/{mId}/items?filter=modifiedTime>={timestamp}&limit=100&offset=0

        Args:
            merchant_id: Clover merchant ID (mId).
            modified_since: Unix timestamp in milliseconds; items with modifiedTime >= this are returned.
            limit: Max items per request.

        Returns:
            List of item dicts (raw API shape).
        """
        all_items: List[Dict[str, Any]] = []
        offset = 0
        client = await self._get_client()

        while True:
            url = f"{self.base_url}/v3/merchants/{merchant_id}/items"
            params = {
                "limit": limit,
                "offset": offset,
                "filter": f"modifiedTime>={modified_since}",
            }
            try:
                response = await client.get(
                    url,
                    headers=self._headers(),
                    params=params,
                )
            except httpx.RequestError as e:
                logger.error(
                    "Clover API list_items_modified_since request failed",
                    merchant_id=merchant_id,
                    modified_since=modified_since,
                    error=str(e),
                )
                raise CloverAPIError(0, str(e)) from e

            if response.status_code != 200:
                logger.error(
                    "Clover API error list_items_modified_since",
                    status_code=response.status_code,
                    body=response.text[:500],
                    merchant_id=merchant_id,
                )
                raise CloverAPIError(
                    response.status_code,
                    f"GET items (modified since) failed: {response.status_code}",
                    body=response.text,
                )

            data = response.json()
            elements = data.get("elements") if isinstance(data, dict) else []
            if not elements:
                break
            all_items.extend(elements)
            if len(elements) < limit:
                break
            offset += limit
            await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        return all_items

    async def list_all_item_ids(self, merchant_id: str) -> List[str]:
        """
        Fetch all item IDs for a merchant (for ghost-item cleanup).
        Uses list_items and extracts IDs to avoid holding full payloads.

        Args:
            merchant_id: Clover merchant ID (mId).

        Returns:
            List of Clover item IDs (without I: prefix).
        """
        ids: List[str] = []
        offset = 0
        client = await self._get_client()

        while True:
            url = f"{self.base_url}/v3/merchants/{merchant_id}/items"
            params = {"limit": DEFAULT_LIMIT, "offset": offset}
            try:
                response = await client.get(
                    url,
                    headers=self._headers(),
                    params=params,
                )
            except httpx.RequestError as e:
                logger.error(
                    "Clover API list_all_item_ids request failed",
                    merchant_id=merchant_id,
                    offset=offset,
                    error=str(e),
                )
                raise CloverAPIError(0, str(e)) from e

            if response.status_code != 200:
                logger.error(
                    "Clover API error list_all_item_ids",
                    status_code=response.status_code,
                    body=response.text[:500],
                    merchant_id=merchant_id,
                )
                raise CloverAPIError(
                    response.status_code,
                    f"GET items failed: {response.status_code}",
                    body=response.text,
                )

            data = response.json()
            elements = data.get("elements") if isinstance(data, dict) else []
            for item in elements:
                item_id = item.get("id")
                if item_id:
                    ids.append(str(item_id))
            if len(elements) < DEFAULT_LIMIT:
                break
            offset += DEFAULT_LIMIT
            await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        return ids
