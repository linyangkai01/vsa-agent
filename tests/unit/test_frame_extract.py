"""Tests for the frame_extract tool — video frame extraction with OpenCV."""

import asyncio
import os
import tempfile

import cv2
import numpy as np
import pytest

from vsa_agent.registry import ToolRegistry


# ===== Helpers =====


def _create_test_video(path: str, duration_sec: float = 3.0, fps: int = 10) -> None:
    """Create a simple test MP4 with colored frames that differ each frame."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    width, height = 320, 240
    out = cv2.VideoWriter(path, fourcc, fps, (width, height))
    if not out.isOpened():
        raise RuntimeError(f"Failed to open VideoWriter for {path}")
    total_frames = int(duration_sec * fps)
    for i in range(total_frames):
        frame = np.full((height, width, 3), (i * 10, 100, 200), dtype=np.uint8)
        out.write(frame)
    out.release()


# ===== Tests =====


class TestFrameExtract:
    """Test the frame_extract registered tool."""

    def test_extract_frames_basic(self):
        """Extract max_frames from a 3-second video at 10 fps."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=3.0, fps=10)

            fn = ToolRegistry.get("frame_extract")
            assert fn is not None, "frame_extract tool must be registered"

            result = asyncio.run(fn(video_path=video_path, max_frames=5))

            assert len(result["frames"]) == 5
            assert result["duration_sec"] == pytest.approx(3.0, abs=0.1)
            for frame_b64 in result["frames"]:
                assert isinstance(frame_b64, str)
                assert len(frame_b64) > 0
        finally:
            os.unlink(video_path)

    def test_extract_frames_default_max(self):
        """When max_frames is not specified, default to 10 frames."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=5.0, fps=10)

            fn = ToolRegistry.get("frame_extract")
            result = asyncio.run(fn(video_path=video_path))

            assert len(result["frames"]) == 10
            assert result["duration_sec"] == pytest.approx(5.0, abs=0.1)
        finally:
            os.unlink(video_path)

    def test_extract_frames_with_time_range(self):
        """Extract frames from a specific time window."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=5.0, fps=10)

            fn = ToolRegistry.get("frame_extract")
            result = asyncio.run(fn(video_path=video_path, max_frames=2,
                                     start_timestamp=1.0, end_timestamp=2.0))

            assert len(result["frames"]) == 2
        finally:
            os.unlink(video_path)

    def test_extract_frames_invalid_path(self):
        """Non-existent video path should raise ValueError."""
        fn = ToolRegistry.get("frame_extract")
        with pytest.raises(ValueError, match="Could not open video"):
            asyncio.run(fn(video_path="/nonexistent/video.mp4", max_frames=5))

    def test_extract_frames_short_video(self):
        """Video shorter than max_frames should return all available frames."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=0.5, fps=10)

            fn = ToolRegistry.get("frame_extract")
            result = asyncio.run(fn(video_path=video_path, max_frames=20))

            assert len(result["frames"]) <= 5
        finally:
            os.unlink(video_path)

    def test_extract_frames_reversed_timestamps(self):
        """When end_timestamp < start_timestamp, return empty frames with metadata."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=3.0, fps=10)

            fn = ToolRegistry.get("frame_extract")
            result = asyncio.run(fn(video_path=video_path, max_frames=5,
                                     start_timestamp=2.0, end_timestamp=1.0))

            assert result["frames"] == []
            assert result["extracted_count"] == 0
            assert result["duration_sec"] > 0
            assert result["fps"] > 0
            assert result["frame_count"] > 0
        finally:
            os.unlink(video_path)

    def test_extract_frames_metadata(self):
        """Result dict should include duration and valid base64 frames."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name
        try:
            _create_test_video(video_path, duration_sec=2.0, fps=10)

            fn = ToolRegistry.get("frame_extract")
            result = asyncio.run(fn(video_path=video_path, max_frames=3))

            assert "duration_sec" in result
            assert result["duration_sec"] > 0
            for frame in result["frames"]:
                assert isinstance(frame, str)
                assert len(frame) > 100
        finally:
            os.unlink(video_path)
