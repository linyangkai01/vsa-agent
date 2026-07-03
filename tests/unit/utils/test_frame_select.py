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

    def test_spans_window_including_last_frame(self):
        indices = select_frame_indices(total_frames=10, max_frames=3)
        assert indices == [0, 4, 9]

    def test_clamps_start_and_end(self):
        indices = select_frame_indices(total_frames=20, max_frames=4, start_frame=-3, end_frame=50)
        assert indices == [0, 6, 12, 19]

class TestFramesForTimestampRange:
    def test_basic(self):
        indices = frames_for_timestamp_range(fps=30.0, duration_sec=30.0, max_frames=5, start_ts=10.0, end_ts=20.0)
        assert len(indices) <= 5

    def test_zero_duration(self):
        indices = frames_for_timestamp_range(fps=30.0, duration_sec=30.0, max_frames=5, start_ts=10.0, end_ts=10.0)
        assert indices == []

    def test_returns_empty_when_fps_invalid(self):
        indices = frames_for_timestamp_range(fps=0.0, duration_sec=30.0, max_frames=5)
        assert indices == []

    def test_clamps_requested_window(self):
        indices = frames_for_timestamp_range(
            fps=10.0,
            duration_sec=5.0,
            max_frames=3,
            start_ts=-1.0,
            end_ts=10.0,
        )
        assert indices == [0, 24, 49]

    def test_adjacent_windows_do_not_repeat_boundary_frame(self):
        first = frames_for_timestamp_range(
            fps=30.0,
            duration_sec=60.0,
            max_frames=4,
            start_ts=0.0,
            end_ts=30.0,
        )
        second = frames_for_timestamp_range(
            fps=30.0,
            duration_sec=60.0,
            max_frames=4,
            start_ts=30.0,
            end_ts=60.0,
        )

        assert first[-1] < second[0]
