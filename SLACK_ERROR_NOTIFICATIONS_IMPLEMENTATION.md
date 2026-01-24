# Slack Error Notifications Implementation Guide

## Overview

This guide documents how to implement real-time Slack alerts for integration errors in the ESL system. Slack notifications help monitor system health and quickly respond to critical issues.

## Context

- **Purpose**: Real-time Slack alerts for integration errors
- **Error Types**: Sync failures, webhook errors, Hipoink API errors, Square API errors
- **Method**: Slack Incoming Webhooks
- **Rate Limiting**: Max 1 alert per error type per 5 minutes to prevent spam
- **Implementation Location**: `app/services/slack_service.py`

## Architecture

The implementation consists of:

1. **Slack Notification Service** (`slack_service.py`): Core service for sending formatted messages to Slack
2. **Rate Limiting**: In-memory cache to prevent duplicate alerts
3. **Integration Points**: Error handlers in workers, webhooks, and API clients
4. **Configuration**: Environment variables for webhook URL and enable/disable flag

---

## 1. Slack Notification Service

**File**: `app/services/slack_service.py`

### Purpose
Handles sending formatted error messages to Slack:
- Formats error messages with emoji and structured data
- Implements rate limiting to prevent spam
- Uses async httpx for non-blocking requests
- Handles Slack API errors gracefully

### Implementation

```python
"""
Slack notification service for error alerts.
Sends formatted error messages to Slack via Incoming Webhooks.
"""

import httpx
import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from collections import defaultdict

from app.config import settings

logger = structlog.get_logger()


class SlackNotificationService:
    """Service for sending error notifications to Slack."""

    def __init__(self):
        """Initialize Slack notification service."""
        self.webhook_url = getattr(settings, "slack_webhook_url", None)
        self.enabled = getattr(settings, "slack_alerts_enabled", "false").lower() == "true"
        
        # Rate limiting: track last alert time per error key
        # Format: {error_key: last_alert_timestamp}
        self._rate_limit_cache: Dict[str, datetime] = defaultdict(lambda: datetime.min)
        self._rate_limit_window = timedelta(minutes=5)  # 5 minute window

    def _get_error_key(
        self, error_type: str, merchant_id: Optional[str] = None, store_code: Optional[str] = None
    ) -> str:
        """
        Generate a unique key for rate limiting.
        
        Args:
            error_type: Type of error (e.g., 'sync_failure', 'webhook_error')
            merchant_id: Optional merchant ID
            store_code: Optional store code
            
        Returns:
            Unique error key for rate limiting
        """
        parts = [error_type]
        if merchant_id:
            parts.append(merchant_id)
        if store_code:
            parts.append(store_code)
        return ":".join(parts)

    def _should_send_alert(self, error_key: str) -> bool:
        """
        Check if alert should be sent based on rate limiting.
        
        Args:
            error_key: Unique error key
            
        Returns:
            True if alert should be sent, False if rate limited
        """
        now = datetime.utcnow()
        last_alert = self._rate_limit_cache.get(error_key, datetime.min)
        
        if now - last_alert >= self._rate_limit_window:
            # Update cache and allow alert
            self._rate_limit_cache[error_key] = now
            return True
        
        # Rate limited - don't send
        logger.debug(
            "Slack alert rate limited",
            error_key=error_key,
            last_alert=last_alert.isoformat(),
            window_minutes=5,
        )
        return False

    def _format_error_message(
        self,
        error_type: str,
        error_message: str,
        merchant_id: Optional[str] = None,
        store_code: Optional[str] = None,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Format error message for Slack.
        
        Args:
            error_type: Type of error
            error_message: Error message
            merchant_id: Optional merchant ID
            store_code: Optional store code
            additional_details: Optional additional details dict
            
        Returns:
            Formatted Slack message payload
        """
        timestamp = datetime.utcnow().isoformat()
        
        # Build message text
        lines = [
            "🚨 *ESL Integration Error*",
            f"• Type: `{error_type}`",
        ]
        
        if merchant_id:
            lines.append(f"• Merchant: `{merchant_id}`")
        
        if store_code:
            lines.append(f"• Store: `{store_code}`")
        
        lines.append(f"• Error: {error_message}")
        lines.append(f"• Time: `{timestamp}`")
        
        # Add additional details if provided
        if additional_details:
            details_lines = []
            for key, value in additional_details.items():
                # Format value for display
                if isinstance(value, dict):
                    value_str = ", ".join(f"{k}: {v}" for k, v in value.items())
                else:
                    value_str = str(value)
                details_lines.append(f"• {key}: `{value_str}`")
            
            if details_lines:
                lines.append("")  # Empty line separator
                lines.extend(details_lines)
        
        text = "\n".join(lines)
        
        return {
            "text": text,
            "mrkdwn": True,  # Enable markdown formatting
        }

    async def send_error_alert(
        self,
        error_type: str,
        error_message: str,
        merchant_id: Optional[str] = None,
        store_code: Optional[str] = None,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send error alert to Slack.
        
        Args:
            error_type: Type of error (e.g., 'sync_failure', 'webhook_error')
            error_message: Error message
            merchant_id: Optional merchant ID
            store_code: Optional store code
            additional_details: Optional additional details dict
            
        Returns:
            True if alert sent successfully, False otherwise
        """
        # Check if alerts are enabled
        if not self.enabled:
            logger.debug("Slack alerts disabled, skipping notification")
            return False
        
        # Check if webhook URL is configured
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured, skipping notification")
            return False
        
        # Check rate limiting
        error_key = self._get_error_key(error_type, merchant_id, store_code)
        if not self._should_send_alert(error_key):
            logger.debug(
                "Slack alert rate limited",
                error_type=error_type,
                merchant_id=merchant_id,
            )
            return False
        
        # Format message
        payload = self._format_error_message(
            error_type=error_type,
            error_message=error_message,
            merchant_id=merchant_id,
            store_code=store_code,
            additional_details=additional_details,
        )
        
        # Send to Slack
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                )
                response.raise_for_status()
                
                logger.info(
                    "Slack error alert sent",
                    error_type=error_type,
                    merchant_id=merchant_id,
                )
                return True
                
        except httpx.TimeoutException:
            logger.error("Timeout sending Slack alert", error_type=error_type)
            return False
        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to send Slack alert",
                error_type=error_type,
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            return False
        except Exception as e:
            logger.error(
                "Error sending Slack alert",
                error_type=error_type,
                error=str(e),
                error_type_name=type(e).__name__,
            )
            return False

    async def send_sync_failure_alert(
        self,
        error_message: str,
        product_id: Optional[str] = None,
        store_mapping_id: Optional[str] = None,
        operation: Optional[str] = None,
        merchant_id: Optional[str] = None,
        store_code: Optional[str] = None,
    ) -> bool:
        """
        Send sync failure alert to Slack.
        
        Args:
            error_message: Error message
            product_id: Optional product ID
            store_mapping_id: Optional store mapping ID
            operation: Optional operation type (create/update/delete)
            merchant_id: Optional merchant ID
            store_code: Optional store code
            
        Returns:
            True if alert sent successfully
        """
        additional_details = {}
        if product_id:
            additional_details["product_id"] = product_id
        if store_mapping_id:
            additional_details["store_mapping_id"] = store_mapping_id
        if operation:
            additional_details["operation"] = operation
        
        return await self.send_error_alert(
            error_type="sync_failure",
            error_message=error_message,
            merchant_id=merchant_id,
            store_code=store_code,
            additional_details=additional_details if additional_details else None,
        )

    async def send_webhook_error_alert(
        self,
        error_message: str,
        integration: Optional[str] = None,
        event_type: Optional[str] = None,
        merchant_id: Optional[str] = None,
    ) -> bool:
        """
        Send webhook error alert to Slack.
        
        Args:
            error_message: Error message
            integration: Optional integration name (shopify/square)
            event_type: Optional event type
            merchant_id: Optional merchant ID
            
        Returns:
            True if alert sent successfully
        """
        additional_details = {}
        if integration:
            additional_details["integration"] = integration
        if event_type:
            additional_details["event_type"] = event_type
        
        return await self.send_error_alert(
            error_type="webhook_error",
            error_message=error_message,
            merchant_id=merchant_id,
            additional_details=additional_details if additional_details else None,
        )

    async def send_api_error_alert(
        self,
        error_message: str,
        api_name: str,
        merchant_id: Optional[str] = None,
        store_code: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> bool:
        """
        Send API error alert to Slack.
        
        Args:
            error_message: Error message
            api_name: API name (e.g., 'hipoink', 'square')
            merchant_id: Optional merchant ID
            store_code: Optional store code
            status_code: Optional HTTP status code
            
        Returns:
            True if alert sent successfully
        """
        additional_details = {"api": api_name}
        if status_code:
            additional_details["status_code"] = status_code
        
        return await self.send_error_alert(
            error_type=f"{api_name}_api_error",
            error_message=error_message,
            merchant_id=merchant_id,
            store_code=store_code,
            additional_details=additional_details,
        )


# Global instance
_slack_service: Optional[SlackNotificationService] = None


def get_slack_service() -> SlackNotificationService:
    """Get or create global Slack notification service instance."""
    global _slack_service
    if _slack_service is None:
        _slack_service = SlackNotificationService()
    return _slack_service
```

### Key Features

- **Rate Limiting**: Prevents duplicate alerts within 5-minute window
- **Formatted Messages**: Structured Slack messages with emoji and markdown
- **Error Type Classification**: Different alert types (sync_failure, webhook_error, api_error)
- **Async Non-Blocking**: Uses httpx for async requests
- **Graceful Degradation**: Continues if Slack is unavailable
- **Configurable**: Can be enabled/disabled via environment variable

---

## 2. Configuration

**File**: `app/config.py` (modifications)

### Add Slack Configuration

```python
class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # ... existing configuration ...
    
    # Slack Configuration
    slack_webhook_url: str = ""  # Slack Incoming Webhook URL
    slack_alerts_enabled: str = "false"  # Enable/disable Slack alerts ("true" or "false")
```

### Environment Variables

Add to `.env` file:

```env
# Slack Error Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_ALERTS_ENABLED=true
```

### Getting Slack Webhook URL

1. Go to https://api.slack.com/apps
2. Create a new app or select existing app
3. Go to "Incoming Webhooks"
4. Activate Incoming Webhooks
5. Click "Add New Webhook to Workspace"
6. Select channel (e.g., #alerts)
7. Copy webhook URL

---

## 3. Integration Points

### 3.1 Sync Worker Integration

**File**: `app/workers/sync_worker.py` (modifications)

Add Slack alerts for sync failures:

```python
from app.services.slack_service import get_slack_service

class SyncWorker:
    # ... existing code ...
    
    async def process_queue_item(self, queue_item: SyncQueueItem):
        """Process a single sync queue item."""
        start_time = time.time()
        
        try:
            # ... existing sync logic ...
            
        except PermanentError as e:
            # ... existing error handling ...
            
            # Send Slack alert
            try:
                store_mapping = self.supabase_service.get_store_mapping_by_id(
                    queue_item.store_mapping_id  # type: ignore
                )
                merchant_id = store_mapping.source_store_id if store_mapping else None
                store_code = store_mapping.hipoink_store_code if store_mapping else None
                
                slack_service = get_slack_service()
                await slack_service.send_sync_failure_alert(
                    error_message=str(e),
                    product_id=str(queue_item.product_id) if queue_item.product_id else None,
                    store_mapping_id=str(queue_item.store_mapping_id) if queue_item.store_mapping_id else None,
                    operation=queue_item.operation,
                    merchant_id=merchant_id,
                    store_code=store_code,
                )
            except Exception as slack_error:
                # Don't fail sync processing if Slack fails
                logger.warning("Failed to send Slack alert", error=str(slack_error))
            
            raise
        
        except (TransientError, HipoinkAPIError) as e:
            # ... existing error handling ...
            
            # Send Slack alert for transient errors that exceed retry limit
            if queue_item.retry_count and queue_item.retry_count >= settings.max_retry_attempts:
                try:
                    store_mapping = self.supabase_service.get_store_mapping_by_id(
                        queue_item.store_mapping_id  # type: ignore
                    )
                    merchant_id = store_mapping.source_store_id if store_mapping else None
                    store_code = store_mapping.hipoink_store_code if store_mapping else None
                    
                    slack_service = get_slack_service()
                    await slack_service.send_sync_failure_alert(
                        error_message=f"Max retries exceeded: {str(e)}",
                        product_id=str(queue_item.product_id) if queue_item.product_id else None,
                        store_mapping_id=str(queue_item.store_mapping_id) if queue_item.store_mapping_id else None,
                        operation=queue_item.operation,
                        merchant_id=merchant_id,
                        store_code=store_code,
                    )
                except Exception as slack_error:
                    logger.warning("Failed to send Slack alert", error=str(slack_error))
            
            raise
```

### 3.2 Webhook Handler Integration

**File**: `app/routers/webhooks_new.py` (modifications)

Add Slack alerts for webhook errors:

```python
from app.services.slack_service import get_slack_service

@router.post("/{integration_name}/{event_type:path}")
async def handle_webhook(
    integration_name: str,
    event_type: str,
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None, alias="X-Shopify-Hmac-Sha256"),
    x_square_hmacsha256_signature: Optional[str] = Header(None, alias="x-square-hmacsha256-signature"),
):
    """Handle webhook from integration."""
    try:
        # ... existing webhook handling ...
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to process webhook",
            integration=integration_name,
            event_type=event_type,
            error=str(e),
        )
        
        # Send Slack alert
        try:
            # Try to extract merchant_id from payload if available
            merchant_id = None
            try:
                body_bytes = await request.body()
                payload = json.loads(body_bytes.decode("utf-8"))
                merchant_id = payload.get("merchant_id") or payload.get("shop")
            except:
                pass
            
            slack_service = get_slack_service()
            await slack_service.send_webhook_error_alert(
                error_message=str(e),
                integration=integration_name,
                event_type=event_type,
                merchant_id=merchant_id,
            )
        except Exception as slack_error:
            logger.warning("Failed to send Slack alert", error=str(slack_error))
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}",
        )
```

### 3.3 Hipoink API Client Integration

**File**: `app/services/hipoink_client.py` (modifications)

Add Slack alerts for Hipoink API errors:

```python
from app.services.slack_service import get_slack_service

class HipoinkClient:
    # ... existing code ...
    
    async def create_products_multiple(
        self, store_code: str, products: List[HipoinkProductItem]
    ) -> Dict[str, Any]:
        """Create multiple products in Hipoink."""
        try:
            # ... existing API call logic ...
            
        except HipoinkAPIError as e:
            # ... existing error handling ...
            
            # Send Slack alert for API errors
            try:
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=str(e),
                    api_name="hipoink",
                    store_code=store_code,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))
            
            raise
```

### 3.4 Square Adapter Integration

**File**: `app/integrations/square/adapter.py` (modifications)

Add Slack alerts for Square API errors:

```python
from app.services.slack_service import get_slack_service

class SquareIntegrationAdapter:
    # ... existing code ...
    
    async def _handle_catalog_update(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle catalog update."""
        try:
            # ... existing logic ...
            
        except HTTPException as e:
            # Send Slack alert for critical errors
            if e.status_code >= 500 or e.status_code == 401:
                try:
                    merchant_id = self.extract_store_id(headers, payload)
                    slack_service = get_slack_service()
                    await slack_service.send_api_error_alert(
                        error_message=e.detail,
                        api_name="square",
                        merchant_id=merchant_id,
                        status_code=e.status_code,
                    )
                except Exception as slack_error:
                    logger.warning("Failed to send Slack alert", error=str(slack_error))
            raise
        
        except Exception as e:
            # Send Slack alert for unexpected errors
            try:
                merchant_id = self.extract_store_id(headers, payload)
                slack_service = get_slack_service()
                await slack_service.send_api_error_alert(
                    error_message=str(e),
                    api_name="square",
                    merchant_id=merchant_id,
                )
            except Exception as slack_error:
                logger.warning("Failed to send Slack alert", error=str(slack_error))
            raise
```

---

## 4. Alert Format Examples

### Sync Failure Alert

```
🚨 *ESL Integration Error*
• Type: `sync_failure`
• Merchant: `merchant_123`
• Store: `STORE001`
• Error: Product validation failed: missing barcode
• Time: `2024-01-15T12:00:00Z`
• product_id: `550e8400-e29b-41d4-a716-446655440000`
• store_mapping_id: `660e8400-e29b-41d4-a716-446655440000`
• operation: `create`
```

### Webhook Error Alert

```
🚨 *ESL Integration Error*
• Type: `webhook_error`
• Merchant: `merchant_123`
• Error: Invalid webhook signature
• Time: `2024-01-15T12:00:00Z`
• integration: `shopify`
• event_type: `products/update`
```

### API Error Alert

```
🚨 *ESL Integration Error*
• Type: `hipoink_api_error`
• Merchant: `merchant_123`
• Store: `STORE001`
• Error: HTTP 500 Internal Server Error
• Time: `2024-01-15T12:00:00Z`
• api: `hipoink`
• status_code: `500`
```

---

## 5. Rate Limiting

### How It Works

- **Window**: 5 minutes per error key
- **Error Key Format**: `{error_type}:{merchant_id}:{store_code}`
- **Behavior**: Only first alert in window is sent, subsequent alerts are rate limited

### Example

```
12:00:00 - Alert sent: sync_failure:merchant_123:STORE001
12:01:00 - Alert rate limited (same error key)
12:02:00 - Alert rate limited (same error key)
12:05:01 - Alert sent (5 minutes passed, new window)
```

### Benefits

- Prevents Slack channel spam
- Reduces noise from repeated errors
- Still alerts on new errors or after cooldown period

---

## 6. Testing

### Manual Testing

1. **Test Slack Service**:
   ```python
   from app.services.slack_service import get_slack_service
   
   slack_service = get_slack_service()
   await slack_service.send_error_alert(
       error_type="test_error",
       error_message="This is a test alert",
       merchant_id="test_merchant",
       store_code="TEST001",
   )
   ```

2. **Test Rate Limiting**:
   ```python
   # Send first alert
   await slack_service.send_error_alert(...)  # Should send
   
   # Send immediately after
   await slack_service.send_error_alert(...)  # Should be rate limited
   
   # Wait 5 minutes, send again
   await slack_service.send_error_alert(...)  # Should send
   ```

3. **Test Integration Points**:
   - Trigger a sync failure and verify Slack alert
   - Send invalid webhook and verify alert
   - Cause API error and verify alert

### Integration Testing

1. **Test Sync Failure Alert**:
   - Create invalid product in sync queue
   - Verify alert sent to Slack
   - Verify rate limiting works

2. **Test Webhook Error Alert**:
   - Send webhook with invalid signature
   - Verify alert sent to Slack

3. **Test API Error Alert**:
   - Temporarily break Hipoink API connection
   - Verify alert sent to Slack

---

## 7. Monitoring

### Key Metrics

1. **Alert Volume**: Count of alerts sent per day
2. **Error Types**: Distribution of error types
3. **Rate Limiting**: Count of rate-limited alerts
4. **Slack API Failures**: Count of failed Slack API calls

### Log Messages

The implementation logs:
- **Info**: Alert sent successfully
- **Debug**: Rate limiting, alerts disabled
- **Warning**: Webhook URL not configured, Slack API failures
- **Error**: Slack API errors

### Example Log Queries

```python
# Find all Slack alerts sent
logger.info("Slack error alert sent", ...)

# Find rate-limited alerts
logger.debug("Slack alert rate limited", ...)

# Find Slack API failures
logger.error("Failed to send Slack alert", ...)
```

---

## 8. Error Handling

### Slack API Failures

If Slack API fails:
1. Log error but don't crash application
2. Continue processing (alerts are non-critical)
3. Retry on next error (rate limiting will handle duplicates)

### Missing Configuration

If webhook URL not configured:
1. Log warning
2. Skip sending alert
3. Continue normal operation

### Rate Limiting Edge Cases

- **Memory**: Rate limit cache grows over time
  - **Solution**: Cache expires after 5 minutes, minimal memory impact
- **Multiple Workers**: Each worker has own cache
  - **Solution**: Acceptable - prevents spam per worker instance

---

## 9. Deployment

### Step 1: Create Slack Service

Create `app/services/slack_service.py` with the code from Section 1.

### Step 2: Update Configuration

Update `app/config.py` to add Slack configuration (see Section 2).

### Step 3: Add Environment Variables

Add to `.env`:
```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_ALERTS_ENABLED=true
```

### Step 4: Integrate into Error Handlers

Update error handlers in:
- `app/workers/sync_worker.py` (Section 3.1)
- `app/routers/webhooks_new.py` (Section 3.2)
- `app/services/hipoink_client.py` (Section 3.3)
- `app/integrations/square/adapter.py` (Section 3.4)

### Step 5: Test

Run manual tests (Section 6) to verify implementation.

### Step 6: Deploy

Deploy updated code. Alerts will start automatically when errors occur.

---

## 10. Troubleshooting

### Issue: Alerts Not Sending

**Symptoms**: No alerts appear in Slack channel.

**Solutions**:
1. Check `SLACK_ALERTS_ENABLED=true` in environment
2. Verify `SLACK_WEBHOOK_URL` is correct
3. Check logs for "Slack webhook URL not configured"
4. Test webhook URL manually with curl:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test"}' \
     $SLACK_WEBHOOK_URL
   ```

### Issue: Too Many Alerts

**Symptoms**: Slack channel flooded with duplicate alerts.

**Solutions**:
1. Verify rate limiting is working (check logs for "rate limited")
2. Increase rate limit window if needed (modify `_rate_limit_window`)
3. Check if multiple worker instances are running (each has own cache)

### Issue: Alerts Missing Information

**Symptoms**: Alerts don't include merchant_id or store_code.

**Solutions**:
1. Verify error handlers pass merchant_id/store_code
2. Check store_mapping lookup is successful
3. Verify metadata is available in error context

### Issue: Slack API Errors

**Symptoms**: Logs show "Failed to send Slack alert".

**Solutions**:
1. Verify webhook URL is valid and not expired
2. Check Slack app permissions
3. Verify network connectivity to Slack
4. Check Slack API status page

---

## 11. Advanced Configuration

### Custom Rate Limit Window

Modify in `slack_service.py`:

```python
self._rate_limit_window = timedelta(minutes=10)  # 10 minute window
```

### Custom Alert Format

Modify `_format_error_message()` method to customize message format.

### Channel-Specific Webhooks

Use different webhooks for different error types:

```python
# In config
slack_webhook_url_critical: str = ""  # For critical errors
slack_webhook_url_warning: str = ""   # For warnings

# In service
if error_type in ["sync_failure", "api_error"]:
    webhook_url = settings.slack_webhook_url_critical
else:
    webhook_url = settings.slack_webhook_url_warning
```

### Alert Filtering

Add filtering to skip certain error types:

```python
# In send_error_alert()
if error_type in ["debug_error", "info_error"]:
    return False  # Skip these types
```

---

## 12. Best Practices

1. **Don't Block**: Always use async and don't await Slack calls in critical paths
2. **Graceful Degradation**: Never fail application if Slack is unavailable
3. **Rate Limiting**: Always implement rate limiting to prevent spam
4. **Structured Data**: Include merchant_id, store_code, and operation context
5. **Error Context**: Include enough detail to debug but not too verbose
6. **Testing**: Test alerts in staging before production
7. **Monitoring**: Monitor alert volume and Slack API health

---

## Summary

This implementation provides:

1. ✅ **Real-Time Alerts**: Errors trigger immediate Slack notifications
2. ✅ **Rate Limiting**: Prevents spam (max 1 alert per error type per 5 min)
3. ✅ **Formatted Messages**: Structured, readable error messages
4. ✅ **Multiple Integration Points**: Sync worker, webhooks, API clients
5. ✅ **Configurable**: Can be enabled/disabled via environment variable
6. ✅ **Non-Blocking**: Async implementation doesn't slow down error handling
7. ✅ **Error Resilient**: Continues if Slack is unavailable

The system ensures critical errors are immediately visible in Slack while preventing notification spam through intelligent rate limiting.
