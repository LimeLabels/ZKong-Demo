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
                self.base_url = "https://sandbox.dev.clover.com"
            else:
                self.base_url = "https://api.clover.com"
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
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
            # Clover may return {"elements": [...]} or a list; normalize to list
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "elements" in data:
                items = data.get("elements", [])
            else:
                items = data if isinstance(data, list) else []

            all_items.extend(items)
            if len(items) < DEFAULT_LIMIT:
                break
            offset += DEFAULT_LIMIT

            # Rate limiting: small delay between pages
            if offset > 0:
                await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        logger.info(
            "Clover list_items completed",
            merchant_id=merchant_id,
            total_items=len(all_items),
        )
        return all_items

    async def get_item(
        self,
        merchant_id: str,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a single item by ID.

        GET /v3/merchants/{mId}/items/{itemId}

        Args:
            merchant_id: Clover merchant ID.
            item_id: Clover item ID (without the "I:" prefix).

        Returns:
            Item dict or None if 404.
        """
        client = await self._get_client()
        url = f"{self.base_url}/v3/merchants/{merchant_id}/items/{item_id}"
        try:
            response = await client.get(url, headers=self._headers())
        except httpx.RequestError as e:
            logger.error(
                "Clover API request failed",
                merchant_id=merchant_id,
                item_id=item_id,
                error=str(e),
            )
            raise CloverAPIError(0, str(e)) from e

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.error(
                "Clover API error",
                status_code=response.status_code,
                body=response.text[:500],
                merchant_id=merchant_id,
                item_id=item_id,
            )
            raise CloverAPIError(
                response.status_code,
                f"GET item failed: {response.status_code}",
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
            modified_since: Unix timestamp in MILLISECONDS; items with modifiedTime >= this are returned.
            limit: Page size (default 100).

        Returns:
            List of item dicts (raw API shape). First run with modified_since=0 returns all items.
        """
        all_items: List[Dict[str, Any]] = []
        offset = 0
        client = await self._get_client()

        while True:
            url = f"{self.base_url}/v3/merchants/{merchant_id}/items"
            params = {
                "filter": f"modifiedTime>={modified_since}",
                "limit": limit,
                "offset": offset,
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
                    offset=offset,
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
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "elements" in data:
                items = data.get("elements", [])
            else:
                items = data if isinstance(data, list) else []

            all_items.extend(items)
            if len(items) < limit:
                break
            offset += limit
            if offset > 0:
                await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        logger.debug(
            "Clover list_items_modified_since completed",
            merchant_id=merchant_id,
            modified_since=modified_since,
            total_items=len(all_items),
        )
        return all_items

    async def list_all_item_ids(self, merchant_id: str) -> List[str]:
        """
        Fetch only item IDs for ghost-item cleanup (lightweight).

        GET /v3/merchants/{mId}/items with minimal payload.
        If the API does not support sparse fields, we still paginate and collect ids.

        Args:
            merchant_id: Clover merchant ID (mId).

        Returns:
            List of Clover item ID strings.
        """
        all_ids: List[str] = []
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
                    f"GET items (ids) failed: {response.status_code}",
                    body=response.text,
                )

            data = response.json()
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "elements" in data:
                items = data.get("elements", [])
            else:
                items = data if isinstance(data, list) else []

            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    all_ids.append(str(item["id"]))
                elif isinstance(item, str):
                    all_ids.append(item)

            if len(items) < DEFAULT_LIMIT:
                break
            offset += DEFAULT_LIMIT
            if offset > 0:
                await asyncio.sleep(PAGINATION_DELAY_SECONDS)

        logger.debug(
            "Clover list_all_item_ids completed",
            merchant_id=merchant_id,
            total_ids=len(all_ids),
        )
        return all_ids
