"""Video understanding tool for short-video and single-segment analysis."""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.config import VideoUnderstandingConfig
from vsa_agent.config import get_config
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import ObservationChunk
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE
from vsa_agent.registry import register_tool
from vsa_agent.utils.frame_select import frames_for_timestamp_range
from vsa_agent.utils.reasoning_parsing import parse_reasoning_content
from vsa_agent.utils.time_measure import async_measure_time
from vsa_agent.utils.time_convert import format_timestamp
from vsa_agent.utils.time_convert import parse_iso8601_duration
from vsa_agent.utils.url_translation import is_remote_url
from vsa_agent.utils.url_translation import translate_url
from vsa_agent.utils.video_file import ensure_local_video_path

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only in runtime environments missing cv2
    cv2 = None

logger = logging.getLogger(__name__)

DEFAULT_MAX_FRAMES = 24
LONG_VIDEO_THRESHOLD_SEC = 40
CHUNK_DURATION_SEC = 30
FRAMES_PER_CHUNK = 12


class VideoUnderstandingInput(BaseModel):
    """Input model for video understanding."""

    sensor_id: str = Field(default="", description="Camera/sensor identifier")
    start_timestamp: str = Field(default="", description="Start time (ISO 8601)")
    end_timestamp: str = Field(default="", description="End time (ISO 8601)")
    user_prompt: str = Field(default="", description="User query about the video")
    video_path: str = Field(default="", description="Path to video file")
    max_frames: int = Field(default=10, description="Maximum frames to extract")


def _require_cv2() -> None:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for video_understanding")


def _get_video_understanding_config(
    config: VideoUnderstandingConfig | None = None,
) -> VideoUnderstandingConfig:
    if config is not None:
        return config
    return get_config().video_understanding


def _normalize_timestamp(
    value: str | int | float | None,
    time_format: str = "iso",
) -> str:
    if value is None:
        return ""

    if isinstance(value, (int, float)):
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
    """Convert offset-style timestamps to seconds for frame extraction.

    Supports numeric values, numeric strings, and `PT...S` duration strings.
    Absolute ISO timestamps are not accepted here because local segment extraction
    has no timeline anchor to resolve them safely.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if text.upper().startswith("PT"):
        return parse_iso8601_duration(text)
    if "T" in text:
        raise ValueError("Absolute ISO timestamps are not supported for local segment extraction")
    return float(text)


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

    evidence_kwargs: dict[str, Any] = {
        "source_type": source_type,
        "frame_indices": frame_indices or [],
        "frame_timestamps": frame_timestamps or [],
        "start_timestamp": normalized_start or None,
        "end_timestamp": normalized_end or None,
    }
    if source_type == "video_file":
        evidence_kwargs["video_path"] = video_path or "<unknown>"
    else:
        evidence_kwargs["sensor_id"] = sensor_id or "<unknown>"

    evidence = EvidenceRef(**evidence_kwargs)
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


def _parse_thinking_from_content(content: str) -> tuple[str | None, str]:
    """Parse VLM response. Delegates to utils.reasoning_parsing."""
    result = parse_reasoning_content(content)
    return result.thinking if result.has_reasoning else None, result.answer


def _build_vlm_messages(frames, query, system_prompt=None):
    """Build VLM messages from frames and query. Independent, testable function."""
    image_parts = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}}
        for frame in frames
    ]
    human_prompt_parts = [
        {"type": "text", "text": VLM_HUMAN_PROMPT_TEMPLATE.format(query=query)},
        *image_parts,
    ]
    return [
        SystemMessage(content=system_prompt or SYSTEM_PROMPT_VIDEO_UNDERSTANDING),
        HumanMessage(content=human_prompt_parts),
    ]


def _extract_frames(
    video_path: str,
    max_frames: int,
    start_timestamp: float = 0.0,
    end_timestamp: float | None = None,
) -> tuple[list[str], float, float, int]:
    """Extract evenly-spaced frames from a video file."""
    _require_cv2()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise ValueError(f"Video has no frames: {video_path}")

        duration_sec = total_frames / fps if fps > 0 else 0
        if end_timestamp is None:
            end_timestamp = duration_sec

        start_ts = max(0.0, start_timestamp)
        end_ts = min(duration_sec, end_timestamp)

        time_window = end_ts - start_ts
        if time_window <= 0:
            return [], duration_sec, fps, total_frames

        frame_indices = frames_for_timestamp_range(
            fps,
            duration_sec,
            max_frames,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        if not frame_indices:
            return [], duration_sec, fps, total_frames

        import base64

        base64_frames = []
        for frame_idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError(f"Could not read frame {frame_idx}")
            _, buffer = cv2.imencode(".jpg", frame)
            base64_frames.append(base64.b64encode(buffer.tobytes()).decode("utf-8"))

        return base64_frames, duration_sec, fps, total_frames
    finally:
        cap.release()


async def _analyze_frames(
    frames: list[str],
    prompt_text: str,
    model_adapter=None,
    *,
    config: VideoUnderstandingConfig | None = None,
) -> str:
    """Send frames to VLM for analysis."""
    from vsa_agent.model_adapter import create_model_adapter

    if not frames:
        return "No frames to analyze."

    tool_config = _get_video_understanding_config(config)

    if model_adapter is None:
        app_config = get_config()
        model_name = (
            app_config.model.dev.vlm_model
            if app_config.model.mode == "dev"
            else app_config.model.prod.vlm_model
        )
        model_adapter = create_model_adapter(model_name=model_name)

    messages = _build_vlm_messages(frames, prompt_text)
    last_error: Exception | None = None
    for attempt in range(1, tool_config.max_retries + 1):
        try:
            async with async_measure_time("video_understanding._analyze_frames", logger=logger):
                response = await model_adapter.invoke(messages)
            result = str(response.content) if response.content is not None else ""
            logger.info("VLM response length: %d chars", len(result))
            return result
        except Exception as exc:  # pragma: no cover - exercised in integration paths
            last_error = exc
            logger.warning(
                "VLM call attempt %d/%d failed for query '%s': %s",
                attempt,
                tool_config.max_retries,
                prompt_text[:60],
                exc,
            )

    raise RuntimeError(f"VLM call failed for query '{prompt_text[:60]}...': {last_error}") from last_error


def _prepare_video_path(
    video_path: str,
    config: VideoUnderstandingConfig,
    *,
    source_type: str = "video_file",
) -> str:
    if not video_path:
        return video_path

    if config.source_mode == "translated" or is_remote_url(video_path):
        translated = translate_url(video_path, target_base=config.translated_base_dir)
        if source_type == "rtsp" and (
            translated.startswith("rtsp://")
            or translated.startswith("http://")
            or translated.startswith("https://")
        ):
            return translated
        return ensure_local_video_path(translated)

    return ensure_local_video_path(video_path)


def _get_requested_window_duration(
    total_duration_sec: float,
    start_timestamp: str | int | float | None,
    end_timestamp: str | int | float | None,
) -> float:
    """Return the requested analysis window length in seconds when offsets are provided."""
    start_offset = _timestamp_to_seconds(start_timestamp)
    end_offset = _timestamp_to_seconds(end_timestamp)
    normalized_start = max(0.0, start_offset or 0.0)
    normalized_end = total_duration_sec if end_offset is None else min(total_duration_sec, end_offset)
    return max(0.0, normalized_end - normalized_start)


def _get_vst_client():
    from vsa_agent.integrations.vst_client import VSTClient

    return VSTClient(external_url="http://localhost:30888")


async def _resolve_video_source(
    video_path: str,
    sensor_id: str | None,
    source_type: str,
    config: VideoUnderstandingConfig,
    *,
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
) -> str:
    """Resolve the concrete analyzable source from explicit path or sensor mapping."""
    from vsa_agent.integrations.vst_client import VSTClientError
    has_time_window = bool(str(start_timestamp or "").strip() or str(end_timestamp or "").strip())

    if video_path:
        return video_path

    if source_type == "rtsp":
        if sensor_id:
            try:
                vst_client = _get_vst_client()
                clip = await vst_client.get_video_clip(
                    sensor_id,
                    "" if start_timestamp is None else str(start_timestamp),
                    "" if end_timestamp is None else str(end_timestamp),
                )
                if clip.local_path:
                    return clip.local_path
                if clip.clip_url:
                    return clip.clip_url
            except VSTClientError:
                if has_time_window:
                    raise
        if sensor_id and sensor_id in config.vst_sensor_source_map:
            return config.vst_sensor_source_map[sensor_id]
        raise ValueError(f"No VST source mapping for sensor_id '{sensor_id}'")

    return video_path


async def generate_understanding_prompt(*args, **kwargs):
    """Lazy wrapper to avoid hard coupling to prompt_gen import paths in tests."""
    from vsa_agent.tools.prompt_gen import generate_understanding_prompt as _generate_prompt

    return await _generate_prompt(*args, **kwargs)


async def analyze_video_segment(
    video_path: str | None = None,
    frames: list[str] | None = None,
    query: str = "",
    source_type: str = "video_file",
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
    model_adapter=None,
    config: VideoUnderstandingConfig | None = None,
    prompt_used: str | None = None,
    sensor_id: str | None = None,
) -> UnderstandingResult:
    """Analyze a single short video or bounded segment and return structured output."""
    tool_config = _get_video_understanding_config(config)
    prompt_text = prompt_used or await generate_understanding_prompt(
        query,
        context={"source_type": source_type},
    )
    resolved_video_path = None

    if frames is None:
        source_candidate = await _resolve_video_source(
            video_path or "",
            sensor_id,
            source_type,
            tool_config,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        resolved_video_path = (
            _prepare_video_path(source_candidate, tool_config, source_type=source_type)
            if source_candidate
            else None
        )
        if not resolved_video_path:
            raise ValueError("Either 'video_path' or 'frames' must be provided")
        if source_type != "rtsp" and not os.path.exists(resolved_video_path):
            raise ValueError(f"Video file not found: {resolved_video_path}")
        start_offset = _timestamp_to_seconds(start_timestamp)
        end_offset = _timestamp_to_seconds(end_timestamp)
        frames, _, _, _ = _extract_frames(
            resolved_video_path,
            DEFAULT_MAX_FRAMES,
            start_timestamp=start_offset or 0.0,
            end_timestamp=end_offset,
        )

    raw_output = await _analyze_frames(
        frames,
        prompt_text,
        model_adapter,
        config=tool_config,
    )
    thinking, parsed_answer = _parse_thinking_from_content(raw_output)
    normalized_output = parsed_answer if tool_config.filter_thinking else raw_output

    return _normalize_model_response(
        query=query,
        source_type=source_type,
        raw_output=raw_output,
        prompt_used=prompt_text,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        thinking=thinking if tool_config.filter_thinking else None,
        time_format=tool_config.time_format,
        video_path=resolved_video_path,
        sensor_id=sensor_id,
        filter_thinking=tool_config.filter_thinking,
    )


async def analyze_video(
    video_path: str = "",
    query: str = "",
    model_adapter=None,
    frames: list[str] | None = None,
    source_type: str = "video_file",
    sensor_id: str | None = None,
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
    config: VideoUnderstandingConfig | None = None,
) -> UnderstandingResult:
    """Unified internal entrypoint returning structured understanding results."""
    tool_config = _get_video_understanding_config(config)

    if frames is not None:
        return await analyze_video_segment(
            frames=frames,
            query=query,
            model_adapter=model_adapter,
            config=tool_config,
            source_type=source_type,
            sensor_id=sensor_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    source_candidate = await _resolve_video_source(
        video_path,
        sensor_id,
        source_type,
        tool_config,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if not source_candidate:
        raise ValueError("Either 'video_path' or 'frames' must be provided")

    resolved_video_path = _prepare_video_path(source_candidate, tool_config, source_type=source_type)
    if source_type == "rtsp" and resolved_video_path.startswith("rtsp://"):
        return await analyze_video_segment(
            video_path=resolved_video_path,
            query=query,
            model_adapter=model_adapter,
            config=tool_config,
            source_type=source_type,
            sensor_id=sensor_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    if source_type != "rtsp" and not os.path.exists(resolved_video_path):
        raise ValueError(f"Video file not found: {resolved_video_path}")

    _require_cv2()
    cap = cv2.VideoCapture(resolved_video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {resolved_video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration_sec = total_frames / fps if fps > 0 else 0

    logger.info(
        "Video: %s, duration: %.1fs, fps: %.1f, frames: %d",
        resolved_video_path,
        duration_sec,
        fps,
        total_frames,
    )

    requested_duration_sec = _get_requested_window_duration(
        duration_sec,
        start_timestamp,
        end_timestamp,
    )
    if requested_duration_sec > LONG_VIDEO_THRESHOLD_SEC:
        logger.info(
            "Analysis window %.1fs > %ds threshold, using Phase 2 long-video pipeline",
            requested_duration_sec,
            LONG_VIDEO_THRESHOLD_SEC,
        )
        return await analyze_long_video(
            video_path=resolved_video_path,
            query=query,
            source_type=source_type,
            model_adapter=model_adapter,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    return await analyze_video_segment(
        video_path=resolved_video_path,
        query=query,
        model_adapter=model_adapter,
        config=tool_config,
        source_type=source_type,
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )


async def analyze_long_video(*args, **kwargs):
    """Lazy wrapper to avoid import cycle with lvs_video_understanding."""
    from vsa_agent.tools import lvs_video_understanding as _lvs_video_understanding

    if "start_timestamp" in kwargs or "end_timestamp" in kwargs:
        return await _lvs_video_understanding._analyze_long_video_window(*args, **kwargs)

    return await _lvs_video_understanding.analyze_long_video(*args, **kwargs)


async def summarize_understanding_result(*args, **kwargs):
    """Lazy wrapper to avoid import cycle with vss_summarize."""
    from vsa_agent.tools.vss_summarize import summarize_understanding_result as _summarize

    return await _summarize(*args, **kwargs)


async def _analyze_chunked(
    video_path: str,
    query: str,
    duration_sec: float,
    model_adapter=None,
    *,
    config: VideoUnderstandingConfig | None = None,
) -> str:
    """Analyze a long video by chunking."""
    tool_config = _get_video_understanding_config(config)
    num_chunks = max(1, math.ceil(duration_sec / CHUNK_DURATION_SEC))
    logger.info(
        "Long video (%.1fs): chunking into %d chunks of %ds",
        duration_sec,
        num_chunks,
        CHUNK_DURATION_SEC,
    )

    captions = []
    for i in range(num_chunks):
        start = i * CHUNK_DURATION_SEC
        end = min(start + CHUNK_DURATION_SEC, duration_sec)

        frames, _, _, _ = _extract_frames(
            video_path,
            FRAMES_PER_CHUNK,
            start_timestamp=start,
            end_timestamp=end,
        )

        if frames:
            caption = await _analyze_frames(
                frames,
                query,
                model_adapter,
                config=tool_config,
            )
            captions.append(f"[{start:.0f}s-{end:.0f}s] {caption}")
        else:
            captions.append(f"[{start:.0f}s-{end:.0f}s] No frames extracted")

    report = [
        "Video Summary Report",
        f"Query: {query}",
        f"Duration: {duration_sec:.1f}s, Chunks: {num_chunks}",
        "=" * 40,
        "",
    ]
    for caption in captions:
        report.append(caption)
        report.append("")

    return "\n".join(report)


@register_tool(
    "video_understanding",
    description="Analyze a video file. Provide the video_path and a query about what to look for. "
    "For short videos (<40s), extracts frames and sends to VLM directly. "
    "For long videos (>40s), automatically chunks the video and analyzes each segment. "
    "Returns a detailed textual description. One-step tool - no need to call frame_extract first.",
)
async def video_understanding_tool(
    video_path: str = "",
    query: str = "",
    model_adapter=None,
    frames: list[str] | None = None,
    source_type: str = "video_file",
    sensor_id: str | None = None,
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
) -> str:
    """Analyze a video file in one step and keep the legacy text return path."""
    result = await analyze_video(
        video_path=video_path,
        query=query,
        model_adapter=model_adapter,
        frames=frames,
        source_type=source_type,
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if result.metadata.get("chunk_count") is not None:
        summary = await summarize_understanding_result(
            result,
            query,
            model_adapter,
        )
        return summary.text_output
    return result.summary_text
