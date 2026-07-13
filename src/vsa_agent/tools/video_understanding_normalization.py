"""Pure normalization helpers for video-understanding results."""

from __future__ import annotations

import re
from typing import Any

from vsa_agent.data_models.understanding import DetectedEvent, EvidenceRef, ObservationChunk, UnderstandingResult
from vsa_agent.utils.reasoning_parsing import parse_reasoning_content
from vsa_agent.utils.time_convert import format_timestamp, parse_iso8601_duration


def _normalize_timestamp(
    value: str | int | float | None,
    time_format: str = "iso",
) -> str:
    if value is None:
        return ""

    if isinstance(value, int | float):
        seconds = float(value)
    else:
        text = str(value).strip()
        if not text:
            return ""
        if "T" in text:
            return text
        try:
            seconds = float(text)
        except ValueError:
            if text.upper().startswith("PT"):
                seconds = parse_iso8601_duration(text)
            else:
                return text

    if time_format == "offset":
        if seconds.is_integer():
            return f"PT{int(seconds)}S"
        return f"PT{seconds}S"

    return format_timestamp(seconds, fmt="hh:mm:ss")


def _timestamp_to_seconds(value: str | int | float | None) -> float | None:
    """Convert offset-style timestamps to seconds for frame extraction."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if text.upper().startswith("PT"):
        return parse_iso8601_duration(text)
    if "T" in text:
        raise ValueError("Absolute ISO timestamps are not supported for local segment extraction")
    return float(text)


def _parse_thinking_from_content(content: str) -> tuple[str | None, str]:
    """Separate reasoning content from the model answer."""
    result = parse_reasoning_content(content)
    return result.thinking if result.has_reasoning else None, result.answer


def _build_evidence(
    *,
    source_type: str,
    video_path: str | None,
    sensor_id: str | None,
    frame_indices: list[int] | None,
    frame_timestamps: list[str] | None,
    start_timestamp: str,
    end_timestamp: str,
) -> EvidenceRef:
    evidence_kwargs: dict[str, Any] = {
        "source_type": source_type,
        "frame_indices": frame_indices or [],
        "frame_timestamps": frame_timestamps or [],
        "start_timestamp": start_timestamp or None,
        "end_timestamp": end_timestamp or None,
    }
    if source_type == "video_file":
        evidence_kwargs["video_path"] = video_path or "<unknown>"
    else:
        evidence_kwargs["sensor_id"] = sensor_id or "<unknown>"
    return EvidenceRef(**evidence_kwargs)


def _extract_events_from_text(
    normalized_text: str,
    start_timestamp: str,
    end_timestamp: str,
    evidence: EvidenceRef,
) -> list[DetectedEvent]:
    """Extract lightweight structured events from model output text."""
    events: list[DetectedEvent] = []

    pattern = re.compile(r"<([^>]+)>\s*(.*?)\s*</timestamp>", re.DOTALL)
    matches = list(pattern.finditer(normalized_text))
    if matches:
        for idx, match in enumerate(matches):
            timestamp = match.group(1).strip()
            description = match.group(2).strip()
            if not description:
                continue
            label = " ".join(description.split()[:3]).strip().lower() or "event"
            events.append(
                DetectedEvent(
                    event_id=f"event-{idx}",
                    label=label,
                    description=description,
                    start_timestamp=timestamp,
                    end_timestamp=timestamp,
                    evidence=[evidence],
                )
            )
        return events

    if normalized_text.strip():
        label = " ".join(normalized_text.split()[:3]).strip().lower() or "event"
        return [
            DetectedEvent(
                event_id="event-0",
                label=label,
                description=normalized_text.strip(),
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                evidence=[evidence],
            )
        ]

    return []


def _normalize_model_response(
    query: str,
    source_type: str,
    raw_output: str | dict[str, Any] | UnderstandingResult,
    prompt_used: str,
    start_timestamp: str | int | float | None,
    end_timestamp: str | int | float | None,
    thinking: str | None,
    *,
    time_format: str = "iso",
    video_path: str | None = None,
    sensor_id: str | None = None,
    frame_indices: list[int] | None = None,
    frame_timestamps: list[str] | None = None,
    filter_thinking: bool = True,
) -> UnderstandingResult:
    """Normalize model output into the shared UnderstandingResult contract."""
    if isinstance(raw_output, UnderstandingResult):
        return raw_output

    if isinstance(raw_output, dict):
        payload = dict(raw_output)
        payload.setdefault("query", query)
        payload.setdefault("source_type", source_type)
        return UnderstandingResult(**payload)

    normalized_start = _normalize_timestamp(start_timestamp, time_format=time_format)
    normalized_end = _normalize_timestamp(end_timestamp, time_format=time_format)
    normalized_text = raw_output.strip()

    if filter_thinking and thinking:
        _, normalized_text = _parse_thinking_from_content(raw_output)

    evidence = _build_evidence(
        source_type=source_type,
        video_path=video_path,
        sensor_id=sensor_id,
        frame_indices=frame_indices,
        frame_timestamps=frame_timestamps,
        start_timestamp=normalized_start,
        end_timestamp=normalized_end,
    )
    chunk = ObservationChunk(
        chunk_id="segment-0",
        start_timestamp=normalized_start,
        end_timestamp=normalized_end,
        prompt_used=prompt_used,
        raw_model_output=raw_output,
        normalized_text=normalized_text,
        thinking=thinking,
        evidence=evidence,
    )
    events = _extract_events_from_text(
        normalized_text=normalized_text,
        start_timestamp=normalized_start,
        end_timestamp=normalized_end,
        evidence=evidence,
    )
    return UnderstandingResult(
        query=query,
        source_type=source_type,
        summary_text=normalized_text,
        chunks=[chunk],
        events=events,
        metadata={"time_format": time_format},
    )


__all__ = [
    "_build_evidence",
    "_extract_events_from_text",
    "_normalize_model_response",
    "_normalize_timestamp",
    "_parse_thinking_from_content",
    "_timestamp_to_seconds",
]
