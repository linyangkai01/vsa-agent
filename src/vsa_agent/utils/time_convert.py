"""Time conversion utilities for video analysis.

Handles ISO 8601 duration, timestamp formatting,
and frame-to-time conversions.
"""

from __future__ import annotations

import re
from datetime import timedelta


def parse_iso8601_duration(duration_str: str) -> float:
    """Parse ISO 8601 duration string to seconds.

    Supports formats like PT30S, PT1M30S, PT1H2M30S.

    Args:
        duration_str: ISO 8601 duration string.

    Returns:
        Duration in seconds.
    """
    pattern = r"PT?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?"
    match = re.match(pattern, duration_str.strip())
    if not match:
        raise ValueError(f"Invalid ISO 8601 duration: {duration_str}")

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = float(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(seconds: float, fmt: str = "hh:mm:ss") -> str:
    """Format seconds into a readable timestamp.

    Args:
        seconds: Time in seconds.
        fmt: Output format: "hh:mm:ss" or "mm:ss.ms".

    Returns:
        Formatted timestamp string.
    """
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if fmt == "hh:mm:ss":
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    elif fmt == "mm:ss.ms":
        ms = int((seconds - int(seconds)) * 1000)
        return f"{minutes:02d}:{secs:02d}.{ms:03d}"
    else:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def frames_to_seconds(frame_index: int, fps: float) -> float:
    """Convert frame index to timestamp in seconds.

    Args:
        frame_index: Zero-based frame index.
        fps: Frames per second.

    Returns:
        Timestamp in seconds.
    """
    if fps <= 0:
        return 0.0
    return frame_index / fps


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to nearest frame index.

    Args:
        seconds: Time in seconds.
        fps: Frames per second.

    Returns:
        Zero-based frame index.
    """
    if fps <= 0:
        return 0
    return int(seconds * fps)
