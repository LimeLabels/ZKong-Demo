"""
Shopify API client for making direct API calls to Shopify.
Handles product variant price updates.
"""

import httpx
import structlog
from typing import Dict, Any, List

logger = structlog.get_logger()


class ShopifyAPIClient:
    """Client for making Shopify Admin API calls."""

    def __init__(self, shop_domain: str, access_token: str):
        """
        Initialize Shopify API client.

        Args:
            shop_domain: Shopify shop domain (e.g., 'myshop.myshopify.com')
            access_token: Shopify Admin API access token
        """
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.base_url = f"https://{shop_domain}/admin/api/2024-01"
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            },
        )

    async def update_variant_price(
        self, product_id: str, variant_id: str, price: str
    ) -> Dict[str, Any]:
        """
        Update a product variant's price in Shopify.

        Args:
            product_id: Shopify product ID
            variant_id: Shopify variant ID
            price: New price as string (e.g., "10.99")

        Returns:
            API response dictionary

        Raises:
            Exception: If API call fails
        """
        try:
            # Get current product data
            product_url = f"{self.base_url}/products/{product_id}.json"
            product_response = await self.client.get(product_url)
            product_response.raise_for_status()
            product_data = product_response.json()

            # Find the variant and update its price
            product = product_data.get("product", {})
            variants = product.get("variants", [])

            variant_found = False
            for variant in variants:
                if str(variant.get("id")) == str(variant_id):
                    variant["price"] = price
                    variant_found = True
                    break

            if not variant_found:
                raise Exception(
                    f"Variant {variant_id} not found in product {product_id}"
                )

            # Update the product with modified variant
            update_url = f"{self.base_url}/products/{product_id}.json"
            update_payload = {"product": product}

            update_response = await self.client.put(update_url, json=update_payload)
            update_response.raise_for_status()

            result = update_response.json()
            logger.info(
                "Updated Shopify variant price",
                product_id=product_id,
                variant_id=variant_id,
                price=price,
            )

            return result

        except httpx.HTTPStatusError as e:
            error_msg = f"Shopify API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            logger.error(
                "Failed to update Shopify variant price",
                product_id=product_id,
                variant_id=variant_id,
                error=error_msg,
            )
            raise Exception(error_msg) from e
        except Exception as e:
            logger.error(
                "Failed to update Shopify variant price",
                product_id=product_id,
                variant_id=variant_id,
                error=str(e),
            )
            raise

    async def update_multiple_variant_prices(
        self, updates: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Update multiple variant prices efficiently.
        Uses Shopify's bulk operations API if available, otherwise makes individual calls.

        Args:
            updates: List of dicts with keys: product_id, variant_id, price

        Returns:
            Dictionary with results
        """
        results = {"succeeded": [], "failed": []}

        for update in updates:
            try:
                result = await self.update_variant_price(
                    product_id=update["product_id"],
                    variant_id=update["variant_id"],
                    price=update["price"],
                )
                results["succeeded"].append(
                    {
                        "product_id": update["product_id"],
                        "variant_id": update["variant_id"],
                        "result": result,
                    }
                )
            except Exception as e:
                results["failed"].append(
                    {
                        "product_id": update["product_id"],
                        "variant_id": update["variant_id"],
                        "error": str(e),
                    }
                )

        return results

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
