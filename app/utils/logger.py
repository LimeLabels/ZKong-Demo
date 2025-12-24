"""
Structured logging configuration using structlog.
"""
import structlog
import logging
import sys
from app.config import settings


def configure_logging():
    """
    Configure structured logging for the application.
    Sets up JSON formatting for production, console formatting for development.
    """
    # Convert log level string to logging constant
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]
    
    if settings.app_environment == "production":
        # JSON formatting for production
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Console formatting for development
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

