"""
Configuration management using Pydantic settings.
Loads environment variables for Hipoink ESL API, Supabase, and Shopify webhook secrets.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Hipoink ESL API Configuration
    hipoink_api_base_url: str = "http://208.167.248.129"  # Hipoink ESL server URL
    hipoink_username: str = ""  # Hipoink admin username
    hipoink_password: str = ""  # Hipoink admin password
    hipoink_api_secret: str = ""  # API secret for signing requests (optional)
    hipoink_client_id: str = "default"  # Client ID for API endpoint

    # Supabase Configuration
    supabase_url: str
    supabase_service_key: str

    # Shopify Configuration
    shopify_webhook_secret: str = (
        ""  # Optional for testing, required for webhook verification
    )
    shopify_api_key: str = ""  # Shopify app API key (for OAuth)
    shopify_api_secret: str = ""  # Shopify app API secret (for OAuth)
    app_base_url: str = "http://localhost:8000"  # Base URL for OAuth redirects

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
