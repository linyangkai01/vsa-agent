"""Time conversion utilities for video analysis."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

DURATION_PATTERN = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$",
    re.IGNORECASE,
)


def parse_iso8601_duration(duration_str: str) -> float:
    """Parse an ISO 8601 duration string to seconds."""
    match = DURATION_PATTERN.fullmatch(duration_str.strip())
    if not match:
        raise ValueError(f"Invalid ISO 8601 duration: {duration_str}")

    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0.0)
    if hours == 0 and minutes == 0 and seconds == 0:
        raise ValueError(f"Invalid ISO 8601 duration: {duration_str}")

    return hours * 3600 + minutes * 60 + seconds


def iso8601_to_datetime(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware datetime."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("ISO 8601 timestamp must not be empty")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        return result.replace(tzinfo=UTC)
    return result


def datetime_to_iso8601(value: datetime) -> str:
    """Serialize datetime to ISO 8601, preferring ``Z`` for UTC."""
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def format_timestamp(seconds: float, fmt: str = "hh:mm:ss") -> str:
    """Format seconds into a readable timestamp."""
    seconds = max(0.0, float(seconds))
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if fmt == "hh:mm:ss":
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    if fmt == "mm:ss.ms":
        total_milliseconds = int(round(seconds * 1000))
        total_whole_seconds, ms = divmod(total_milliseconds, 1000)
        total_minutes, secs = divmod(total_whole_seconds, 60)
        return f"{total_minutes:02d}:{secs:02d}.{ms:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def frames_to_seconds(frame_index: int, fps: float) -> float:
    """Convert frame index to timestamp in seconds."""
    if fps <= 0:
        return 0.0
    return max(0, frame_index) / fps


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to the corresponding zero-based frame index."""
    if fps <= 0:
        return 0
    return int(max(0.0, seconds) * fps)
