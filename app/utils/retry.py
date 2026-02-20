"""
Retry utility functions with exponential backoff.
Categorizes errors as transient (retryable) or permanent (non-retryable).
"""

from collections.abc import Callable
from typing import TypeVar

import httpx
import structlog
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger()

T = TypeVar("T")


class TransientError(Exception):
    """Raised for transient/retryable errors (network issues, rate limits, 5xx)."""

    pass


class PermanentError(Exception):
    """Raised for permanent/non-retryable errors (4xx validation errors, auth failures)."""

    pass


def is_transient_error(exception: Exception) -> bool:
    """
    Determine if an exception represents a transient error that should be retried.

    Args:
        exception: The exception to check

    Returns:
        True if error is transient (retryable), False otherwise
    """
    # Network/connection errors are transient
    if isinstance(exception, httpx.ConnectError | httpx.TimeoutException | httpx.NetworkError):
        return True

    # HTTP 5xx errors are transient
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        if 500 <= status_code < 600:
            return True
        # Rate limiting (429) is transient
        if status_code == 429:
            return True

    # Timeout errors are transient
    if isinstance(exception, TimeoutError):
        return True

    # TransientError explicitly marked as retryable
    if isinstance(exception, TransientError):
        return True

    # PermanentError explicitly marked as non-retryable
    if isinstance(exception, PermanentError):
        return False

    # HTTP 4xx errors (except 429) are typically permanent
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        if 400 <= status_code < 500 and status_code != 429:
            return False

    # Default to non-retryable for unknown errors
    return False


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 60.0,
):
    """
    Decorator for retrying functions with exponential backoff.
    Only retries on transient errors.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        multiplier: Multiplier for exponential backoff
        max_delay: Maximum delay in seconds

    Returns:
        Decorated function with retry logic
    """

    def retry_decorator(func: Callable[..., T]) -> Callable[..., T]:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=multiplier, min=initial_delay, max=max_delay),
            retry=retry_if_exception_type(TransientError),
            reraise=True,
            before_sleep=_log_retry_attempt,
        )
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if is_transient_error(e):
                    # Wrap as TransientError to trigger retry
                    raise TransientError(f"Transient error: {str(e)}") from e
                else:
                    # Wrap as PermanentError to prevent retry
                    raise PermanentError(f"Permanent error: {str(e)}") from e

        return wrapper

    return retry_decorator


def _log_retry_attempt(retry_state: RetryCallState):
    """Log retry attempt before sleeping."""
    if retry_state.outcome is not None:
        exception = retry_state.outcome.exception()
        logger.warning(
            "Retrying after transient error",
            attempt=retry_state.attempt_number,
            exception=str(exception),
            wait_time=retry_state.next_action.sleep if retry_state.next_action else 0,
        )
