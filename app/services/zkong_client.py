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
            login_data = {
                "username": self.username,
                "password": encrypted_password
            }
            
            response = await self.client.post("/api/v1/login", json=login_data)
            response.raise_for_status()
            
            data = response.json()
            if data.get("code") != 200:
                raise ZKongAuthenticationError(
                    f"Authentication failed: {data.get('message')}"
                )
            
            # Extract token from response
            token_data = data.get("data", {})
            token = token_data.get("token") or token_data.get("access_token")
            
            if not token:
                raise ZKongAuthenticationError("Token not found in authentication response")
            
            # Cache token (check expiration if provided)
            self._auth_token = token
            expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
            import time
            self._token_expires_at = time.time() + expires_in
            
            logger.info("Successfully authenticated with ZKong API")
            return token
            
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
            # Prepare request payload
            request_data = {
                "products": [
                    {
                        "barcode": p.barcode,
                        "merchant_id": merchant_id,
                        "store_id": store_id,
                        "product_name": p.product_name,
                        "price": p.price,
                        "currency": p.currency,
                        **({k: v for k, v in p.dict().items() if v is not None and k not in [
                            "barcode", "merchant_id", "store_id", "product_name", "price", "currency"
                        ]})
                    }
                    for p in products
                ]
            }
            
            headers = {
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json"
            }
            
            response = await self.client.post(
                "/api/v1/products/import",
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

