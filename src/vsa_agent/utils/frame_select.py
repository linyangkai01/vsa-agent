"""Frame selection utilities for video analysis.

Extracted from frame_extract for reuse across tools.
"""

from __future__ import annotations

import math


def select_frame_indices(
    total_frames: int,
    max_frames: int,
    start_frame: int = 0,
    end_frame: int | None = None,
) -> list[int]:
    """Select evenly-spaced frame indices from a video.

    Args:
        total_frames: Total number of frames in the video.
        max_frames: Maximum number of frames to select.
        start_frame: Starting frame index (inclusive).
        end_frame: Ending frame index (exclusive). Defaults to total_frames.

    Returns:
        List of selected frame indices.
    """
    if total_frames <= 0 or max_frames <= 0:
        return []

    if end_frame is None:
        end_frame = total_frames

    start_frame = max(0, start_frame)
    end_frame = min(total_frames, end_frame)

    window = end_frame - start_frame
    if window <= 0:
        return []

    step = max(1, window // max_frames)
    indices = list(range(start_frame, end_frame, step))

    return indices[:max_frames]


def frames_for_timestamp_range(
    fps: float,
    duration_sec: float,
    max_frames: int,
    start_ts: float = 0.0,
    end_ts: float | None = None,
) -> list[int]:
    """Select frame indices for a given time range.

    Args:
        fps: Frames per second.
        duration_sec: Total video duration.
        max_frames: Maximum frames to return.
        start_ts: Start timestamp in seconds.
        end_ts: End timestamp in seconds. Defaults to duration_sec.

    Returns:
        List of selected frame indices.
    """
    if end_ts is None:
        end_ts = duration_sec

    start_ts = max(0.0, start_ts)
    end_ts = min(duration_sec, end_ts)

    total_frames = int(duration_sec * fps)
    start_frame = int(start_ts * fps)
    end_frame = int(end_ts * fps)

    return select_frame_indices(total_frames, max_frames, start_frame, end_frame)
