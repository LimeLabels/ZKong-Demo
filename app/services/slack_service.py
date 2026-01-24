"""
Slack notification service for error alerts.
Sends formatted error messages to Slack via Incoming Webhooks.
"""

import httpx
import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.config import settings

logger = structlog.get_logger()


class SlackNotificationService:
    """Service for sending error notifications to Slack."""

    def __init__(self):
        """Initialize Slack notification service."""
        self.webhook_url = getattr(settings, "slack_webhook_url", None)
        enabled_raw = getattr(settings, "slack_alerts_enabled", "false")
        self.enabled = str(enabled_raw).lower() == "true"
        
        # Log initialization for debugging
        logger.info(
            "SlackNotificationService initialized",
            enabled=self.enabled,
            enabled_raw=enabled_raw,
            webhook_url_configured=bool(self.webhook_url),
            webhook_url_length=len(self.webhook_url) if self.webhook_url else 0,
        )
        
        # Rate limiting: track last alert time per error key
        # Format: {error_key: last_alert_timestamp}
        self._rate_limit_cache: Dict[str, datetime] = {}
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
        last_alert = self._rate_limit_cache.get(error_key)
        if last_alert is None:
            last_alert = datetime.min
        
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
            logger.warning("Slack alerts disabled, skipping notification", enabled=self.enabled, enabled_type=type(self.enabled).__name__)
            return False
        
        # Check if webhook URL is configured
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured, skipping notification", webhook_url_set=bool(self.webhook_url))
            return False
        
        # Check rate limiting
        error_key = self._get_error_key(error_type, merchant_id, store_code)
        if not self._should_send_alert(error_key):
            logger.info(
                "Slack alert rate limited",
                error_type=error_type,
                merchant_id=merchant_id,
                store_code=store_code,
                error_key=error_key,
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
                    "Slack error alert sent successfully",
                    error_type=error_type,
                    merchant_id=merchant_id,
                    store_code=store_code,
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
