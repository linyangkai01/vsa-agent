"""Tests for utils/frame_select.py."""
from vsa_agent.utils.frame_select import select_frame_indices, frames_for_timestamp_range

class TestSelectFrameIndices:
    def test_basic(self):
        indices = select_frame_indices(total_frames=100, max_frames=5)
        assert len(indices) == 5
        assert indices[0] == 0

    def test_fewer_frames_than_max(self):
        indices = select_frame_indices(total_frames=3, max_frames=10)
        assert len(indices) == 3

    def test_zero_frames(self):
        indices = select_frame_indices(total_frames=0, max_frames=5)
        assert indices == []

class TestFramesForTimestampRange:
    def test_basic(self):
        indices = frames_for_timestamp_range(fps=30.0, duration_sec=30.0, max_frames=5, start_ts=10.0, end_ts=20.0)
        assert len(indices) <= 5

    def test_zero_duration(self):
        indices = frames_for_timestamp_range(fps=30.0, duration_sec=30.0, max_frames=5, start_ts=10.0, end_ts=10.0)
        assert indices == []
