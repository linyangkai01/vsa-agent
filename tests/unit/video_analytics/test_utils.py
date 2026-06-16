"""Tests for video_analytics/utils.py."""
from vsa_agent.video_analytics.utils import create_time_buckets, check_event_overlap, merge_overlapping_events

class TestCreateTimeBuckets:
    def test_basic(self):
        buckets = create_time_buckets(start_sec=0.0, end_sec=100.0, bucket_duration_sec=10.0)
        assert len(buckets) == 10
        assert buckets[0] == (0.0, 10.0)

    def test_single_bucket(self):
        buckets = create_time_buckets(start_sec=0.0, end_sec=5.0, bucket_duration_sec=10.0)
        assert len(buckets) == 1

    def test_zero_duration(self):
        buckets = create_time_buckets(start_sec=10.0, end_sec=10.0, bucket_duration_sec=5.0)
        assert buckets == []

class TestCheckEventOverlap:
    def test_overlapping(self):
        assert check_event_overlap((0.0, 10.0), (5.0, 15.0)) is True

    def test_non_overlapping(self):
        assert check_event_overlap((0.0, 10.0), (15.0, 20.0)) is False

    def test_adjacent_no_overlap(self):
        assert check_event_overlap((0.0, 10.0), (10.0, 20.0)) is True  # overlap_duration=0 >= threshold=0

    def test_with_threshold(self):
        assert check_event_overlap((0.0, 10.0), (9.0, 15.0), threshold_sec=0.5) is True

class TestMergeOverlappingEvents:
    def test_merge_overlapping(self):
        events = [(0.0, 5.0, "a"), (3.0, 8.0, "b"), (10.0, 15.0, "c")]
        merged = merge_overlapping_events(events)
        assert len(merged) == 2
        assert merged[0][1] == 8.0

    def test_no_overlap(self):
        events = [(0.0, 5.0, "a"), (10.0, 15.0, "b")]
        merged = merge_overlapping_events(events)
        assert len(merged) == 2

    def test_empty(self):
        merged = merge_overlapping_events([])
        assert merged == []
