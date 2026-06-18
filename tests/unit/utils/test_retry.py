"""Tests for utils/retry.py."""
import pytest

from vsa_agent.utils.retry import async_retry
from vsa_agent.utils.retry import call_with_async_retry

class TestAsyncRetry:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_specific_exceptions(self):
        @async_retry(max_retries=2, exceptions=(ValueError,))
        async def fail_with_type_error():
            raise TypeError("Wrong exception type")

        with pytest.raises(TypeError):
            await fail_with_type_error()


class TestCallWithAsyncRetry:
    @pytest.mark.asyncio
    async def test_retries_and_returns_value(self, monkeypatch):
        attempts = {"count": 0}
        waits = []

        async def fake_sleep(delay):
            waits.append(delay)

        async def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ValueError("temporary")
            return "ok"

        monkeypatch.setattr("vsa_agent.utils.retry.asyncio.sleep", fake_sleep)

        result = await call_with_async_retry(
            flaky,
            max_retries=2,
            delay=0.5,
            backoff=2.0,
            exceptions=(ValueError,),
        )

        assert result == "ok"
        assert attempts["count"] == 3
        assert waits == [0.5, 1.0]

    @pytest.mark.asyncio
    async def test_does_not_retry_unlisted_exception(self, monkeypatch):
        waits = []

        async def fake_sleep(delay):
            waits.append(delay)

        async def fail():
            raise TypeError("wrong type")

        monkeypatch.setattr("vsa_agent.utils.retry.asyncio.sleep", fake_sleep)

        with pytest.raises(TypeError):
            await call_with_async_retry(
                fail,
                max_retries=3,
                exceptions=(ValueError,),
            )

        assert waits == []
