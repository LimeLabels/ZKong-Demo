"""
Configuration management using Pydantic settings.
Loads environment variables for Hipoink ESL API, Supabase, Shopify, and Square.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Hipoink ESL API Configuration
    hipoink_api_base_url: str = "http://43.153.107.21"  # Hipoink ESL server URL
    hipoink_username: str = ""  # Hipoink admin username
    hipoink_password: str = ""  # Hipoink admin password
    hipoink_api_secret: str = ""  # API secret for signing requests (optional)
    hipoink_client_id: str = "default"  # Client ID for API endpoint

    # Supabase Configuration
    supabase_url: str = ""  # Required for production, optional for NCR testing
    supabase_service_key: str = ""  # Required for production, optional for NCR testing

    # Shopify Configuration
    shopify_webhook_secret: str = (
        ""  # Required for webhook verification in production
    )
    shopify_api_key: str = ""  # Shopify app API key (for OAuth)
    shopify_api_secret: str = ""  # Shopify app API secret (for OAuth)
    app_base_url: str = (
        "http://localhost:8000"  # Base URL for OAuth redirects (backend)
    )
    frontend_url: str = (
        "http://localhost:3000"  # Frontend app URL (must match App URL in Shopify)
    )

    # NCR POS Configuration
    ncr_pos_base_url: str = (
        "https://ncr-pos-local-production.up.railway.app"  # NCR POS deployment URL (Railway)
    )
    ncr_api_base_url: str = "https://api.ncr.com/catalog"  # NCR API base URL (production)
    ncr_shared_key: str = "42ca1d8c9fe34aa89b283b07e7694fcd"  # NCR shared key (bsp-shared-key)
    ncr_secret_key: str = "fc12af86bb4d4aa1a01e6178373f9b21"  # NCR secret key (bsp-secret-key)
    ncr_organization: str = "test-drive-db9be7e5183a4ed183c99"  # NCR organization ID (bsp-organization)
    ncr_enterprise_unit: str = "4e469b13321f41bc9f2d45078de86beb"  # NCR enterprise unit ID (bsp-site-id)
    ncr_department_id: str = "DEFAULT"  # Default department ID
    ncr_category_id: str = "DEFAULT"  # Default category ID
    # Square Configuration
    square_webhook_secret: str = ""  # Webhook signature key from Square
    square_application_id: str = ""  # Square Application ID
    square_application_secret: str = ""  # Square Application Secret
    square_environment: str = "production"  # "sandbox" or "production"

    # Application Configuration
    app_environment: str = "development"
    log_level: str = "INFO"

    # Worker Configuration
    sync_worker_interval_seconds: int = 5  # Poll interval for sync queue
    max_retry_attempts: int = 3
    retry_backoff_multiplier: float = 2.0
    retry_initial_delay_seconds: float = 1.0

    # Rate Limiting
    hipoink_rate_limit_per_second: int = 10

    # Slack Configuration
    slack_webhook_url: str = ""  # Slack Incoming Webhook URL
    slack_alerts_enabled: str = "false"  # Enable/disable Slack alerts ("true" or "false")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables (like NEXT_PUBLIC_* for frontend, deprecated NCR_ACCESS_TOKEN)


# Global settings instance
settings = Settings()
