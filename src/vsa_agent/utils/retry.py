"""Retry decorator for async functions. Mirrors NVIDIA utils/retry.py."""

import asyncio
import functools
import logging

logger = logging.getLogger(__name__)


def async_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,)):
    """Decorator: retry async function on exception with exponential backoff.

    Args:
        max_retries: Maximum retry attempts (default 3).
        delay: Initial delay in seconds (default 1.0).
        backoff: Multiplier for each subsequent retry (default 2.0).
        exceptions: Tuple of exception types to catch (default all).
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = delay * (backoff ** attempt)
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1, max_retries, func.__name__, wait, e,
                        )
                        await asyncio.sleep(wait)
            raise last_exc
        return wrapper
    return decorator