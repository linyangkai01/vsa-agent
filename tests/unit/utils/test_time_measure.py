"""Tests for utils/time_measure.py."""

import asyncio

import pytest

from vsa_agent.utils.time_measure import TimeMeasureResult, async_measure_time, measure_time


def test_measure_time_returns_elapsed_result():
    with measure_time("sync-block") as result:
        pass

    assert isinstance(result, TimeMeasureResult)
    assert result.label == "sync-block"
    assert result.elapsed_sec >= 0.0


@pytest.mark.asyncio
async def test_async_measure_time_returns_elapsed_result():
    async with async_measure_time("async-block") as result:
        await asyncio.sleep(0)

    assert isinstance(result, TimeMeasureResult)
    assert result.label == "async-block"
    assert result.elapsed_sec >= 0.0


def test_measure_time_logs_when_logger_provided():
    records = []

    class DummyLogger:
        def info(self, message, *args):
            records.append(message % args)

    with measure_time("logged-block", logger=DummyLogger()):
        pass

    assert any("logged-block" in line for line in records)
