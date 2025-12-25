"""
ZKong API client with RSA authentication and retry logic.
Implements authentication (2.1-2.2), product import (3.1), and image upload (3.3).
"""
import base64
import httpx
import structlog
from typing import Optional, Dict, Any, List
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from app.config import settings
from app.models.zkong import (
    ZKongProductImportItem,
    ZKongBulkImportRequest,
    ZKongAuthResponse,
    ZKongProductImportResponse,
    ZKongImageUploadResponse
)
from app.utils.retry import retry_with_backoff, TransientError, PermanentError

logger = structlog.get_logger()


class ZKongAPIError(Exception):
    """Base exception for ZKong API errors."""
    pass


class ZKongAuthenticationError(ZKongAPIError):
    """Raised when ZKong authentication fails."""
    pass


class ZKongClient:
    """Client for interacting with ZKong ESL API."""
    
    def __init__(self):
        """Initialize ZKong API client."""
        self.base_url = settings.zkong_api_base_url.rstrip("/")
        self.username = settings.zkong_username
        self.password = settings.zkong_password
        self.rsa_public_key = settings.zkong_rsa_public_key
        self._auth_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        
        # HTTP client with timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
            headers={"Content-Type": "application/json"}
        )
    
    def _encrypt_password(self, password: str, public_key_str: str) -> str:
        """
        Encrypt password using RSA public key.
        Based on ZKong API 3.2 Appendix II.
        
        Args:
            password: Plain text password
            public_key_str: RSA public key in PEM format
            
        Returns:
            Base64 encoded encrypted password
        """
        try:
            # Load public key
            public_key = serialization.load_pem_public_key(
                public_key_str.encode('utf-8'),
                backend=default_backend()
            )
            
            # Encrypt password
            encrypted = public_key.encrypt(
                password.encode('utf-8'),
                padding.PKCS1v15()
            )
            
            # Return base64 encoded
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            logger.error("Failed to encrypt password", error=str(e))
            raise ZKongAPIError(f"Password encryption failed: {str(e)}")
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        multiplier=2.0
    )
    async def get_public_key(self) -> str:
        """
        Get RSA public key from ZKong API (section 2.1).
        Supports both /zk/user/getErpPublicKey and /api/v1/public-key endpoints.
        
        Returns:
            RSA public key string (PEM format)
        """
        try:
            # Try the endpoint from the API docs first
            endpoints = ["/zk/user/getErpPublicKey", "/api/v1/public-key"]
            
            for endpoint in endpoints:
                try:
                    response = await self.client.get(endpoint)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Handle different response formats
                    if data.get("success") and data.get("data"):
                        # Format: {"success": true, "data": "MIGfMA0G..."}
                        base64_key = data.get("data")
                        if base64_key:
                            # Convert base64 to PEM format
                            pem_key = "-----BEGIN PUBLIC KEY-----\n"
                            pem_key += "\n".join([base64_key[i:i+64] for i in range(0, len(base64_key), 64)])
                            pem_key += "\n-----END PUBLIC KEY-----"
                            return pem_key
                    
                    if data.get("code") == 200 or data.get("code") == 10000:
                        public_key = data.get("data", {})
                        if isinstance(public_key, str):
                            # Already a string (base64), convert to PEM
                            pem_key = "-----BEGIN PUBLIC KEY-----\n"
                            pem_key += "\n".join([public_key[i:i+64] for i in range(0, len(public_key), 64)])
                            pem_key += "\n-----END PUBLIC KEY-----"
                            return pem_key
                        elif isinstance(public_key, dict):
                            public_key_str = public_key.get("public_key")
                            if public_key_str:
                                return public_key_str
                        
                    if endpoint == endpoints[-1]:  # Last endpoint
                        raise ZKongAPIError(f"Failed to get public key: {data.get('message')}")
                        
                except Exception:
                    if endpoint == endpoints[-1]:
                        raise
                    continue
            
            raise ZKongAPIError("Public key not found in response")
        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"ZKong API error: {e.response.status_code}")
            raise PermanentError(f"ZKong API error: {e.response.status_code}")
        except Exception as e:
            raise ZKongAPIError(f"Failed to get public key: {str(e)}")
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        multiplier=2.0
    )
    async def authenticate(self) -> str:
        """
        Authenticate with ZKong API using RSA-encrypted password (section 2.2).
        
        Returns:
            Authentication token
        """
        try:
            # Use provided public key or fetch it
            if self.rsa_public_key:
                public_key = self.rsa_public_key
            else:
                public_key = await self.get_public_key()
            
            # Encrypt password
            encrypted_password = self._encrypt_password(self.password, public_key)
            
            # Login request
            # Try /zk/user/login first (as shown in Postman testing), fallback to /api/v1/login
            login_data = {
                "account": self.username,  # ZKong API uses "account" field, not "username"
                "loginType": 3,  # Login type (3 seems to be for API login)
                "password": encrypted_password
            }
            
            # Try both endpoints
            endpoints = ["/zk/user/login", "/api/v1/login"]
            last_error = None
            
            for endpoint in endpoints:
                try:
                    response = await self.client.post(endpoint, json=login_data)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Check if login was successful
                    if data.get("success") is False or data.get("code") not in [200, 10000]:
                        if endpoint == endpoints[-1]:  # Last endpoint
                            raise ZKongAuthenticationError(
                                f"Authentication failed: {data.get('message')}"
                            )
                        continue  # Try next endpoint
                    
                    # Success - extract token
                    token_data = data.get("data", {})
                    if isinstance(token_data, dict):
                        token = token_data.get("token") or token_data.get("access_token")
                    else:
                        token = None
                    
                    if not token:
                        if endpoint == endpoints[-1]:
                            raise ZKongAuthenticationError("Token not found in authentication response")
                        continue
                    
                    # Cache token
                    self._auth_token = token
                    expires_in = token_data.get("expires_in", 3600) if isinstance(token_data, dict) else 3600
                    import time
                    self._token_expires_at = time.time() + expires_in
                    
                    logger.info("Successfully authenticated with ZKong API", endpoint=endpoint)
                    return token
                    
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if endpoint == endpoints[-1]:
                        raise
                    continue
                except Exception as e:
                    last_error = e
                    if endpoint == endpoints[-1]:
                        raise
                    continue
            
            # If we get here, all endpoints failed
            if last_error:
                raise last_error
            raise ZKongAuthenticationError("Authentication failed on all endpoints")
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ZKongAuthenticationError("Invalid credentials")
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"ZKong API error: {e.response.status_code}")
            raise PermanentError(f"ZKong API error: {e.response.status_code}")
        except ZKongAuthenticationError:
            raise
        except Exception as e:
            raise ZKongAPIError(f"Authentication failed: {str(e)}")
    
    async def _ensure_authenticated(self):
        """Ensure we have a valid authentication token."""
        import time
        if not self._auth_token or (
            self._token_expires_at and time.time() >= self._token_expires_at
        ):
            await self.authenticate()
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        multiplier=2.0
    )
    async def import_products_bulk(
        self,
        products: List[ZKongProductImportItem],
        merchant_id: str,
        store_id: str
    ) -> ZKongProductImportResponse:
        """
        Import products in bulk to ZKong (section 3.1).
        
        Args:
            products: List of products to import
            merchant_id: ZKong merchant ID
            store_id: ZKong store ID
            
        Returns:
            Import response from ZKong API
        """
        await self._ensure_authenticated()
        
        try:
            # Prepare request payload according to ZKong API 3.2 section 3.1
            # Required fields: storeId, merchantId, agencyId, itemList
            # Each item needs: barCode, attrCategory, attrName (required)
            # Note: agencyId might need to be provided - check if it's in store mapping
            
            # Build item list according to ZKong API spec
            # Required fields: barCode, attrCategory, attrName
            item_list = []
            for p in products:
                item = {
                    "barCode": p.barcode,  # Required: barcode (Unique product identifier)
                    "attrCategory": "default",  # Required: Template Classification (using default)
                    "attrName": "default",  # Required: Template properties (using default)
                }
                
                # Add product name/title
                if p.product_name:
                    item["itemTitle"] = p.product_name  # Product title
                    item["shortTitle"] = p.product_name  # Product Name
                
                # Add price (selling price)
                if p.price is not None:
                    item["price"] = float(p.price)
                
                # Add optional fields if provided
                if p.sku:
                    item["productSku"] = p.sku
                if p.external_id:
                    item["productCode"] = p.external_id
                if p.image_url:
                    item["qrCode"] = p.image_url  # QR code URL field
                
                item_list.append(item)
            
            # Build request payload
            request_data = {
                "storeId": int(store_id),  # Required: Integer
                "merchantId": int(merchant_id),  # Required: Integer
                "agencyId": settings.zkong_agency_id,  # Required: Integer (from config, default 0)
                "unitName": 1,  # Optional: 0=Points, 1=Yuan (default to Yuan)
                "itemList": item_list  # Required: List of items
            }
            
            headers = {
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json;charset=utf-8"
            }
            
            # ZKong API endpoint: /zk/item/batchImportItem
            response = await self.client.post(
                "/zk/item/batchImportItem",
                json=request_data,
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            return ZKongProductImportResponse(**data)
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # Token expired, re-authenticate and retry once
                self._auth_token = None
                await self._ensure_authenticated()
                raise TransientError("Token expired, will retry after re-authentication")
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"ZKong API error: {e.response.status_code}")
            raise PermanentError(f"ZKong API error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise ZKongAPIError(f"Failed to import products: {str(e)}")
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        multiplier=2.0
    )
    async def upload_product_image(
        self,
        barcode: str,
        image_url: str,
        merchant_id: str,
        store_id: str
    ) -> ZKongImageUploadResponse:
        """
        Upload product image to ZKong (section 3.3, 3.4).
        
        Args:
            barcode: Product barcode
            image_url: URL of the product image
            merchant_id: ZKong merchant ID
            store_id: ZKong store ID
            
        Returns:
            Upload response from ZKong API
        """
        await self._ensure_authenticated()
        
        try:
            # Upload image information (section 3.4)
            request_data = {
                "barcode": barcode,
                "merchant_id": merchant_id,
                "store_id": store_id,
                "image_url": image_url
            }
            
            headers = {
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json"
            }
            
            response = await self.client.post(
                "/api/v1/products/images",
                json=request_data,
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            return ZKongImageUploadResponse(**data)
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._auth_token = None
                await self._ensure_authenticated()
                raise TransientError("Token expired, will retry after re-authentication")
            if 500 <= e.response.status_code < 600:
                raise TransientError(f"ZKong API error: {e.response.status_code}")
            raise PermanentError(f"ZKong API error: {e.response.status_code}")
        except Exception as e:
            raise ZKongAPIError(f"Failed to upload product image: {str(e)}")
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

