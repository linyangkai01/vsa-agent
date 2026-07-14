"""Fixed-duration planning for recorded-video analysis."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from vsa_agent.recorded_video.models import Asset, Segment, segment_id
from vsa_agent.recorded_video.ports import Segmenter


class FixedDurationSegmenter(Segmenter):
    """Plan contiguous fixed-duration segments from probed asset metadata."""

    def __init__(self, duration_seconds: int) -> None:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        self._duration_ms = duration_seconds * 1_000

    async def plan(self, asset: Asset, pipeline_version: str) -> Sequence[Segment]:
        """Return ordered half-open segments covering the complete asset duration."""
        if asset.duration_ms is None:
            raise ValueError("asset.duration_ms is required for segmentation")

        segments: list[Segment] = []
        for ordinal, start_offset_ms in enumerate(range(0, asset.duration_ms, self._duration_ms)):
            end_offset_ms = min(start_offset_ms + self._duration_ms, asset.duration_ms)
            segments.append(
                Segment(
                    segment_id=segment_id(asset.asset_id, pipeline_version, ordinal),
                    asset_id=asset.asset_id,
                    pipeline_version=pipeline_version,
                    ordinal=ordinal,
                    start_offset_ms=start_offset_ms,
                    end_offset_ms=end_offset_ms,
                    start_time=asset.timeline_origin + timedelta(milliseconds=start_offset_ms),
                    end_time=asset.timeline_origin + timedelta(milliseconds=end_offset_ms),
                )
            )
        return segments
