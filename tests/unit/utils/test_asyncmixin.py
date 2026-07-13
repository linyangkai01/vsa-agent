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


class TestAsyncMixinCompat:
    @pytest.mark.asyncio
    async def test_create_calls_dunder_async_init_when_present(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self.ready = False

            async def __async_init__(self):
                self.ready = True

        obj = await MyResource.create()
        assert obj.ready is True

    @pytest.mark.asyncio
    async def test_aexit_uses_close_when_present(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        obj = MyResource()
        await obj.__aexit__(None, None, None)
        assert obj.closed is True
