"""Utility functions for video analytics.

Provides time bucketing, event overlap analysis, and other helpers.
Mirrors NVIDIA video_analytics/utils.py.
"""

from __future__ import annotations

from typing import Any


def create_time_buckets(
    start_sec: float,
    end_sec: float,
    bucket_duration_sec: float = 60.0,
) -> list[tuple[float, float]]:
    """Split a time range into evenly-sized buckets.

    Args:
        start_sec: Start time in seconds.
        end_sec: End time in seconds.
        bucket_duration_sec: Duration of each bucket in seconds.

    Returns:
        List of (bucket_start, bucket_end) tuples.
    """
    buckets: list[tuple[float, float]] = []
    current = start_sec
    while current < end_sec:
        bucket_end = min(current + bucket_duration_sec, end_sec)
        buckets.append((current, bucket_end))
        current = bucket_end
    return buckets


def check_event_overlap(
    event_a: tuple[float, float],
    event_b: tuple[float, float],
    threshold_sec: float = 0.0,
) -> bool:
    """Check if two time-range events overlap.

    Args:
        event_a: (start_sec, end_sec) for event A.
        event_b: (start_sec, end_sec) for event B.
        threshold_sec: Minimum overlap duration to count as overlap.

    Returns:
        True if events overlap by at least threshold_sec.
    """
    overlap_start = max(event_a[0], event_b[0])
    overlap_end = min(event_a[1], event_b[1])
    overlap_duration = overlap_end - overlap_start
    return overlap_duration >= threshold_sec


def merge_overlapping_events(
    events: list[tuple[float, float, Any]],
    threshold_sec: float = 0.0,
) -> list[tuple[float, float, list[Any]]]:
    """Merge overlapping events into combined time ranges.

    Args:
        events: List of (start_sec, end_sec, data) tuples.
        threshold_sec: Minimum overlap to consider merging.

    Returns:
        List of merged (start_sec, end_sec, [data]) tuples.
    """
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: e[0])
    merged: list[tuple[float, float, list[Any]]] = []

    current_start, current_end, current_data = sorted_events[0]
    current_items = [current_data]

    for start, end, data in sorted_events[1:]:
        if start - current_end <= threshold_sec:
            # Overlaps or adjacent — merge
            current_end = max(current_end, end)
            current_items.append(data)
        else:
            merged.append((current_start, current_end, current_items))
            current_start, current_end = start, end
            current_items = [data]

    merged.append((current_start, current_end, current_items))
    return merged
