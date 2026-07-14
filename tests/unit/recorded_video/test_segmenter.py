from __future__ import annotations

from datetime import UTC, datetime, timedelta

from vsa_agent.recorded_video.models import Asset, AssetStatus, segment_id
from vsa_agent.recorded_video.ports import Segmenter
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


def _asset(duration_ms: int) -> Asset:
    return Asset(
        asset_id="asset-a",
        display_filename="a.mp4",
        safe_filename="a.mp4",
        size_bytes=1,
        sha256="a" * 64,
        mime_type="video/mp4",
        source_extension="mp4",
        duration_ms=duration_ms,
        timeline_origin=ORIGIN,
        status=AssetStatus.READY,
        created_at=ORIGIN,
        updated_at=ORIGIN,
    )


async def test_fixed_duration_segmenter_emits_stable_last_partial_segment() -> None:
    segmenter = FixedDurationSegmenter(30)

    segments = list(await segmenter.plan(_asset(61_000), "pipeline-v1"))

    assert isinstance(segmenter, Segmenter)
    assert [(segment.ordinal, segment.start_offset_ms, segment.end_offset_ms) for segment in segments] == [
        (0, 0, 30_000),
        (1, 30_000, 60_000),
        (2, 60_000, 61_000),
    ]
    assert [segment.segment_id for segment in segments] == [
        segment_id("asset-a", "pipeline-v1", ordinal) for ordinal in range(3)
    ]
    assert all(segment.pipeline_version == "pipeline-v1" for segment in segments)


async def test_segment_times_use_timeline_origin_plus_offsets() -> None:
    segments = list(await FixedDurationSegmenter(30).plan(_asset(61_000), "pipeline-v1"))

    assert [(segment.start_time, segment.end_time) for segment in segments] == [
        (ORIGIN, ORIGIN + timedelta(seconds=30)),
        (ORIGIN + timedelta(seconds=30), ORIGIN + timedelta(seconds=60)),
        (ORIGIN + timedelta(seconds=60), ORIGIN + timedelta(seconds=61)),
    ]


async def test_exact_boundary_has_no_empty_trailing_segment() -> None:
    segments = list(await FixedDurationSegmenter(30).plan(_asset(60_000), "pipeline-v1"))

    assert [(segment.start_offset_ms, segment.end_offset_ms) for segment in segments] == [
        (0, 30_000),
        (30_000, 60_000),
    ]


async def test_segment_boundaries_have_no_overlaps_or_gaps() -> None:
    segments = list(await FixedDurationSegmenter(7).plan(_asset(25_001), "pipeline-v1"))

    assert segments[0].start_offset_ms == 0
    assert all(left.end_offset_ms == right.start_offset_ms for left, right in zip(segments, segments[1:]))
    assert segments[-1].end_offset_ms == 25_001
