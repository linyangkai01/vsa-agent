"""Long-video understanding orchestration."""

from __future__ import annotations

from vsa_agent.config import LVSVideoUnderstandingConfig
from vsa_agent.config import get_config
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.registry import register_tool
from vsa_agent.tools.video_understanding import _timestamp_to_seconds
from vsa_agent.tools.video_understanding import analyze_video_segment


def split_video_into_chunks(duration_sec: float, chunk_duration_sec: int) -> list[tuple[float, float]]:
    """Split a video duration into ordered chunks."""
    if duration_sec <= 0 or chunk_duration_sec <= 0:
        return []

    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_sec:
        end = min(start + float(chunk_duration_sec), duration_sec)
        chunks.append((start, end))
        start = end
    return chunks


def merge_chunk_results(
    query: str,
    source_type: str,
    chunk_results: list[UnderstandingResult],
    *,
    merge_adjacent_events: bool = True,
) -> UnderstandingResult:
    """Merge chunk-level understanding results into one aggregate result."""
    summary_parts = [item.summary_text for item in chunk_results if item.summary_text]
    merged_chunks = []
    merged_events = []
    for item in chunk_results:
        merged_chunks.extend(item.chunks)
        merged_events.extend(item.events)

    if merge_adjacent_events:
        merged_events = _merge_adjacent_events(merged_events)

    return UnderstandingResult(
        query=query,
        source_type=source_type,
        summary_text="\n".join(summary_parts),
        chunks=merged_chunks,
        events=merged_events,
        metadata={"chunk_count": len(chunk_results)},
    )


def _parse_hhmmss(value: str) -> int | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _merge_adjacent_events(events: list[DetectedEvent]) -> list[DetectedEvent]:
    """Merge adjacent or overlapping events with the same semantic identity."""
    if not events:
        return []

    def _sort_key(event: DetectedEvent) -> int:
        return _parse_hhmmss(event.start_timestamp) or 0

    sorted_events = sorted(events, key=_sort_key)
    merged: list[DetectedEvent] = [sorted_events[0]]

    for current in sorted_events[1:]:
        previous = merged[-1]
        prev_end = _parse_hhmmss(previous.end_timestamp)
        cur_start = _parse_hhmmss(current.start_timestamp)
        can_merge = (
            previous.label == current.label
            and previous.description == current.description
            and prev_end is not None
            and cur_start is not None
            and cur_start <= prev_end
        )
        if can_merge:
            merged[-1] = previous.model_copy(
                update={
                    "end_timestamp": current.end_timestamp,
                    "evidence": [*previous.evidence, *current.evidence],
                }
            )
        else:
            merged.append(current)

    return merged


def _probe_video_duration(video_path: str) -> float:
    """Probe video duration in seconds."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return total_frames / fps if fps > 0 else 0.0
    finally:
        cap.release()


async def _analyze_long_video_window(
    video_path: str,
    query: str,
    source_type: str = "video_file",
    chunk_duration_sec: int = 30,
    max_frames_per_chunk: int = 12,
    model_adapter=None,
    config: LVSVideoUnderstandingConfig | None = None,
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
) -> UnderstandingResult:
    """Analyze a full video or bounded time window by chunking segment calls."""
    if config is None:
        config = get_config().lvs_video_understanding.model_copy(
            update={
                "chunk_duration_sec": chunk_duration_sec,
                "max_frames_per_chunk": max_frames_per_chunk,
            }
        )

    duration_sec = _probe_video_duration(video_path)
    start_sec = max(0.0, _timestamp_to_seconds(start_timestamp) or 0.0)
    requested_end = _timestamp_to_seconds(end_timestamp)
    end_sec = duration_sec if requested_end is None else min(duration_sec, requested_end)
    window_duration_sec = max(0.0, end_sec - start_sec)

    chunks = split_video_into_chunks(window_duration_sec, config.chunk_duration_sec)
    if config.max_chunks is not None:
        chunks = chunks[: config.max_chunks]

    chunk_results: list[UnderstandingResult] = []
    for relative_start_sec, relative_end_sec in chunks:
        absolute_start_sec = start_sec + relative_start_sec
        absolute_end_sec = start_sec + relative_end_sec
        chunk_result = await analyze_video_segment(
            video_path=video_path,
            query=query,
            source_type=source_type,
            start_timestamp=absolute_start_sec,
            end_timestamp=absolute_end_sec,
            model_adapter=model_adapter,
        )
        chunk_results.append(chunk_result)

    return merge_chunk_results(
        query,
        source_type,
        chunk_results,
        merge_adjacent_events=config.merge_adjacent_events,
    )


@register_tool(
    "lvs_video_understanding",
    description="Analyze long videos by splitting into chunks and merging structured results.",
)
async def analyze_long_video(
    video_path: str,
    query: str,
    source_type: str = "video_file",
    chunk_duration_sec: int = 30,
    max_frames_per_chunk: int = 12,
    model_adapter=None,
    config: LVSVideoUnderstandingConfig | None = None,
) -> UnderstandingResult:
    """Analyze a long video by chunking and delegating to segment analysis."""
    return await _analyze_long_video_window(
        video_path=video_path,
        query=query,
        source_type=source_type,
        chunk_duration_sec=chunk_duration_sec,
        max_frames_per_chunk=max_frames_per_chunk,
        model_adapter=model_adapter,
        config=config,
    )
