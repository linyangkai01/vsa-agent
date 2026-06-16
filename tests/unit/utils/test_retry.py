"""Tests for utils/retry.py."""
import pytest
from vsa_agent.utils.retry import async_retry

class TestAsyncRetry:
    async def test_success_no_retry(self):
        call_count = 0
        @async_retry(max_retries=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"
        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retry_on_failure(self):
        call_count = 0
        @async_retry(max_retries=3)
        async def eventually_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Temporary error")
            return "ok"
        result = await eventually_succeed()
        assert result == "ok"
        assert call_count == 2

    async def test_exhaust_retries(self):
        call_count = 0
        @async_retry(max_retries=2)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Persistent error")
        with pytest.raises(ValueError):
            await always_fail()
        assert call_count == 3

    async def test_specific_exceptions(self):
        @async_retry(max_retries=2, exceptions=(ValueError,))
        async def fail_with_type_error():
            raise TypeError("Wrong exception type")
        with pytest.raises(TypeError):
            await fail_with_type_error()
