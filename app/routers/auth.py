"""
FastAPI router for authentication and user management.
Handles Supabase Auth token verification and user-store associations.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Header
from typing import Optional
from uuid import UUID
from datetime import datetime
import structlog
from app.services.supabase_service import SupabaseService
from pydantic import BaseModel
from supabase import create_client, Client
from app.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/api/auth", tags=["auth"])
supabase_service = SupabaseService()


def get_supabase_auth_client() -> Client:
    """
    Create a Supabase client for auth operations.
    Uses the anon key for client-side auth verification.
    """
    # For auth verification, we need the anon key, not the service key
    # The service key should be in settings, but we'll use it for now
    # In production, you might want to add supabase_anon_key to settings
    return create_client(settings.supabase_url, settings.supabase_service_key)


async def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    Verify Supabase JWT token from Authorization header.
    
    Args:
        authorization: Authorization header value (Bearer <token>)
        
    Returns:
        User data from token
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # Extract token from "Bearer <token>"
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        token = parts[1]
        
        # Verify token with Supabase
        # Use Supabase REST API to verify the JWT token
        supabase_auth = get_supabase_auth_client()
        
        try:
            # Use the Supabase client's auth API to get user from token
            # The supabase-py library's get_user() method can verify tokens
            # by making a request to Supabase's auth API
            import httpx
            
            # Make a request to Supabase's user endpoint to verify the token
            auth_url = f"{settings.supabase_url}/auth/v1/user"
            headers = {
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_service_key,
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(auth_url, headers=headers, timeout=10.0)
                
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                
                user_data = response.json()
                
                if not user_data or not user_data.get("id"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid token payload",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                
                return {
                    "user_id": user_data["id"],
                    "email": user_data.get("email"),
                    "user": user_data,
                }
        except HTTPException:
            raise
        except httpx.HTTPError as http_error:
            logger.error("HTTP error during token verification", error=str(http_error))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as token_error:
            logger.error("Token verification error", error=str(token_error))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ConnectStoreRequest(BaseModel):
    """Request model for connecting user to store mapping."""
    store_mapping_id: UUID


@router.post("/connect-store")
async def connect_store(
    request: ConnectStoreRequest,
    user_data: dict = Depends(verify_token),
):
    """
    Connect authenticated user to a store mapping.
    Associates the user with the store mapping in the database.
    """
    user_id = user_data["user_id"]
    store_mapping_id = request.store_mapping_id
    
    try:
        # Get the store mapping
        store_mapping = supabase_service.get_store_mapping_by_id(store_mapping_id)
        if not store_mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store mapping not found: {store_mapping_id}",
            )
        
        # Update store mapping to associate with user
        # We'll add user_id to metadata or create a separate association
        # For now, we'll add it to metadata
        metadata = store_mapping.metadata or {}
        metadata["user_id"] = user_id
        metadata["connected_at"] = datetime.utcnow().isoformat()
        
        result = (
            supabase_service.client.table("store_mappings")
            .update({"metadata": metadata})
            .eq("id", str(store_mapping_id))
            .execute()
        )
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to connect store",
            )
        
        logger.info(
            "User connected to store",
            user_id=user_id,
            store_mapping_id=str(store_mapping_id),
        )
        
        return {
            "success": True,
            "message": "Store connected successfully",
            "store_mapping_id": str(store_mapping_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to connect store", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect store: {str(e)}",
        )


@router.get("/me")
async def get_current_user(user_data: dict = Depends(verify_token)):
    """
    Get current authenticated user information.
    """
    return {
        "user_id": user_data["user_id"],
        "email": user_data["email"],
    }


@router.get("/my-store")
async def get_my_store(user_data: dict = Depends(verify_token)):
    """
    Get the store mapping associated with the current user.
    """
    user_id = user_data["user_id"]
    
    try:
        # Find store mapping where metadata contains user_id
        result = (
            supabase_service.client.table("store_mappings")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        
        # Filter in Python since Supabase JSON queries can be tricky
        user_store = None
        for item in result.data:
            mapping = supabase_service.get_store_mapping_by_id(UUID(item["id"]))
            if (
                mapping
                and mapping.metadata
                and mapping.metadata.get("user_id") == user_id
            ):
                user_store = mapping
                break
        
        if not user_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No store mapping found for this user. Please complete onboarding.",
            )
        
        return {
            "id": str(user_store.id),
            "source_system": user_store.source_system,
            "source_store_id": user_store.source_store_id,
            "hipoink_store_code": user_store.hipoink_store_code or "",
            "is_active": user_store.is_active,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user store", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user store: {str(e)}",
        )


class FindStoreMappingRequest(BaseModel):
    """Request model for finding a store mapping by POS system and Hipoink code."""
    source_system: str
    hipoink_store_code: str


@router.post("/find-store-mapping")
async def find_store_mapping(
    request: FindStoreMappingRequest,
    user_data: dict = Depends(verify_token),
):
    """
    Find an existing store mapping by POS system and Hipoink store code.
    This is used during onboarding to connect users to existing mappings.
    Does NOT create new mappings - only finds existing ones (1:1 relationship).
    """
    try:
        # Find existing mapping by source system and Hipoink store code
        mapping = supabase_service.get_store_mapping_by_hipoink_code(
            source_system=request.source_system,
            hipoink_store_code=request.hipoink_store_code.strip(),
        )
        
        if not mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No store mapping found for {request.source_system} with Hipoink store code '{request.hipoink_store_code}'. "
                       f"Store mappings must be created separately before users can connect to them.",
            )
        
        # Check if this mapping is already connected to another user
        if mapping.metadata and mapping.metadata.get("user_id"):
            existing_user_id = mapping.metadata.get("user_id")
            if existing_user_id != user_data["user_id"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"This store mapping is already connected to another user.",
                )
        
        return {
            "id": str(mapping.id),
            "source_system": mapping.source_system,
            "source_store_id": mapping.source_store_id,
            "hipoink_store_code": mapping.hipoink_store_code or "",
            "is_active": mapping.is_active,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to find store mapping", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to find store mapping: {str(e)}",
        )

