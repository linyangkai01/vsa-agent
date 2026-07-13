"""Long-video understanding orchestration."""

from __future__ import annotations

from time import perf_counter

from langgraph.config import get_stream_writer

from vsa_agent.agents.data_models import AgentMessageChunk, AgentMessageChunkType
from vsa_agent.config import LVSVideoUnderstandingConfig, get_config
from vsa_agent.data_models.understanding import DetectedEvent, UnderstandingResult
from vsa_agent.observability.live_trace import write_live_trace_event
from vsa_agent.registry import register_tool
from vsa_agent.tools.video_understanding import _timestamp_to_seconds, analyze_video_segment


def _format_seconds(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}s"
    return f"{value:.1f}s"


def _emit_chunk_progress(
    *,
    status: str,
    chunk_index: int,
    chunk_count: int,
    start_timestamp: float,
    end_timestamp: float,
    summary_length: int | None = None,
    event_count: int | None = None,
    elapsed_sec: float | None = None,
    frame_count: int | None = None,
    risk_category: str | None = None,
    risk_evidence: str | None = None,
    evidence_type: str | None = None,
    raw_artifact_path: str | None = None,
    result_artifact_path: str | None = None,
) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return

    verb = "Completed" if status == "completed" else "Analyzing"
    lines = [
        f"{verb} video chunk {chunk_index}/{chunk_count}",
        f"Window: {_format_seconds(start_timestamp)} - {_format_seconds(end_timestamp)}",
    ]
    if elapsed_sec is not None:
        lines.append(f"Elapsed: {elapsed_sec:.1f}s")
    if summary_length is not None:
        lines.append(f"Summary length: {summary_length} chars")
    if event_count is not None:
        lines.append(f"Detected events: {event_count}")
    if frame_count is not None:
        lines.append(f"Frames: {frame_count} sampled")
    if risk_category:
        lines.append(f"Risk: {risk_category}")
    if evidence_type:
        lines.append(f"Evidence type: {evidence_type}")
    if risk_evidence:
        lines.append(f"Key evidence: {risk_evidence}")
    if raw_artifact_path:
        lines.append(f"Raw VLM output: {raw_artifact_path}")
    if result_artifact_path:
        lines.append(f"Result JSON: {result_artifact_path}")

    writer(
        AgentMessageChunk(
            type=AgentMessageChunkType.TOOL_PROGRESS,
            content="\n".join(lines),
            metadata={
                "tool_name": "video_understanding",
                "status": status,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "start_sec": start_timestamp,
                "end_sec": end_timestamp,
                "summary_length": summary_length,
                "event_count": event_count,
                "elapsed_sec": elapsed_sec,
                "frame_count": frame_count,
                "risk_category": risk_category,
                "risk_evidence": risk_evidence,
                "evidence_type": evidence_type,
                "raw_artifact_path": raw_artifact_path,
                "result_artifact_path": result_artifact_path,
            },
        )
    )


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


_RISK_DIGEST_CATEGORIES = (
    ("Eye / face protection", ("eye protection", "safety goggles", "face shield", "flying sparks", "flying debris")),
    (
        "PPE / visibility",
        ("ppe", "hard hat", "safety vest", "high-visibility", "goggles", "eye protection", "face shield"),
    ),
    ("Fire / hot work", ("fire", "spark", "welding", "grinding", "angle grinder", "hot")),
    ("Slip / trip / housekeeping", ("slip", "trip", "wet", "muddy", "debris", "dust", "gravel", "uneven")),
    ("Fall / work at height", ("fall", "height", "scaffold", "rebar framework", "harness", "lanyard", "guardrail")),
    ("Heavy equipment / struck-by", ("crane", "vehicle", "excavator", "hydraulic breaker", "barrier", "struck")),
    ("Machine guarding / pinch points", ("machine", "moving parts", "guard", "entanglement", "pinch", "bending")),
    ("Chemical / respiratory exposure", ("chemical", "smoke", "fume", "respiratory", "ventilation", "inhalation")),
)


def _truncate_digest_text(value: str, max_chars: int = 240) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _classify_evidence_type(text: str) -> tuple[str, bool]:
    lowered = text.lower()
    inference_markers = (
        "could ",
        "may ",
        "might ",
        "should ",
        "suggest",
        "potential",
        "concern",
        "unclear",
        "verify",
        "check ",
        "recommend",
        "need for",
        "need to",
    )
    is_inference = any(marker in lowered for marker in inference_markers)
    return ("inferred_or_recommended" if is_inference else "observed", is_inference)


def _select_risk_category(summary_text: str) -> str:
    lowered = summary_text.lower()
    for category, keywords in _RISK_DIGEST_CATEGORIES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Additional evidence"


def _get_chunk_window(result: UnderstandingResult) -> tuple[str, str]:
    chunk = result.chunks[0] if result.chunks else None
    if not chunk:
        return "", ""
    return chunk.start_timestamp, chunk.end_timestamp


def _build_risk_digest_item(result: UnderstandingResult, chunk_index: int) -> dict:
    start, end = _get_chunk_window(result)
    evidence = _truncate_digest_text(result.summary_text)
    evidence_type, is_inference = _classify_evidence_type(evidence)
    return {
        "category": _select_risk_category(result.summary_text),
        "chunk_index": chunk_index,
        "start_timestamp": start,
        "end_timestamp": end,
        "time_range": {"start": start, "end": end},
        "evidence": evidence,
        "evidence_type": evidence_type,
        "inference": is_inference,
    }


def build_chunk_diverse_risk_digest(
    chunk_results: list[UnderstandingResult],
    *,
    max_items: int | None = None,
    max_per_chunk: int = 1,
) -> list[dict]:
    """Select a balanced set of risk snippets across chunks for long-video summarization."""
    if max_items is None:
        max_items = len(chunk_results)
    if max_items <= 0:
        return []

    digest: list[dict] = []
    per_chunk_counts: dict[int, int] = {}
    used_pairs: set[tuple[int, str]] = set()

    # First pass: guarantee broad temporal coverage, one compact evidence item per chunk.
    for chunk_index, result in enumerate(chunk_results, start=1):
        if len(digest) >= max_items:
            return digest[:max_items]
        if per_chunk_counts.get(chunk_index, 0) >= max_per_chunk:
            continue
        item = _build_risk_digest_item(result, chunk_index)
        digest.append(item)
        per_chunk_counts[chunk_index] = per_chunk_counts.get(chunk_index, 0) + 1
        used_pairs.add((chunk_index, item["category"]))

    for category, keywords in _RISK_DIGEST_CATEGORIES:
        for chunk_index, result in enumerate(chunk_results, start=1):
            if per_chunk_counts.get(chunk_index, 0) >= max_per_chunk:
                continue
            lowered = result.summary_text.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            pair = (chunk_index, category)
            if pair in used_pairs:
                continue
            item = _build_risk_digest_item(result, chunk_index)
            item["category"] = category
            digest.append(item)
            per_chunk_counts[chunk_index] = per_chunk_counts.get(chunk_index, 0) + 1
            used_pairs.add(pair)
            break
        if len(digest) >= max_items:
            return digest[:max_items]

    if len(digest) >= max_items:
        return digest[:max_items]

    for chunk_index, result in enumerate(chunk_results, start=1):
        if per_chunk_counts.get(chunk_index, 0) >= max_per_chunk:
            continue
        digest.append(_build_risk_digest_item(result, chunk_index))
        if len(digest) >= max_items:
            break

    return digest[:max_items]


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
        metadata={
            "chunk_count": len(chunk_results),
            "risk_digest": build_chunk_diverse_risk_digest(chunk_results, max_items=len(chunk_results)),
        },
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
    max_frames_per_chunk: int = 8,
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

    write_live_trace_event(
        "lvs_video_understanding.started",
        {
            "video_path": video_path,
            "query": query,
            "source_type": source_type,
            "duration_sec": duration_sec,
            "window_start_sec": start_sec,
            "window_end_sec": end_sec,
            "window_duration_sec": window_duration_sec,
            "chunk_duration_sec": config.chunk_duration_sec,
            "max_frames_per_chunk": config.max_frames_per_chunk,
            "chunk_count": len(chunks),
        },
    )

    chunk_results: list[UnderstandingResult] = []
    for index, (relative_start_sec, relative_end_sec) in enumerate(chunks, start=1):
        absolute_start_sec = start_sec + relative_start_sec
        absolute_end_sec = start_sec + relative_end_sec
        chunk_started_at = perf_counter()
        _emit_chunk_progress(
            status="started",
            chunk_index=index,
            chunk_count=len(chunks),
            start_timestamp=absolute_start_sec,
            end_timestamp=absolute_end_sec,
        )
        write_live_trace_event(
            "lvs_video_understanding.chunk.started",
            {
                "video_path": video_path,
                "query": query,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "start_timestamp": absolute_start_sec,
                "end_timestamp": absolute_end_sec,
                "max_frames": config.max_frames_per_chunk,
            },
        )
        chunk_result = await analyze_video_segment(
            video_path=video_path,
            query=query,
            source_type=source_type,
            start_timestamp=absolute_start_sec,
            end_timestamp=absolute_end_sec,
            model_adapter=model_adapter,
            max_frames=config.max_frames_per_chunk,
        )
        chunk_results.append(chunk_result)
        chunk_elapsed_sec = perf_counter() - chunk_started_at
        progress_item = _build_risk_digest_item(chunk_result, index)
        _emit_chunk_progress(
            status="completed",
            chunk_index=index,
            chunk_count=len(chunks),
            start_timestamp=absolute_start_sec,
            end_timestamp=absolute_end_sec,
            summary_length=len(chunk_result.summary_text),
            event_count=len(chunk_result.events),
            elapsed_sec=chunk_elapsed_sec,
            frame_count=chunk_result.metadata.get("frame_count"),
            risk_category=progress_item.get("category"),
            risk_evidence=progress_item.get("evidence"),
            evidence_type=progress_item.get("evidence_type"),
            raw_artifact_path=chunk_result.metadata.get("raw_artifact_path"),
            result_artifact_path=chunk_result.metadata.get("result_artifact_path"),
        )
        write_live_trace_event(
            "lvs_video_understanding.chunk.completed",
            {
                "video_path": video_path,
                "query": query,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "start_timestamp": absolute_start_sec,
                "end_timestamp": absolute_end_sec,
                "event_count": len(chunk_result.events),
                "summary_length": len(chunk_result.summary_text),
                "elapsed_sec": chunk_elapsed_sec,
            },
        )

    merged_result = merge_chunk_results(
        query,
        source_type,
        chunk_results,
        merge_adjacent_events=config.merge_adjacent_events,
    )
    merged_result.metadata.update(
        {
            "chunk_duration_sec": config.chunk_duration_sec,
            "max_frames_per_chunk": config.max_frames_per_chunk,
            "window_start_sec": start_sec,
            "window_end_sec": end_sec,
        }
    )
    write_live_trace_event(
        "lvs_video_understanding.completed",
        {
            "video_path": video_path,
            "query": query,
            "chunk_count": len(chunk_results),
            "event_count": len(merged_result.events),
            "summary_length": len(merged_result.summary_text),
        },
    )
    return merged_result


@register_tool(
    "lvs_video_understanding",
    description="Analyze long videos by splitting into chunks and merging structured results.",
)
async def analyze_long_video(
    video_path: str,
    query: str,
    source_type: str = "video_file",
    chunk_duration_sec: int = 30,
    max_frames_per_chunk: int = 8,
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
