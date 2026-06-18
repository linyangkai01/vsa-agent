"""Video frame extraction tool — extracts evenly-spaced frames from a video file.

Uses OpenCV to read video frames and returns them as base64-encoded JPEG strings,
suitable for feeding into VLM models for video understanding tasks.

Design Pattern: #1 Plugin Registration, #10 Registry Table.
"""

import base64
import logging
import math

import cv2

from vsa_agent.registry import register_tool
from vsa_agent.tools.frame_store import store_frames
from vsa_agent.utils.frame_select import select_frame_indices

logger = logging.getLogger(__name__)

# ===== Constants =====

DEFAULT_MAX_FRAMES = 10
DEFAULT_START_TIMESTAMP = 0.0


# ===== Core Utility =====


def _extract_frames(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
    start_timestamp: float,
    end_timestamp: float,
    step_size: float,
) -> list[str]:
    """Select frames from an already-opened video at evenly-spaced intervals.

    Args:
        cap: An opened cv2.VideoCapture instance positioned at the start.
        fps: Frames per second of the source video.
        total_frames: Total number of frames in the source video.
        start_timestamp: Start time in seconds.
        end_timestamp: End time in seconds.
        step_size: Time interval between frames in seconds.

    Returns:
        List of base64-encoded JPEG frame images.
    """
    start_frame = min(total_frames - 1, math.floor(start_timestamp * fps))
    end_frame = min(total_frames, max(start_frame + 1, math.ceil(end_timestamp * fps)))
    time_window = max(0.0, end_timestamp - start_timestamp)
    requested_frames = max(1, math.ceil(time_window / step_size)) if step_size > 0 else 1

    frame_indices = select_frame_indices(
        total_frames,
        requested_frames,
        start_frame=start_frame,
        end_frame=end_frame,
    )
    if not frame_indices:
        logger.warning(
            "No frames selected from %.2fs to %.2fs (step=%.2fs)",
            start_timestamp, end_timestamp, step_size,
        )
        return []

    base64_frames: list[str] = []
    for frame_idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()

        if not ret:
            raise RuntimeError(f"Could not read frame {frame_idx}")

        _, buffer = cv2.imencode(".jpg", frame)
        base64_frames.append(base64.b64encode(buffer.tobytes()).decode("utf-8"))

    return base64_frames




# ===== GPU Detection =====


def has_nvidia_gpu() -> bool:
    """Check for NVIDIA GPU availability. Mirrors NVIDIA has_nvidia_gpu()."""
    import shutil
    import subprocess
    return (
        shutil.which("nvidia-smi") is not None
        and subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0
    )

# ===== Registered Tool =====


@register_tool(
    "frame_extract",
    description="Extract evenly-spaced frames from a video file. Returns metadata with a frame_key reference. "
                "Pass the frame_key to video_understanding to analyze the frames.",
)
async def frame_extract_tool(
    video_path: str,
    max_frames: int = DEFAULT_MAX_FRAMES,
    start_timestamp: float = DEFAULT_START_TIMESTAMP,
    end_timestamp: float | None = None,
) -> dict:
    """Extract up to max_frames evenly-spaced frames from a video.

    Frames are stored in an internal frame store. The returned dict contains
    a 'frame_key' that can be passed to video_understanding_tool to analyze
    the frames. The 'frames' field is included for backward compatibility
    but is deprecated - use frame_key instead.

    Args:
        video_path: Absolute or relative path to the video file.
        max_frames: Maximum number of frames to extract (default 10).
        start_timestamp: Start time offset in seconds (default 0.0).
        end_timestamp: End time offset in seconds (None = read entire duration).

    Returns:
        dict with keys:
            frame_key: reference key for video_understanding
            frames: list of base64-encoded JPEG strings (deprecated)
            duration_sec: total video duration in seconds
            fps: frames per second of the source video
            frame_count: total number of frames in the source video
            extracted_count: number of frames actually extracted
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames <= 0:
            raise ValueError(f"Video has no frames: {video_path}")

        duration_sec = total_frames / fps if fps > 0 else total_frames / 30.0

        if end_timestamp is None:
            end_timestamp = duration_sec

        # Clamp timestamps to valid range
        start_timestamp = max(0.0, start_timestamp)
        end_timestamp = min(duration_sec, end_timestamp)

        time_window = end_timestamp - start_timestamp
        if time_window <= 0:
            logger.warning(
                "Empty time window for %s: start=%.2f end=%.2f",
                video_path, start_timestamp, end_timestamp,
            )
            return {
                "frame_key": "",
                "frames": [],
                "duration_sec": duration_sec,
                "fps": fps,
                "frame_count": total_frames,
                "extracted_count": 0,
            }

        # Calculate step_size to get evenly-spaced frames
        step_size = time_window / max_frames

        frames = _extract_frames(
            cap, fps, total_frames, start_timestamp, end_timestamp, step_size,
        )

        # Store frames in shared store, return reference key
        frame_key = store_frames(frames, {
            "video_path": video_path,
            "duration_sec": duration_sec,
            "fps": fps,
            "frame_count": total_frames,
            "extracted_count": len(frames),
        })

        return {
            "frame_key": frame_key,
            "frames": frames,
            "duration_sec": duration_sec,
            "fps": fps,
            "frame_count": total_frames,
            "extracted_count": len(frames),
        }
    finally:
        cap.release()
