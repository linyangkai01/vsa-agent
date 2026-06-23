"""Helpers for converting frame indices into video timestamps."""

from __future__ import annotations

from vsa_agent.registry import register_tool
from vsa_agent.utils.time_convert import format_timestamp
from vsa_agent.utils.time_convert import frames_to_seconds


def frame_indices_to_timestamps(
    frame_indices: list[int],
    fps: float,
    start_seconds: float = 0.0,
    fmt: str = "hh:mm:ss",
) -> list[dict[str, float | int | str]]:
    """Convert frame indices into timestamp metadata."""
    if not frame_indices:
        return []
    if fps <= 0:
        raise ValueError("fps must be positive")

    results: list[dict[str, float | int | str]] = []
    for frame_index in frame_indices:
        seconds = start_seconds + frames_to_seconds(frame_index, fps)
        results.append(
            {
                "frame_index": frame_index,
                "seconds": seconds,
                "timestamp": format_timestamp(seconds, fmt=fmt),
            }
        )
    return results


@register_tool(
    "video_frame_timestamp",
    description="Convert video frame indices into timestamp metadata.",
)
async def video_frame_timestamp_tool(
    frame_indices: list[int],
    fps: float,
    start_seconds: float = 0.0,
    fmt: str = "hh:mm:ss",
) -> list[dict[str, float | int | str]]:
    """Tool wrapper for converting frame indices to timestamps."""
    return frame_indices_to_timestamps(
        frame_indices,
        fps,
        start_seconds=start_seconds,
        fmt=fmt,
    )
