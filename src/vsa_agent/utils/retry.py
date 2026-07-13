"""Shared async retry utilities."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


async def call_with_async_retry(
    func: Callable[..., Awaitable[Any]],
    *args,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    non_retry_exceptions: tuple[type[Exception], ...] = (),
    **kwargs,
) -> Any:
    """Call an async function with exponential-backoff retry."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except non_retry_exceptions:
            raise
        except exceptions as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = delay * (backoff**attempt)
                logger.warning(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    getattr(func, "__name__", repr(func)),
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
    if last_exc is None:
        raise RuntimeError("Retry loop exited without result or captured exception")
    raise last_exc


def async_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,)):
    """Decorator: retry async function on exception with exponential backoff."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await call_with_async_retry(
                func,
                *args,
                max_retries=max_retries,
                delay=delay,
                backoff=backoff,
                exceptions=exceptions,
                **kwargs,
            )

        return wrapper

    return decorator
