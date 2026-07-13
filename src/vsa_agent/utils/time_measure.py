"""Lightweight time-measurement helpers."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass


@dataclass
class TimeMeasureResult:
    label: str
    elapsed_sec: float = 0.0


@contextmanager
def measure_time(label: str, logger=None):
    """Measure elapsed time for a synchronous block."""
    result = TimeMeasureResult(label=label)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed_sec = time.perf_counter() - start
        if logger is not None:
            logger.info("%s took %.6fs", label, result.elapsed_sec)


@asynccontextmanager
async def async_measure_time(label: str, logger=None):
    """Measure elapsed time for an asynchronous block."""
    result = TimeMeasureResult(label=label)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed_sec = time.perf_counter() - start
        if logger is not None:
            logger.info("%s took %.6fs", label, result.elapsed_sec)
