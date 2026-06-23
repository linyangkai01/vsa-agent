"""Tests for tools/video_frame_timestamp.py."""

import pytest


def test_frame_indices_to_timestamps_formats_offsets():
    from vsa_agent.tools.video_frame_timestamp import frame_indices_to_timestamps

    result = frame_indices_to_timestamps([0, 15, 30], fps=30.0, start_seconds=10.0)

    assert result == [
        {"frame_index": 0, "seconds": 10.0, "timestamp": "00:00:10"},
        {"frame_index": 15, "seconds": 10.5, "timestamp": "00:00:10"},
        {"frame_index": 30, "seconds": 11.0, "timestamp": "00:00:11"},
    ]


def test_frame_indices_to_timestamps_returns_empty_for_empty_input():
    from vsa_agent.tools.video_frame_timestamp import frame_indices_to_timestamps

    assert frame_indices_to_timestamps([], fps=30.0) == []


def test_frame_indices_to_timestamps_rejects_non_positive_fps():
    from vsa_agent.tools.video_frame_timestamp import frame_indices_to_timestamps

    with pytest.raises(ValueError):
        frame_indices_to_timestamps([1, 2, 3], fps=0.0)


@pytest.mark.asyncio
async def test_video_frame_timestamp_tool_uses_helper(monkeypatch):
    from vsa_agent.tools.video_frame_timestamp import video_frame_timestamp_tool

    captured = {}

    def fake_frame_indices_to_timestamps(frame_indices, fps, start_seconds=0.0, fmt="hh:mm:ss"):
        captured["args"] = (frame_indices, fps, start_seconds, fmt)
        return [{"frame_index": 1, "seconds": 2.0, "timestamp": "00:00:02"}]

    monkeypatch.setattr(
        "vsa_agent.tools.video_frame_timestamp.frame_indices_to_timestamps",
        fake_frame_indices_to_timestamps,
    )

    result = await video_frame_timestamp_tool([1], fps=25.0, start_seconds=2.0)

    assert captured["args"] == ([1], 25.0, 2.0, "hh:mm:ss")
    assert result == [{"frame_index": 1, "seconds": 2.0, "timestamp": "00:00:02"}]
