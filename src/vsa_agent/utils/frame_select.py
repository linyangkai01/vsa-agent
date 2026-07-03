"""Frame selection utilities for video analysis."""

from __future__ import annotations

import math

from vsa_agent.utils.time_convert import seconds_to_frames


def select_frame_indices(
    total_frames: int,
    max_frames: int,
    start_frame: int = 0,
    end_frame: int | None = None,
) -> list[int]:
    """Select evenly-spaced frame indices from a frame window."""
    if total_frames <= 0 or max_frames <= 0:
        return []

    if end_frame is None:
        end_frame = total_frames

    start_frame = max(0, start_frame)
    end_frame = min(total_frames, end_frame)

    window = end_frame - start_frame
    if window <= 0:
        return []
    if window <= max_frames:
        return list(range(start_frame, end_frame))
    if max_frames == 1:
        return [start_frame]

    step = (window - 1) / (max_frames - 1)
    return [
        min(end_frame - 1, start_frame + math.floor(index * step))
        for index in range(max_frames)
    ]


def frames_for_timestamp_range(
    fps: float,
    duration_sec: float,
    max_frames: int,
    start_ts: float = 0.0,
    end_ts: float | None = None,
) -> list[int]:
    """Select frame indices for a given time range."""
    if fps <= 0 or duration_sec <= 0 or max_frames <= 0:
        return []

    if end_ts is None:
        end_ts = duration_sec

    start_ts = max(0.0, start_ts)
    end_ts = min(duration_sec, end_ts)
    if end_ts <= start_ts:
        return []

    total_frames = seconds_to_frames(duration_sec, fps)
    start_frame = seconds_to_frames(start_ts, fps)
    if start_ts > 0:
        # Treat non-zero segment starts as exclusive so adjacent long-video
        # chunks do not re-save the same boundary frame.
        start_frame += 1
    end_frame = min(total_frames, max(start_frame + 1, math.ceil(end_ts * fps)))

    return select_frame_indices(total_frames, max_frames, start_frame, end_frame)
