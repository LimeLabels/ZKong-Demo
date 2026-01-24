# Square OAuth Token Refresh Implementation Guide

## Overview

Square access tokens expire after 30 days. This guide documents how to implement automatic token refresh to ensure uninterrupted API access.

## Context

- **Token Expiration**: Square access tokens expire after 30 days
- **Storage Location**: Tokens are stored in `store_mappings.metadata`:
  - `square_access_token`: Current access token
  - `square_refresh_token`: Token used to obtain new access tokens
  - `square_expires_at`: ISO timestamp when the access token expires
- **Refresh Threshold**: Refresh tokens when less than 7 days remain before expiration
- **Implementation Location**: `app/integrations/square/`

## Architecture

The implementation consists of three components:

1. **Token Refresh Service** (`token_refresh.py`): Core logic for refreshing tokens
2. **Scheduled Job** (`token_refresh_scheduler.py`): Daily check and refresh of expiring tokens
3. **Adapter Middleware** (`adapter.py`): Auto-refresh before API calls

---

## 1. Token Refresh Service

**File**: `app/integrations/square/token_refresh.py`

### Purpose
Handles the core token refresh logic:
- Checks if token is expiring soon (<7 days)
- Calls Square's `/oauth2/token` endpoint with `grant_type=refresh_token`
- Updates `store_mappings.metadata` with new tokens
- Logs refresh success/failure

### Implementation

```python
"""
Square OAuth token refresh service.
Handles automatic refresh of expiring access tokens.
"""

import httpx
import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from uuid import UUID

from app.config import settings
from app.services.supabase_service import SupabaseService
from app.models.database import StoreMapping

logger = structlog.get_logger()


class SquareTokenRefreshService:
    """Service for refreshing Square OAuth tokens."""

    def __init__(self):
        """Initialize token refresh service."""
        self.supabase_service = SupabaseService()
        self.refresh_threshold_days = 7  # Refresh if less than 7 days remaining

    def is_token_expiring_soon(
        self, expires_at: Optional[str], threshold_days: int = None
    ) -> bool:
        """
        Check if token is expiring within the threshold period.

        Args:
            expires_at: ISO timestamp string of token expiration
            threshold_days: Days before expiration to trigger refresh (default: 7)

        Returns:
            True if token expires within threshold, False otherwise
        """
        if not expires_at:
            # If no expiration date, assume expired (should refresh)
            logger.warning("No expiration date found for token, assuming expired")
            return True

        threshold = threshold_days or self.refresh_threshold_days

        try:
            # Parse ISO timestamp
            expires_datetime = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = datetime.utcnow()

            # Calculate days until expiration
            days_until_expiry = (expires_datetime - now).days

            is_expiring = days_until_expiry < threshold
            logger.debug(
                "Token expiration check",
                expires_at=expires_at,
                days_until_expiry=days_until_expiry,
                threshold_days=threshold,
                is_expiring=is_expiring,
            )

            return is_expiring
        except Exception as e:
            logger.error(
                "Error parsing expiration date, assuming expired",
                expires_at=expires_at,
                error=str(e),
            )
            return True  # Assume expired if we can't parse

    async def refresh_token(
        self, store_mapping: StoreMapping
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Refresh Square OAuth token for a store mapping.

        Args:
            store_mapping: Store mapping with Square tokens in metadata

        Returns:
            Tuple of (success: bool, new_token_data: Optional[Dict])
            new_token_data contains: access_token, refresh_token, expires_at
        """
        if not store_mapping.metadata:
            logger.warning(
                "Store mapping has no metadata",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None

        refresh_token = store_mapping.metadata.get("square_refresh_token")
        if not refresh_token:
            logger.error(
                "No refresh token found in store mapping",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )
            return False, None

        square_application_id = settings.square_application_id
        square_application_secret = settings.square_application_secret

        if not square_application_id or not square_application_secret:
            logger.error("Square application credentials not configured")
            return False, None

        # Determine Square API base URL
        if settings.square_environment == "sandbox":
            base_url = "https://connect.squareupsandbox.com"
        else:
            base_url = "https://connect.squareup.com"

        token_url = f"{base_url}/oauth2/token"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    json={
                        "client_id": square_application_id,
                        "client_secret": square_application_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.error(
                        "Square token refresh failed",
                        status_code=response.status_code,
                        response_text=response.text,
                        store_mapping_id=str(store_mapping.id),
                        merchant_id=store_mapping.source_store_id,
                    )
                    return False, None

                token_data = response.json()

                access_token = token_data.get("access_token")
                new_refresh_token = token_data.get("refresh_token")
                expires_at = token_data.get("expires_at")

                if not access_token:
                    logger.error(
                        "No access token in refresh response",
                        store_mapping_id=str(store_mapping.id),
                    )
                    return False, None

                # Return new token data
                new_token_data = {
                    "access_token": access_token,
                    "refresh_token": new_refresh_token or refresh_token,  # Use new if provided, else keep old
                    "expires_at": expires_at,
                }

                logger.info(
                    "Square token refreshed successfully",
                    store_mapping_id=str(store_mapping.id),
                    merchant_id=store_mapping.source_store_id,
                    expires_at=expires_at,
                )

                return True, new_token_data

        except httpx.TimeoutException:
            logger.error(
                "Timeout refreshing Square token",
                store_mapping_id=str(store_mapping.id),
            )
            return False, None
        except Exception as e:
            logger.error(
                "Error refreshing Square token",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, None

    async def refresh_token_and_update(
        self, store_mapping: StoreMapping
    ) -> Tuple[bool, Optional[StoreMapping]]:
        """
        Refresh token and update store mapping metadata.

        Args:
            store_mapping: Store mapping to refresh token for

        Returns:
            Tuple of (success: bool, updated_store_mapping: Optional[StoreMapping])
        """
        success, new_token_data = await self.refresh_token(store_mapping)

        if not success or not new_token_data:
            return False, None

        # Update store mapping metadata
        try:
            updated_metadata = store_mapping.metadata.copy()
            updated_metadata.update(
                {
                    "square_access_token": new_token_data["access_token"],
                    "square_refresh_token": new_token_data["refresh_token"],
                    "square_expires_at": new_token_data["expires_at"],
                    "square_token_refreshed_at": datetime.utcnow().isoformat(),
                }
            )

            # Update in database
            self.supabase_service.client.table("store_mappings").update(
                {"metadata": updated_metadata}
            ).eq("id", str(store_mapping.id)).execute()

            # Return updated store mapping
            updated_mapping = self.supabase_service.get_store_mapping_by_id(
                store_mapping.id
            )

            logger.info(
                "Store mapping updated with new token",
                store_mapping_id=str(store_mapping.id),
                merchant_id=store_mapping.source_store_id,
            )

            return True, updated_mapping

        except Exception as e:
            logger.error(
                "Failed to update store mapping with new token",
                store_mapping_id=str(store_mapping.id),
                error=str(e),
            )
            return False, None

    def get_access_token(
        self, store_mapping: StoreMapping, auto_refresh: bool = True
    ) -> Optional[str]:
        """
        Get access token from store mapping, optionally refreshing if expiring.

        Args:
            store_mapping: Store mapping with tokens
            auto_refresh: If True, refresh token if expiring soon

        Returns:
            Access token string or None if not available
        """
        if not store_mapping.metadata:
            return None

        access_token = store_mapping.metadata.get("square_access_token")
        expires_at = store_mapping.metadata.get("square_expires_at")

        if not access_token:
            return None

        # Check if token is expiring soon
        if auto_refresh and self.is_token_expiring_soon(expires_at):
            logger.info(
                "Token is expiring soon, should refresh",
                store_mapping_id=str(store_mapping.id),
                expires_at=expires_at,
            )
            # Note: This is synchronous check - actual refresh should be async
            # For synchronous access, return token but log warning
            logger.warning(
                "Token expiring soon but refresh is async - token may expire",
                store_mapping_id=str(store_mapping.id),
            )

        return access_token
```

### Key Features

- **Expiration Check**: `is_token_expiring_soon()` checks if token expires within threshold (default 7 days)
- **Token Refresh**: `refresh_token()` calls Square's `/oauth2/token` endpoint
- **Database Update**: `refresh_token_and_update()` updates `store_mappings.metadata`
- **Error Handling**: Comprehensive error handling and logging

---

## 2. Scheduled Token Refresh Job

**File**: `app/workers/token_refresh_scheduler.py`

### Purpose
Runs daily to check all Square store mappings and refresh tokens that are expiring soon.

### Implementation

```python
"""
Scheduled job for refreshing Square OAuth tokens.
Runs daily to check and refresh expiring tokens.
"""

import asyncio
import structlog
from datetime import datetime, timedelta
from typing import List

from app.services.supabase_service import SupabaseService
from app.integrations.square.token_refresh import SquareTokenRefreshService
from app.models.database import StoreMapping

logger = structlog.get_logger()


class SquareTokenRefreshScheduler:
    """
    Scheduler that checks Square store mappings daily and refreshes expiring tokens.
    """

    def __init__(self):
        """Initialize token refresh scheduler."""
        self.supabase_service = SupabaseService()
        self.token_refresh_service = SquareTokenRefreshService()
        self.running = False
        self.check_interval_hours = 24  # Check once per day

    async def start(self):
        """Start the token refresh scheduler loop."""
        self.running = True
        logger.info("Square token refresh scheduler started")

        while self.running:
            try:
                await self.check_and_refresh_tokens()
            except Exception as e:
                logger.error(
                    "Error in token refresh scheduler loop", error=str(e)
                )

            # Wait before next check (24 hours)
            await asyncio.sleep(self.check_interval_hours * 3600)

    async def stop(self):
        """Stop the token refresh scheduler."""
        self.running = False
        logger.info("Square token refresh scheduler stopped")

    async def check_and_refresh_tokens(self):
        """
        Check all Square store mappings and refresh expiring tokens.
        """
        try:
            # Get all active Square store mappings
            store_mappings = self._get_square_store_mappings()

            if not store_mappings:
                logger.debug("No Square store mappings found")
                return

            logger.info(
                "Checking Square tokens for refresh",
                store_mapping_count=len(store_mappings),
            )

            refreshed_count = 0
            failed_count = 0
            skipped_count = 0

            for store_mapping in store_mappings:
                try:
                    # Check if token needs refresh
                    if self._should_refresh_token(store_mapping):
                        logger.info(
                            "Refreshing Square token",
                            store_mapping_id=str(store_mapping.id),
                            merchant_id=store_mapping.source_store_id,
                        )

                        success, updated_mapping = (
                            await self.token_refresh_service.refresh_token_and_update(
                                store_mapping
                            )
                        )

                        if success:
                            refreshed_count += 1
                            logger.info(
                                "Token refreshed successfully",
                                store_mapping_id=str(store_mapping.id),
                            )
                        else:
                            failed_count += 1
                            logger.error(
                                "Failed to refresh token",
                                store_mapping_id=str(store_mapping.id),
                            )
                    else:
                        skipped_count += 1
                        logger.debug(
                            "Token does not need refresh",
                            store_mapping_id=str(store_mapping.id),
                        )

                except Exception as e:
                    failed_count += 1
                    logger.error(
                        "Error processing store mapping",
                        store_mapping_id=str(store_mapping.id),
                        error=str(e),
                    )

            logger.info(
                "Token refresh check completed",
                total=len(store_mappings),
                refreshed=refreshed_count,
                failed=failed_count,
                skipped=skipped_count,
            )

        except Exception as e:
            logger.error("Error checking tokens for refresh", error=str(e))
            raise

    def _get_square_store_mappings(self) -> List[StoreMapping]:
        """
        Get all active Square store mappings.

        Returns:
            List of Square store mappings
        """
        try:
            # Query Supabase for Square store mappings
            response = (
                self.supabase_service.client.table("store_mappings")
                .select("*")
                .eq("source_system", "square")
                .eq("is_active", True)
                .execute()
            )

            store_mappings = []
            for row in response.data:
                try:
                    store_mapping = StoreMapping(**row)
                    # Only include mappings that have Square tokens
                    if (
                        store_mapping.metadata
                        and store_mapping.metadata.get("square_access_token")
                    ):
                        store_mappings.append(store_mapping)
                except Exception as e:
                    logger.warning(
                        "Failed to parse store mapping",
                        row_id=row.get("id"),
                        error=str(e),
                    )

            return store_mappings

        except Exception as e:
            logger.error("Failed to fetch Square store mappings", error=str(e))
            return []

    def _should_refresh_token(self, store_mapping: StoreMapping) -> bool:
        """
        Check if token should be refreshed.

        Args:
            store_mapping: Store mapping to check

        Returns:
            True if token should be refreshed
        """
        if not store_mapping.metadata:
            return False

        expires_at = store_mapping.metadata.get("square_expires_at")
        return self.token_refresh_service.is_token_expiring_soon(expires_at)


async def run_token_refresh_scheduler():
    """
    Main entry point for running the token refresh scheduler.
    Creates a SquareTokenRefreshScheduler instance and starts it.
    """
    scheduler = SquareTokenRefreshScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        logger.info(
            "Received interrupt signal, shutting down token refresh scheduler"
        )
    finally:
        await scheduler.stop()
```

### Integration with Workers

Update `app/workers/__main__.py` to include the token refresh scheduler:

```python
"""
Entry point for running workers as a module.
Runs sync worker, price scheduler, and token refresh scheduler concurrently.
Usage: python -m app.workers
"""

import asyncio
from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker
from app.workers.price_scheduler import run_price_scheduler
from app.workers.token_refresh_scheduler import run_token_refresh_scheduler


async def run_all_workers():
    """Run all workers concurrently."""
    await asyncio.gather(
        run_worker(),
        run_price_scheduler(),
        run_token_refresh_scheduler(),
    )


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_all_workers())
```

### Key Features

- **Daily Check**: Runs once per 24 hours
- **Batch Processing**: Checks all Square store mappings in one run
- **Selective Refresh**: Only refreshes tokens expiring within 7 days
- **Error Resilience**: Continues processing even if one mapping fails

---

## 3. Adapter Middleware for Auto-Refresh

**File**: `app/integrations/square/adapter.py` (modifications)

### Purpose
Add automatic token refresh check before API calls to ensure tokens are valid.

### Implementation

Add the following methods to `SquareIntegrationAdapter`:

```python
async def _ensure_valid_token(
    self, store_mapping: StoreMapping
) -> Optional[str]:
    """
    Ensure store mapping has a valid, non-expiring access token.
    Refreshes token if expiring soon.

    Args:
        store_mapping: Store mapping to check/refresh token for

    Returns:
        Valid access token or None if refresh failed
    """
    from app.integrations.square.token_refresh import SquareTokenRefreshService

    token_refresh_service = SquareTokenRefreshService()

    # Check if token is expiring soon
    expires_at = None
    if store_mapping.metadata:
        expires_at = store_mapping.metadata.get("square_expires_at")

    if token_refresh_service.is_token_expiring_soon(expires_at):
        logger.info(
            "Token expiring soon, refreshing before API call",
            store_mapping_id=str(store_mapping.id),
            merchant_id=store_mapping.source_store_id,
        )

        # Refresh token
        success, updated_mapping = (
            await token_refresh_service.refresh_token_and_update(store_mapping)
        )

        if success and updated_mapping:
            # Use updated mapping
            store_mapping = updated_mapping
            logger.info(
                "Token refreshed successfully before API call",
                store_mapping_id=str(store_mapping.id),
            )
        else:
            logger.error(
                "Failed to refresh token before API call",
                store_mapping_id=str(store_mapping.id),
            )
            return None

    # Get access token from (possibly updated) store mapping
    if store_mapping.metadata:
        return store_mapping.metadata.get("square_access_token")

    return None
```

### Update Existing Methods

Modify methods in `SquareIntegrationAdapter` that use access tokens to call `_ensure_valid_token()` first:

**Example: Update `_handle_catalog_update` method:**

```python
async def _handle_catalog_update(
    self, headers: Dict[str, str], payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Handle catalog update with pagination, safe token retrieval, 
    deletion detection, and automatic token refresh.
    """
    # ... existing validation code ...

    merchant_id = self.extract_store_id(headers, payload)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Merchant ID missing",
        )

    # 1. Get store mapping
    store_mapping = self.supabase_service.get_store_mapping("square", merchant_id)
    if not store_mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store mapping not found",
        )

    # 2. Ensure valid token (auto-refresh if needed)
    access_token = await self._ensure_valid_token(store_mapping)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to obtain valid access token",
        )

    # 3. Continue with existing logic using access_token
    # ... rest of the method ...
```

**Example: Update `sync_all_products_from_square` method:**

```python
async def sync_all_products_from_square(
    self,
    merchant_id: str,
    access_token: str,  # Keep for backward compatibility
    store_mapping_id: UUID,
    base_url: str,
) -> Dict[str, Any]:
    """
    Fetch all products from Square Catalog API and sync to database.
    
    This function is called during initial onboarding to sync all existing
    products from Square to the database and queue them for Hipoink sync.
    
    Args:
        merchant_id: Square merchant ID
        access_token: Square OAuth access token (optional if store_mapping_id provided)
        store_mapping_id: Store mapping UUID
        base_url: Square API base URL (sandbox or production)
    
    Returns:
        Dict with sync statistics (total_items, products_created, products_updated, errors)
    """
    # If access_token not provided, get from store mapping
    if not access_token and store_mapping_id:
        store_mapping = self.supabase_service.get_store_mapping_by_id(store_mapping_id)
        if store_mapping:
            # Ensure valid token
            access_token = await self._ensure_valid_token(store_mapping)
            if not access_token:
                raise Exception("Failed to obtain valid access token")

    # ... rest of existing method ...
```

### Key Features

- **Pre-API Refresh**: Checks and refreshes tokens before API calls
- **Transparent**: Existing code continues to work, tokens are refreshed automatically
- **Error Handling**: Returns None if refresh fails, allowing calling code to handle

---

## 4. Testing

### Manual Testing

1. **Test Token Refresh Service**:
   ```python
   from app.integrations.square.token_refresh import SquareTokenRefreshService
   from app.services.supabase_service import SupabaseService
   
   service = SquareTokenRefreshService()
   supabase = SupabaseService()
   
   # Get a Square store mapping
   store_mapping = supabase.get_store_mapping("square", "YOUR_MERCHANT_ID")
   
   # Check if token is expiring
   expires_at = store_mapping.metadata.get("square_expires_at")
   is_expiring = service.is_token_expiring_soon(expires_at)
   print(f"Token expiring soon: {is_expiring}")
   
   # Refresh token
   success, new_data = await service.refresh_token(store_mapping)
   print(f"Refresh success: {success}")
   ```

2. **Test Scheduler**:
   ```python
   from app.workers.token_refresh_scheduler import SquareTokenRefreshScheduler
   
   scheduler = SquareTokenRefreshScheduler()
   await scheduler.check_and_refresh_tokens()
   ```

3. **Test Adapter Middleware**:
   - Make an API call that uses Square adapter
   - Verify token is refreshed if expiring soon
   - Check logs for refresh messages

### Integration Testing

1. **Set Token to Expire Soon**:
   - Manually update `square_expires_at` in database to a date <7 days away
   - Run scheduler or make API call
   - Verify token is refreshed

2. **Test Expired Token**:
   - Set `square_expires_at` to past date
   - Verify refresh is triggered

3. **Test Multiple Store Mappings**:
   - Create multiple Square store mappings
   - Verify scheduler processes all of them

---

## 5. Configuration

### Environment Variables

No new environment variables required. Uses existing:
- `SQUARE_APPLICATION_ID`
- `SQUARE_APPLICATION_SECRET`
- `SQUARE_ENVIRONMENT` (sandbox/production)

### Configurable Parameters

In `SquareTokenRefreshService`:
- `refresh_threshold_days`: Default 7 days (configurable)

In `SquareTokenRefreshScheduler`:
- `check_interval_hours`: Default 24 hours (configurable)

---

## 6. Monitoring and Logging

### Log Messages

The implementation logs:
- **Info**: Token refresh success, scheduler runs, token checks
- **Warning**: Token expiring soon, no expiration date found
- **Error**: Refresh failures, API errors, database errors

### Key Metrics to Monitor

1. **Token Refresh Success Rate**: Count of successful vs failed refreshes
2. **Scheduler Execution**: Daily run completion
3. **Token Expiration Warnings**: Tokens expiring within threshold
4. **API Call Failures**: 401 errors indicating token issues

### Example Log Queries

```python
# Find all token refresh attempts
logger.info("Square token refreshed successfully", ...)

# Find refresh failures
logger.error("Failed to refresh token", ...)

# Find scheduler runs
logger.info("Token refresh check completed", ...)
```

---

## 7. Error Handling

### Refresh Token Failures

If refresh fails:
1. Log error with store_mapping_id and merchant_id
2. Continue processing other store mappings
3. Token will be retried on next scheduler run
4. API calls will fail with 401, triggering manual intervention

### Database Update Failures

If database update fails after successful refresh:
1. Log error
2. Return failure (token refreshed but not saved)
3. Next scheduler run will attempt refresh again

### Network Failures

If Square API is unreachable:
1. Log timeout/connection error
2. Return failure
3. Retry on next scheduler run

---

## 8. Deployment

### Step 1: Create Token Refresh Service

Create `app/integrations/square/token_refresh.py` with the code from Section 1.

### Step 2: Create Scheduler

Create `app/workers/token_refresh_scheduler.py` with the code from Section 2.

### Step 3: Update Workers Entry Point

Update `app/workers/__main__.py` to include token refresh scheduler (see Section 2).

### Step 4: Update Adapter

Add `_ensure_valid_token()` method to `SquareIntegrationAdapter` and update methods that use tokens (see Section 3).

### Step 5: Test

Run manual tests (Section 4) to verify implementation.

### Step 6: Deploy

Deploy updated code. The scheduler will start automatically with other workers.

---

## 9. Reference: Square OAuth Token Refresh API

### Endpoint
```
POST https://connect.squareup.com/oauth2/token
POST https://connect.squareupsandbox.com/oauth2/token (sandbox)
```

### Request Body
```json
{
  "client_id": "YOUR_APPLICATION_ID",
  "client_secret": "YOUR_APPLICATION_SECRET",
  "grant_type": "refresh_token",
  "refresh_token": "REFRESH_TOKEN_FROM_METADATA"
}
```

### Response
```json
{
  "access_token": "NEW_ACCESS_TOKEN",
  "token_type": "bearer",
  "expires_at": "2024-01-15T12:00:00Z",
  "merchant_id": "MERCHANT_ID",
  "refresh_token": "NEW_REFRESH_TOKEN"  // May be same as old one
}
```

### Documentation
- [Square OAuth Refresh Token Documentation](https://developer.squareup.com/docs/oauth-api/refresh-token)

---

## 10. Troubleshooting

### Issue: Tokens Not Refreshing

**Symptoms**: Tokens expire and API calls fail with 401.

**Solutions**:
1. Check scheduler is running: `ps aux | grep token_refresh_scheduler`
2. Check logs for refresh attempts
3. Verify `square_refresh_token` exists in metadata
4. Verify Square application credentials are correct

### Issue: Scheduler Not Running

**Symptoms**: No refresh logs appear.

**Solutions**:
1. Verify scheduler is included in `app/workers/__main__.py`
2. Check worker process is running
3. Verify no exceptions in scheduler startup

### Issue: Refresh Fails with 400/401

**Symptoms**: Refresh API returns error.

**Solutions**:
1. Verify refresh token is valid (not revoked)
2. Check Square application credentials
3. Verify environment (sandbox vs production) matches
4. Check Square API status

---

## Summary

This implementation provides:

1. ✅ **Automatic Token Refresh**: Tokens refresh when <7 days remain
2. ✅ **Daily Scheduled Check**: Scheduler runs every 24 hours
3. ✅ **Pre-API Refresh**: Tokens refresh before API calls if needed
4. ✅ **Comprehensive Logging**: All operations are logged
5. ✅ **Error Resilience**: Failures don't crash the system
6. ✅ **Database Updates**: New tokens are saved to `store_mappings.metadata`

The system ensures Square API access remains uninterrupted by automatically refreshing tokens before expiration.
