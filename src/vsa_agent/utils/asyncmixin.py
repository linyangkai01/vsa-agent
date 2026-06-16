"""AsyncMixin base class for async resource management.

Provides lifecycle hooks for async initialization and cleanup.
Mirrors NVIDIA AsyncMixin pattern.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AsyncMixin:
    """Mixin for classes that need async initialization and cleanup.

    Usage:
        class MyClass(AsyncMixin):
            async def async_init(self):
                # Initialize async resources
                pass

            async def async_close(self):
                # Clean up async resources
                pass

        obj = await MyClass.create()
        # ... use obj ...
        await obj.close()
    """

    _async_initialized: bool = False

    async def async_init(self) -> None:
        """Initialize async resources. Override in subclass."""
        self._async_initialized = True

    async def async_close(self) -> None:
        """Clean up async resources. Override in subclass."""
        self._async_initialized = False

    @classmethod
    async def create(cls, *args: Any, **kwargs: Any) -> "AsyncMixin":
        """Factory method: create and async-initialize an instance.

        Args:
            *args: Positional arguments for __init__.
            **kwargs: Keyword arguments for __init__.

        Returns:
            Initialized instance.
        """
        instance = cls(*args, **kwargs)
        await instance.async_init()
        return instance

    async def __aenter__(self) -> "AsyncMixin":
        if not self._async_initialized:
            await self.async_init()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.async_close()
