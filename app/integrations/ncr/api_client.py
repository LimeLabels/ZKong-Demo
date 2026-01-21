"""
NCR PRO Catalog API client.
Handles product create, price update, and product delete (via status update) operations.
"""

import httpx
import structlog
import hashlib
import hmac
import base64
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from email.utils import formatdate
from urllib.parse import urlparse

from app.integrations.ncr.models import (
    SaveMultipleItemPricesRequest,
    ItemWriteData,
    ItemPriceWriteData,
    MultiLanguageTextData,
)

logger = structlog.get_logger()


class NCRAPIClient:
    """Client for making NCR PRO Catalog API calls."""

    def __init__(
        self,
        base_url: str = "https://api.ncr.com/catalog",
        shared_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        organization: Optional[str] = None,
        enterprise_unit: Optional[str] = None,
    ):
        """
        Initialize NCR API client.

        Args:
            base_url: NCR API base URL
            shared_key: NCR shared key (bsp-shared-key) for Authorization header
            secret_key: NCR secret key (bsp-secret-key) for HMAC signing
            organization: NCR organization identifier (bsp-organization)
            enterprise_unit: Enterprise unit identifier (bsp-site-id)
        """
        self.base_url = base_url.rstrip("/")
        self.organization = organization
        self.enterprise_unit = enterprise_unit
        self.shared_key = shared_key
        self.secret_key = secret_key
        
        # Base headers (Authorization will be added per-request with HMAC)
        self.base_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        if organization:
            self.base_headers["nep-organization"] = organization
        if enterprise_unit:
            self.base_headers["nep-enterprise-unit"] = enterprise_unit
            
        self.client = httpx.AsyncClient(timeout=30.0)
    
    def _generate_signature(
        self, 
        method: str, 
        uri: str, 
        content_type: str,
        content_md5: str,
        organization: str,
        date: datetime,
    ) -> str:
        """
        Generate HMAC-SHA512 signature for NCR API authentication.
        
        Based on NCR Postman pre-request script:
        1. Create nonce from date: date.toISOString().slice(0, 19) + '.000Z'
        2. Create signing key: secret_key + nonce
        3. Create signable content: METHOD\nPATH\ncontent-type\ncontent-md5\nnep-organization
        4. HMAC-SHA512(signable_content, signing_key)
        5. Base64 encode result
        """
        if not self.secret_key:
            return ""
        
        # Create nonce from date (ISO format: 2026-01-12T12:00:00.000Z)
        nonce = date.strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
        
        # Signing key = secret_key + nonce
        signing_key = self.secret_key + nonce
        
        # Build signable content (filter out empty values, join with newlines)
        params = [
            method,           # PUT
            uri,              # /catalog/v2/items/itemObject
            content_type,     # application/json
            content_md5,      # MD5 hash of body
            organization,     # nep-organization header value
        ]
        signable_content = '\n'.join(p for p in params if p)
        
        logger.debug(
            "NCR HMAC signing",
            nonce=nonce,
            signing_key_prefix=signing_key[:20] + "...",
            signable_content=signable_content,
        )
        
        # Generate HMAC-SHA512 signature
        signature = hmac.new(
            signing_key.encode('utf-8'),
            signable_content.encode('utf-8'),
            hashlib.sha512
        ).digest()
        
        # Base64 encode the signature
        return base64.b64encode(signature).decode('utf-8')
    
    def _get_request_headers(self, method: str, url: str, body: bytes = b"") -> Dict[str, str]:
        """
        Get headers for a request, including HMAC signature.
        
        Args:
            method: HTTP method (PUT, GET, POST, etc.)
            url: Full URL for the request
            body: Request body as bytes (for Content-MD5 calculation)
            
        Returns:
            Dictionary of headers including Authorization with HMAC signature
        """
        headers = self.base_headers.copy()
        
        # Get current date (rounded to nearest second for consistency with JavaScript implementation)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        
        # Add Date header (GMT string format, e.g., "Mon, 12 Jan 2026 12:00:00 GMT")
        date_str = now.strftime('%a, %d %b %Y %H:%M:%S GMT')
        headers["Date"] = date_str
        
        # Calculate Content-MD5 of body
        content_md5 = ""
        if body:
            md5_hash = hashlib.md5(body).digest()
            content_md5 = base64.b64encode(md5_hash).decode('utf-8')
            headers["Content-MD5"] = content_md5
        
        # Parse URI from URL (full path including query string)
        # This matches the JavaScript implementation: url.replace(/^https?:\/\/[^/]+\//, '/')
        # Example: https://api.ncr.com/catalog/items/123 -> /catalog/items/123
        parsed = urlparse(url)
        uri = parsed.path
        if parsed.query:
            uri += "?" + parsed.query
        
        # Generate Authorization header with HMAC signature
        if self.shared_key and self.secret_key:
            signature = self._generate_signature(
                method=method,
                uri=uri,
                content_type="application/json",
                content_md5=content_md5,
                organization=self.organization or "",
                date=now,
            )
            headers["Authorization"] = f"AccessKey {self.shared_key}:{signature}"
        elif self.shared_key:
            headers["Authorization"] = f"AccessKey {self.shared_key}"
        
        return headers

    async def create_product(
        self,
        item_code: str,
        title: str,
        department_id: str,
        category_id: str,
        price: Optional[float] = None,
        sku: Optional[str] = None,
        barcode: Optional[str] = None,
        status: str = "ACTIVE",
    ) -> Dict[str, Any]:
        """
        Create a single product in NCR via PUT /items/{itemCode} endpoint.
        
        This method:
        1. Validates that item_code, barcode, or sku is provided
        2. Creates the product data structure with NCR-required fields
        3. Sends PUT request to NCR API to create/update the product
        4. Optionally creates a price if price is provided

        Args:
            item_code: Unique item code (alphanumeric, max 100 chars)
            title: Product title/description
            department_id: Department identifier
            category_id: Merchandise category node ID
            price: Optional price (if provided, will also create price)
            sku: Optional SKU
            barcode: Optional barcode (can be used as item_code or in packageIdentifiers)
            status: Item status (ACTIVE, INACTIVE, etc.)

        Returns:
            API response dictionary with status and item_code

        Raises:
            ValueError: If item_code, barcode, and sku are all missing
            Exception: If NCR API returns an error
        """
        from app.integrations.ncr.models import (
            ItemIdData,
            MultiLanguageTextData,
            NodeIdData,
        )

        # Step 1: Determine item_code - use barcode or sku as fallback
        # NCR requires an item_code, so we use the first available identifier
        if not item_code and barcode:
            item_code = barcode
        elif not item_code and sku:
            item_code = sku

        # Validate that we have at least one identifier
        if not item_code:
            raise ValueError("item_code, barcode, or sku must be provided")

        # Step 2: Create item data structure with required NCR fields
        # NCR requires: departmentId, merchandiseCategory, shortDescription, status
        item_data = ItemWriteData(
            itemId=ItemIdData(itemCode=item_code),
            departmentId=department_id,
            merchandiseCategory=NodeIdData(nodeId=category_id),
            nonMerchandise=False,
            shortDescription=MultiLanguageTextData.from_single_text(title),
            status=status,
            sku=sku,
        )

        # Step 3: Add barcode to package identifiers if provided and different from item_code
        # This allows products to be identified by barcode while using a different item_code
        if barcode and barcode != item_code:
            item_data.packageIdentifiers = [
                {"type": "UPC", "value": barcode}
            ]

        # Step 4: Prepare request payload and URL
        # Note: NCR API uses PUT for create/update operations (idempotent)
        # The endpoint is PUT /items/{itemCode} and accepts ItemData (not wrapped in array)
        # ItemId is excluded from payload since it's in the URL path
        payload = item_data.model_dump(exclude_none=True, by_alias=True, exclude={"itemId"})
        url = f"{self.base_url}/items/{item_code}"
        
        # Step 5: Serialize body and generate HMAC-signed headers
        # NCR requires Content-MD5 header and HMAC signature for authentication
        body = json.dumps(payload).encode('utf-8')
        headers = self._get_request_headers("PUT", url, body)
        
        logger.info("NCR create product request", url=url, payload=payload, headers={k: v for k, v in headers.items() if k != "Authorization"})
        
        # Step 6: Send PUT request to NCR API
        response = await self.client.put(
            url,
            content=body,  # Use content= instead of json= since we already serialized
            headers=headers,
        )
        
        # Step 7: Handle errors
        if response.status_code >= 400:
            error_body = response.text
            logger.error("NCR API error", status=response.status_code, body=error_body)
            raise Exception(f"NCR API error {response.status_code}: {error_body}")
        
        response.raise_for_status()

        logger.info(
            "NCR product created",
            item_code=item_code,
            title=title,
        )

        # Step 8: If price provided and enterprise_unit exists, create price record
        # Prices are created separately via the item-prices endpoint
        if price is not None and self.enterprise_unit:
            try:
                await self.update_price(
                    item_code=item_code,
                    price=price,
                    price_code="REGULAR",  # Default price code
                )
            except Exception as e:
                # Log warning but don't fail product creation if price creation fails
                logger.warning(
                    "Failed to create price after product creation",
                    item_code=item_code,
                    error=str(e),
                )

        return {"status": "success", "item_code": item_code}

    async def update_price(
        self,
        item_code: str,
        price: float,
        price_code: str = "REGULAR",
        currency: str = "USD",
        effective_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update product price in NCR via PUT /item-prices endpoint.
        
        This method:
        1. Validates that enterprise_unit is configured (required for prices)
        2. Creates price data structure with effective date, currency, and status
        3. Sends PUT request to NCR API to update/create the price

        Args:
            item_code: Item code of the product
            price: New price value (float)
            price_code: Price code identifier (default: "REGULAR")
            currency: Currency code (default: "USD")
            effective_date: Effective date in ISO format (default: now)

        Returns:
            API response dictionary with status, item_code, and price

        Raises:
            ValueError: If enterprise_unit is not configured
            Exception: If NCR API returns an error
        """
        # Validate enterprise_unit is required for price updates
        # Prices are store-specific (enterprise unit specific) in NCR
        if not self.enterprise_unit:
            raise ValueError("enterprise_unit is required for price updates")

        from app.integrations.ncr.models import ItemPriceIdData

        # Step 1: Generate effective date if not provided
        # NCR API requires ISO 8601 format with timezone indicator (Z for UTC)
        # Format: 2026-01-14T16:19:48.061Z (milliseconds precision)
        if effective_date is None:
            now = datetime.now(timezone.utc)
            # Format with milliseconds (remove last 3 digits of microseconds) and add Z
            effective_date = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        # Step 2: Determine actual price code
        # Note: For base prices, priceCode typically matches itemCode (NCR demo pattern)
        # If price_code is "REGULAR", use item_code as the price code (common pattern)
        actual_price_code = item_code if price_code == "REGULAR" else price_code
        
        # Step 3: Create price data structure with required NCR fields
        # NCR requires: priceId (itemCode, priceCode, enterpriseUnitId), price, currency, effectiveDate, status
        price_data = ItemPriceWriteData(
            priceId=ItemPriceIdData(
                itemCode=item_code,
                priceCode=actual_price_code,
                enterpriseUnitId=self.enterprise_unit,
            ),
            price=price,
            currency=currency,
            effectiveDate=effective_date,
            promotionPriceType="NON_CARD_PRICE",
            status="ACTIVE",
            basePrice=True,  # Required for base prices
            endDate="2100-12-31T23:59:59Z",  # Set far future end date (effectively no end)
        )

        # Step 4: Wrap in request model (NCR API accepts batch of prices)
        request = SaveMultipleItemPricesRequest(itemPrices=[price_data])

        url = f"{self.base_url}/item-prices"
        
        # Step 5: Serialize body and generate HMAC-signed headers
        payload = request.model_dump(exclude_none=True, by_alias=True)
        body = json.dumps(payload).encode('utf-8')
        headers = self._get_request_headers("PUT", url, body)
        
        logger.info("NCR update price request", url=url, payload=payload, headers={k: v for k, v in headers.items() if k != "Authorization"})
        
        # Step 6: Send PUT request to NCR API
        response = await self.client.put(
            url,
            content=body,
            headers=headers,
        )
        
        # Step 7: Handle errors
        if response.status_code >= 400:
            error_body = response.text
            logger.error("NCR API error", status=response.status_code, body=error_body, url=url, payload=payload)
            raise Exception(f"NCR API error {response.status_code}: {error_body}")
        
        response.raise_for_status()

        logger.info(
            "NCR price updated",
            item_code=item_code,
            price=price,
            price_code=price_code,
        )

        return {"status": "success", "item_code": item_code, "price": price}

    async def delete_product(
        self,
        item_code: str,
        department_id: str,
        category_id: str,
    ) -> Dict[str, Any]:
        """
        Delete a product by setting its status to INACTIVE.
        
        Note: NCR API doesn't have a physical DELETE endpoint. Instead, products
        are "deleted" by updating their status to INACTIVE via PUT /items/{itemCode}.
        This preserves the product data but hides it from active product listings.
        
        This method:
        1. Creates a minimal update payload with INACTIVE status
        2. Sends PUT request to NCR API to update the product status

        Args:
            item_code: Item code of the product to delete
            department_id: Department ID (required for NCR API update)
            category_id: Category ID (required for NCR API update)

        Returns:
            API response dictionary with status, item_code, and deleted flag

        Raises:
            Exception: If NCR API returns an error

        Note:
            This is a minimal update that only sets status to INACTIVE. In production,
            you might want to fetch the existing item first to preserve other fields
            when updating to INACTIVE status.
        """
        from app.integrations.ncr.models import (
            ItemIdData,
            MultiLanguageTextData,
            NodeIdData,
        )

        # Step 1: Create minimal item data structure with INACTIVE status
        # Note: We're doing a minimal update - in production, you might want to
        # fetch the existing item first to preserve other fields when setting status
        # Required fields: departmentId, merchandiseCategory, shortDescription, status
        # Use a placeholder description instead of empty string to avoid validation errors
        item_data = ItemWriteData(
            itemId=ItemIdData(itemCode=item_code),
            departmentId=department_id,
            merchandiseCategory=NodeIdData(nodeId=category_id),
            nonMerchandise=False,
            shortDescription=MultiLanguageTextData.from_single_text("Product deleted"),  # Required field (use placeholder instead of empty)
            status="INACTIVE",  # Set to INACTIVE to "delete" the product
        )
        # Explicitly exclude longDescription to avoid sending empty values
        # NCR validation requires longDescription values to be 1-1024 chars if present

        # Step 2: Prepare request payload and URL
        # Note: NCR API uses PUT for updates (idempotent)
        # The endpoint is PUT /items/{itemCode} and accepts ItemData (not wrapped in array)
        # ItemId is excluded from payload since it's in the URL path
        payload = item_data.model_dump(exclude_none=True, by_alias=True, exclude={"itemId"})
        url = f"{self.base_url}/items/{item_code}"
        
        # Step 3: Serialize body and generate HMAC-signed headers
        body = json.dumps(payload).encode('utf-8')
        headers = self._get_request_headers("PUT", url, body)

        # Step 4: Send PUT request to NCR API
        response = await self.client.put(
            url,
            content=body,
            headers=headers,
        )
        
        # Step 5: Handle errors
        if response.status_code >= 400:
            error_body = response.text
            logger.error("NCR API error", status=response.status_code, body=error_body)
            raise Exception(f"NCR API error {response.status_code}: {error_body}")
        
        response.raise_for_status()

        logger.info(
            "NCR product deleted (status set to INACTIVE)",
            item_code=item_code,
        )

        return {"status": "success", "item_code": item_code, "deleted": True}

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

