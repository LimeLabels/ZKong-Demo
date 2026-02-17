"""
Hipoink ESL API client for product synchronization.
Integrates with Hipoink ESL system running at http://208.167.248.129/

API Documentation (Version V1.0.0):
- Create/Edit Product: POST /api/{i_client_id}/product/create
- Create Multiple Products: POST /api/{i_client_id}/product/create_multiple
  - Uses 'f1' parameter (not 'fs') for product array
  - Default sign: "80805d794841f1b4"
  - Default client_id: "default"
"""

from typing import Any

import httpx
import structlog

from app.config import settings
from app.services.slack_service import get_slack_service
from app.utils.retry import PermanentError, TransientError, retry_with_backoff

logger = structlog.get_logger()


class HipoinkAPIError(Exception):
    """Base exception for Hipoink API errors."""

    pass


class HipoinkAuthenticationError(HipoinkAPIError):
    """Raised when Hipoink authentication fails."""

    pass


class HipoinkProductItem:
    """Model for Hipoink product item."""

    def __init__(
        self,
        product_code: str,  # pc - required
        product_name: str,  # pn - required
        product_price: str,  # pp - required (as string)
        product_inner_code: str | None = None,  # pi
        product_spec: str | None = None,  # ps
        product_grade: str | None = None,  # pg
        product_unit: str | None = None,  # pu
        vip_price: str | None = None,  # vp
        origin_price: str | None = None,  # pop
        product_origin: str | None = None,  # po
        product_manufacturer: str | None = None,  # pm
        promotion: int | None = None,  # promotion
        product_image_url: str | None = None,  # pim
        product_qrcode_url: str | None = None,  # pqr
        **kwargs,  # For f1-f16 and other fields
    ):
        self.pc = product_code
        self.pn = product_name
        self.pp = product_price
        self.pi = product_inner_code
        self.ps = product_spec
        self.pg = product_grade
        self.pu = product_unit
        self.vp = vip_price
        self.pop = origin_price
        self.po = product_origin
        self.pm = product_manufacturer
        self.promotion = promotion
        self.pim = product_image_url
        self.pqr = product_qrcode_url

        # Add f1-f16 fields if providedd
        for i in range(1, 17):
            field_name = f"f{i}"
            if field_name in kwargs:
                setattr(self, field_name, kwargs[field_name])

        # Add extend field if provided
        if "extend" in kwargs:
            self.extend = kwargs["extend"]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {
            "pc": self.pc,
            "pn": self.pn,
            "pp": self.pp,
        }

        # Add optional fields if they exist
        optional_fields = [
            "pi",
            "ps",
            "pg",
            "pu",
            "vp",
            "pop",
            "po",
            "pm",
            "promotion",
            "pim",
            "pqr",
            "extend",
        ]
        for field in optional_fields:
            value = getattr(self, field, None)
            if value is not None:
                result[field] = value

        # Add f1-f16 fields
        for i in range(1, 17):
            field_name = f"f{i}"
            value = getattr(self, field_name, None)
            if value is not None:
                result[field_name] = value

        return result


class HipoinkClient:
    """Client for interacting with Hipoink ESL API."""

    def __init__(self, base_url: str = None, client_id: str = "default", api_secret: str = None):
        """
        Initialize Hipoink API client.

        Args:
            base_url: Hipoink server base URL (defaults to settings)
            client_id: Client ID for API endpoint (defaults to "default")
            api_secret: API secret for signing requests (optional)
        """
        self.base_url = (
            base_url or getattr(settings, "hipoink_api_base_url", "http://208.167.248.129")
        ).rstrip("/")
        self.client_id = client_id
        self.api_secret = api_secret or getattr(settings, "hipoink_api_secret", "")
        self.username = getattr(settings, "hipoink_username", "")
        self.password = getattr(settings, "hipoink_password", "")

        # HTTP client with timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            follow_redirects=True,
        )

    def _generate_sign(self, data: dict[str, Any]) -> str:
        """
        Generate sign for API request.
        Based on Hipoink API documentation, sign is required.
        Default sign per API docs: "80805d794841f1b4"

        The sign should be passed directly as-is (not hashed).

        Args:
            data: Request data dictionary

        Returns:
            Sign string
        """
        # If API secret is provided, use it directly as the sign
        # (Hipoink expects the static sign value, not a computed hash)
        if self.api_secret:
            return self.api_secret

        # Default sign per API documentation
        return "80805d794841f1b4"

    @retry_with_backoff(max_attempts=3, initial_delay=1.0, multiplier=2.0)
    async def create_products_multiple(
        self, store_code: str, products: list[HipoinkProductItem], is_base64: str = "0"
    ) -> dict[str, Any]:
        """
        Create multiple products in Hipoink ESL system.
        Uses endpoint: POST /api/{i_client_id}/product/create_multiple

        According to API docs, the parameter is 'f1' (not 'fs') for the product array.

        Args:
            store_code: Store code (required)
            products: List of HipoinkProductItem objects
            is_base64: Whether images are base64 encoded (default "0")

        Returns:
            Response data from Hipoink API
        """
        try:
            # Build product list (f1 array - per API documentation)
            f1 = [product.to_dict() for product in products]

            # Build request payload
            request_data = {
                "store_code": store_code,
                "f1": f1,  # API uses 'f1' not 'fs'
                "is_base64": is_base64,
            }

            # Generate sign
            sign = self._generate_sign(request_data)
            request_data["sign"] = sign

            # API endpoint
            endpoint = f"/api/{self.client_id}/product/create_multiple"

            logger.info(
                "Creating products in Hipoink",
                product_count=len(products),
                store_code=store_code,
                endpoint=endpoint,
            )

            response = await self.client.post(endpoint, json=request_data)
            response.raise_for_status()

            response_data = response.json()

            # Check for errors
            error_code = response_data.get("error_code")
            if error_code != 0:
                error_msg = response_data.get("error_msg", "Unknown error")
                error = HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

                # Send Slack alert for Hipoink API errors
                try:
                    slack_service = get_slack_service()
                    await slack_service.send_api_error_alert(
                        error_message=f"{error_msg} (code: {error_code})",
                        api_name="hipoink",
                        store_code=store_code,
                    )
                except Exception as slack_error:
                    logger.warning("Failed to send Slack alert", error=str(slack_error))

                raise error

            logger.info(
                "Successfully created products in Hipoink",
                product_count=len(products),
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            # Send Slack alert for HTTP errors
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=f"HTTP {e.response.status_code}: {str(e)}",
                    api_name="hipoink",
                    store_code=store_code,
                    status_code=e.response.status_code,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))

            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}") from e
            raise PermanentError(f"Hipoink API error: {e.response.status_code}") from e
        except Exception as e:
            # Send Slack alert for unexpected errors
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=str(e),
                    api_name="hipoink",
                    store_code=store_code,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))

            raise HipoinkAPIError(f"Product creation failed: {str(e)}") from e

    @retry_with_backoff(max_attempts=3, initial_delay=1.0, multiplier=2.0)
    async def create_product(
        self, store_code: str, product: HipoinkProductItem, is_base64: str = "0"
    ) -> dict[str, Any]:
        """
        Create or edit a single product in Hipoink ESL system.
        Uses endpoint: POST /api/{i_client_id}/product/create

        Args:
            store_code: Store code (required)
            product: HipoinkProductItem object
            is_base64: Whether images are base64 encoded (default "0")

        Returns:
            Response data from Hipoink API
        """
        try:
            # Build request payload
            request_data = {
                "store_code": store_code,
                **product.to_dict(),
                "is_base64": is_base64,
            }

            # Generate sign
            sign = self._generate_sign(request_data)
            request_data["sign"] = sign

            # API endpoint
            endpoint = f"/api/{self.client_id}/product/create"

            # Log request payload for debugging (excluding sign for security)
            request_data_log = {k: v for k, v in request_data.items() if k != "sign"}
            logger.info(
                "Hipoink API request payload",
                endpoint=endpoint,
                store_code=store_code,
                payload=request_data_log,
                f1=request_data.get("f1"),
                f2=request_data.get("f2"),
                f3=request_data.get("f3"),
                f4=request_data.get("f4"),
                pp=request_data.get("pp"),
            )

            logger.info(
                "Creating product in Hipoink",
                product_code=product.pc,
                store_code=store_code,
                endpoint=endpoint,
            )

            response = await self.client.post(endpoint, json=request_data)
            response.raise_for_status()

            response_data = response.json()

            # Check for errors
            error_code = response_data.get("error_code")
            if error_code != 0:
                error_msg = response_data.get("error_msg", "Unknown error")
                error = HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

                # Send Slack alert for Hipoink API errors
                try:
                    slack_service = get_slack_service()
                    await slack_service.send_api_error_alert(
                        error_message=f"{error_msg} (code: {error_code})",
                        api_name="hipoink",
                        store_code=store_code,
                    )
                except Exception as slack_error:
                    logger.warning("Failed to send Slack alert", error=str(slack_error))

                raise error

            logger.info(
                "Successfully created product in Hipoink",
                product_code=product.pc,
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            # Send Slack alert for HTTP errors
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=f"HTTP {e.response.status_code}: {str(e)}",
                    api_name="hipoink",
                    store_code=store_code,
                    status_code=e.response.status_code,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))

            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}") from e
            raise PermanentError(f"Hipoink API error: {e.response.status_code}") from e
        except Exception as e:
            # Send Slack alert for unexpected errors
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=str(e),
                    api_name="hipoink",
                    store_code=store_code,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))

            raise HipoinkAPIError(f"Product creation failed: {str(e)}") from e

    @retry_with_backoff(max_attempts=3, initial_delay=1.0, multiplier=2.0)
    async def delete_products(
        self, store_code: str, product_codes: list[str], is_base64: str = "0"
    ) -> dict[str, Any]:
        """
        Delete products from Hipoink ESL system.
        Uses endpoint: POST /api/{client_id}/product/del_multiple

        When a product is deleted, any ESL tag bound to it will be unbound.

        Args:
            store_code: Store code (required)
            product_codes: List of product codes (barcodes) to delete
            is_base64: Whether codes are base64 encoded (default "0")

        Returns:
            Response data from Hipoink API with count of deleted products
        """
        try:
            # Build request payload
            # f1 is the array of product codes to delete
            request_data = {
                "store_code": store_code,
                "f1": product_codes,
                "is_base64": is_base64,
            }

            # Generate sign
            sign = self._generate_sign(request_data)
            request_data["sign"] = sign

            # API endpoint
            endpoint = f"/api/{self.client_id}/product/del_multiple"

            logger.info(
                "Deleting products from Hipoink",
                product_codes=product_codes,
                store_code=store_code,
                endpoint=endpoint,
            )

            response = await self.client.post(endpoint, json=request_data)
            response.raise_for_status()

            response_data = response.json()

            # Check for errors
            error_code = response_data.get("error_code")
            if error_code != 0:
                error_msg = response_data.get("error_msg", "Unknown error")
                raise HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

            deleted_count = response_data.get("count", 0)
            logger.info(
                "Successfully deleted products from Hipoink",
                deleted_count=deleted_count,
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}") from e
            raise PermanentError(f"Hipoink API error: {e.response.status_code}") from e
        except Exception as e:
            raise HipoinkAPIError(f"Product deletion failed: {str(e)}") from e

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
