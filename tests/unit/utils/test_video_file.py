"""Tests for utils/video_file.py."""

import pytest

from vsa_agent.utils.video_file import ensure_local_video_path, is_local_video_candidate


def test_is_local_video_candidate_accepts_windows_and_posix_paths():
    assert is_local_video_candidate("C:/videos/demo.mp4") is True
    assert is_local_video_candidate("/var/data/demo.mp4") is True


def test_is_local_video_candidate_rejects_remote_urls():
    assert is_local_video_candidate("https://example.com/video.mp4") is False
    assert is_local_video_candidate("rtsp://camera-1/stream") is False


def test_ensure_local_video_path_returns_normalized_local_path():
    assert ensure_local_video_path("C:\\videos\\demo.mp4") == "C:/videos/demo.mp4"


def test_ensure_local_video_path_rejects_remote_url():
    with pytest.raises(ValueError, match="local video file"):
        ensure_local_video_path("https://example.com/video.mp4")
