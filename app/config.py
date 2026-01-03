"""
Configuration management using Pydantic settings.
Loads environment variables for ZKong API, Supabase, and Shopify webhook secrets.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # ZKong API Configuration
    zkong_api_base_url: str = (
        "https://esl-eu.zkong.com"  # ZKong ESL API base URL (EU region)
    )
    zkong_username: str = ""  # Optional for testing, required for ZKong sync
    zkong_password: str = ""  # Optional for testing, required for ZKong sync
    zkong_rsa_public_key: str = ""  # Optional for testing, required for ZKong sync
    zkong_agency_id: int = (
        0  # Agent ID (required for product import, default 0 if not used)
    )

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
    zkong_rate_limit_per_second: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
