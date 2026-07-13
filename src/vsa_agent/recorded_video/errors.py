"""Recorded-video error types and retry classifications."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    CORRUPT_MEDIA = "CORRUPT_MEDIA"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    CONFIGURATION = "CONFIGURATION"
    EMBEDDING_DIMENSION = "EMBEDDING_DIMENSION"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_5XX = "MODEL_5XX"
    ES_TIMEOUT = "ES_TIMEOUT"
    ES_5XX = "ES_5XX"


PERMANENT_ERROR_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.CORRUPT_MEDIA,
        ErrorCode.UNSUPPORTED_MEDIA,
        ErrorCode.FFMPEG_MISSING,
        ErrorCode.CONFIGURATION,
        ErrorCode.EMBEDDING_DIMENSION,
    }
)

RETRYABLE_ERROR_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.MODEL_RATE_LIMIT,
        ErrorCode.MODEL_TIMEOUT,
        ErrorCode.MODEL_5XX,
        ErrorCode.ES_TIMEOUT,
        ErrorCode.ES_5XX,
    }
)


class RecordedVideoError(Exception):
    def __init__(self, code: ErrorCode | str, retryable: bool, message: str | None = None) -> None:
        self.code = ErrorCode(code)
        expected_retryable = self.code in RETRYABLE_ERROR_CODES
        if retryable is not expected_retryable:
            raise ValueError(f"retryable={retryable} conflicts with classification for {self.code.value}")
        self.retryable = expected_retryable
        super().__init__(message or self.code.value)


class InvalidStateTransition(Exception):  # noqa: N818 - public name is part of the domain contract
    def __init__(self, source: Any, target: Any) -> None:
        self.source = source
        self.target = target
        source_value = getattr(source, "value", source)
        target_value = getattr(target, "value", target)
        super().__init__(f"invalid job state transition: {source_value} -> {target_value}")
