"""Tests for utils/asyncmixin.py."""
import pytest
from vsa_agent.utils.asyncmixin import AsyncMixin

class TestAsyncMixin:
    def test_async_init_not_called_automatically(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self._async_initialized = False
            async def __async_init__(self):
                self._async_initialized = True
        obj = MyResource()
        assert not obj._async_initialized

    async def test_create_and_close(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self._async_initialized = False
                self._closed = False
            async def __async_init__(self):
                self._async_initialized = True
            async def close(self):
                self._closed = True
        obj = await MyResource.create()
        assert obj._async_initialized
        await obj.close()
        assert obj._closed
