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

import httpx
import structlog
import hashlib
from typing import Optional, List, Dict, Any
from app.config import settings
from app.utils.retry import retry_with_backoff, TransientError, PermanentError

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
        product_inner_code: Optional[str] = None,  # pi
        product_spec: Optional[str] = None,  # ps
        product_grade: Optional[str] = None,  # pg
        product_unit: Optional[str] = None,  # pu
        vip_price: Optional[str] = None,  # vp
        origin_price: Optional[str] = None,  # pop
        product_origin: Optional[str] = None,  # po
        product_manufacturer: Optional[str] = None,  # pm
        promotion: Optional[int] = None,  # promotion
        product_image_url: Optional[str] = None,  # pim
        product_qrcode_url: Optional[str] = None,  # pqr
        **kwargs  # For f1-f16 and other fields
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
        
        # Add f1-f16 fields if provided
        for i in range(1, 17):
            field_name = f"f{i}"
            if field_name in kwargs:
                setattr(self, field_name, kwargs[field_name])
        
        # Add extend field if provided
        if "extend" in kwargs:
            self.extend = kwargs["extend"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {
            "pc": self.pc,
            "pn": self.pn,
            "pp": self.pp,
        }
        
        # Add optional fields if they exist
        optional_fields = [
            "pi", "ps", "pg", "pu", "vp", "pop", "po", "pm", 
            "promotion", "pim", "pqr", "extend"
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
        self.base_url = (base_url or getattr(settings, 'hipoink_api_base_url', 'http://208.167.248.129')).rstrip("/")
        self.client_id = client_id
        self.api_secret = api_secret or getattr(settings, 'hipoink_api_secret', '')
        self.username = getattr(settings, 'hipoink_username', '')
        self.password = getattr(settings, 'hipoink_password', '')

        # HTTP client with timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            follow_redirects=True,
        )

    def _generate_sign(self, data: Dict[str, Any]) -> str:
        """
        Generate sign for API request.
        Based on Hipoink API documentation, sign is required.
        Default sign per API docs: "80805d794841f1b4"
        
        Args:
            data: Request data dictionary
            
        Returns:
            Sign string
        """
        # If API secret is provided, use it for signing
        if self.api_secret:
            # Common signing method: sort keys, concatenate values, hash
            sorted_keys = sorted(data.keys())
            sign_string = "".join(str(data.get(k, "")) for k in sorted_keys)
            sign_string += self.api_secret
            return hashlib.md5(sign_string.encode()).hexdigest()
        
        # Default sign per API documentation
        return "80805d794841f1b4"

    @retry_with_backoff(max_attempts=3, initial_delay=1.0, multiplier=2.0)
    async def create_products_multiple(
        self, 
        store_code: str,
        products: List[HipoinkProductItem],
        is_base64: str = "0"
    ) -> Dict[str, Any]:
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
                raise HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

            logger.info(
                "Successfully created products in Hipoink",
                product_count=len(products),
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}")
            raise PermanentError(f"Hipoink API error: {e.response.status_code}")
        except Exception as e:
            raise HipoinkAPIError(f"Product creation failed: {str(e)}")

    @retry_with_backoff(max_attempts=3, initial_delay=1.0, multiplier=2.0)
    async def create_product(
        self,
        store_code: str,
        product: HipoinkProductItem,
        is_base64: str = "0"
    ) -> Dict[str, Any]:
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
                raise HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

            logger.info(
                "Successfully created product in Hipoink",
                product_code=product.pc,
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}")
            raise PermanentError(f"Hipoink API error: {e.response.status_code}")
        except Exception as e:
            raise HipoinkAPIError(f"Product creation failed: {str(e)}")

    async def create_price_adjustment_order(
        self,
        store_code: str,
        order_number: str,
        order_name: str,
        products: List[Dict[str, Any]],  # List of {"pc": "product_code", "pp": price}
        trigger_stores: Optional[List[str]] = None,
        trigger_days: Optional[List[str]] = None,  # ['1','3','5'] = Mon, Wed, Fri
        start_time: Optional[str] = None,  # "15:00"
        end_time: Optional[str] = None,  # "16:00"
        is_base64: str = "0"
    ) -> Dict[str, Any]:
        """
        Create a product price adjustment order.
        Uses endpoint: POST /api/{i_client_id}/productadjust/create_order
        
        This allows scheduling price changes for specific days of the week and times.
        
        Args:
            store_code: Store code (required)
            order_number: Price adjustment order number (required)
            order_name: Price adjustment order name (required)
            products: List of products with pc (product code) and pp (price) (required)
            trigger_stores: Array of store codes to trigger (optional)
            trigger_days: Array of day numbers ['1','3','5'] = Mon, Wed, Fri (optional)
            start_time: Price adjustment start time in HH:MM format (optional)
            end_time: Price adjustment end time in HH:MM format (optional)
            is_base64: Whether data is base64 encoded (default "0")
            
        Returns:
            Response data from Hipoink API
        """
        try:
            # Validate products array
            if not products or not isinstance(products, list):
                raise HipoinkAPIError("Products must be a non-empty list")
            
            if len(products) == 0:
                raise HipoinkAPIError("At least one product is required")
            
            # Ensure all products have required fields and convert pp to number
            validated_products = []
            for product in products:
                if not isinstance(product, dict):
                    raise HipoinkAPIError(f"Product must be a dictionary, got {type(product)}")
                if "pc" not in product or "pp" not in product:
                    raise HipoinkAPIError("Product must have 'pc' (product code) and 'pp' (price) fields")
                # Convert pp to float (API expects number, per API docs example: {"pc": "010901", "pp": 5.68})
                pp_value = product["pp"]
                if isinstance(pp_value, str):
                    try:
                        pp_value = float(pp_value)
                    except ValueError:
                        raise HipoinkAPIError(f"Price 'pp' must be a valid number, got: {pp_value}")
                elif not isinstance(pp_value, (int, float)):
                    raise HipoinkAPIError(f"Price 'pp' must be a number or string, got: {type(pp_value)}")
                
                validated_products.append({
                    "pc": str(product["pc"]),
                    "pp": float(pp_value)  # API expects number (float) per documentation
                })

            # Build request payload
            request_data = {
                "store_code": store_code,
                "f1": order_number,  # Order number
                "f2": order_name,  # Order name
                "f7": validated_products,  # Product data array (validated)
                "is_base64": is_base64,
            }
            
            # Add optional fields
            # For array fields (f3, f4), send empty array if not provided to avoid PHP foreach() errors
            request_data["f3"] = trigger_stores if trigger_stores else []
            request_data["f4"] = trigger_days if trigger_days else []
            
            # String fields can be omitted if not provided
            if start_time:
                request_data["f5"] = start_time
            if end_time:
                request_data["f6"] = end_time
            
            # Generate sign (create copy to avoid modifying original)
            sign_data = dict(request_data)  # Shallow copy
            sign = self._generate_sign(sign_data)
            request_data["sign"] = sign

            # API endpoint
            endpoint = f"/api/{self.client_id}/productadjust/create_order"
            
                    logger.info(
                "Creating price adjustment order in Hipoink",
                order_number=order_number,
                order_name=order_name,
                product_count=len(validated_products),
                store_code=store_code,
                        endpoint=endpoint,
                products=validated_products,
            )
            
            # Log full request payload for debugging
            logger.info(
                "Price adjustment request payload",
                endpoint=endpoint,
                store_code=store_code,
                order_number=order_number,
                products_count=len(validated_products),
                products=validated_products,
                has_trigger_days=bool(trigger_days),
                has_start_time=bool(start_time),
                has_end_time=bool(end_time),
                full_payload=request_data,
            )

            response = await self.client.post(endpoint, json=request_data)
                    response.raise_for_status()
            
                    response_data = response.json()
            
            # Check for errors
            error_code = response_data.get("error_code")
            if error_code != 0:
                error_msg = response_data.get("error_msg", "Unknown error")
                raise HipoinkAPIError(f"Hipoink API error: {error_msg} (code: {error_code})")

            logger.info(
                "Successfully created price adjustment order in Hipoink",
                order_number=order_number,
                store_code=store_code,
            )

            return response_data

        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"Hipoink API error: {e.response.status_code}")
            raise PermanentError(f"Hipoink API error: {e.response.status_code}")
        except Exception as e:
            raise HipoinkAPIError(f"Price adjustment order creation failed: {str(e)}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
