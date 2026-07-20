from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentMessageChunk, AgentMessageChunkType, AgentState
from vsa_agent.config import resolve_runtime_config
from vsa_agent.observability.live_trace import live_trace_context, write_live_json_artifact, write_live_trace_event

ORIGINAL_UI_TRACE_ROOT_ENV = "VSA_ORIGINAL_UI_TRACE_ROOT"
_QUERY_CONTEXT_PREFIX = "[Context:"

logger = logging.getLogger(__name__)


class OriginalUIChatMessage(BaseModel):
    role: str
    content: str | list[Any] | dict[str, Any] = ""


class OriginalUIChatRequest(BaseModel):
    messages: list[OriginalUIChatMessage] = Field(default_factory=list)


class SelectedRecordedVideoContext(BaseModel):
    """Server-validated recorded-video identity passed to the agent graph."""

    asset_id: str
    segment_id: str = ""
    video_name: str
    video_path: Path
    start_offset_sec: float | None = None
    end_offset_sec: float | None = None


def _extract_text_from_content(content: str | list[Any] | dict[str, Any]) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(content, dict):
        text = content.get("text") or content.get("content") or ""
        return text.strip() if isinstance(text, str) else ""
    return ""


def extract_latest_user_text(request: OriginalUIChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            text = _extract_text_from_content(message.content)
            if text:
                return text
    raise ValueError("No user message with text content found.")


def extract_query_context(user_text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract the original UI's leading ``[Context: JSON]`` envelope."""
    leading_trimmed = user_text.lstrip()
    if not leading_trimmed.startswith(_QUERY_CONTEXT_PREFIX):
        return user_text, []

    payload_text = leading_trimmed[len(_QUERY_CONTEXT_PREFIX) :].lstrip()
    try:
        payload, end = json.JSONDecoder().raw_decode(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid chat context payload.") from exc

    suffix = payload_text[end:].lstrip()
    if not suffix.startswith("]"):
        raise ValueError("Invalid chat context envelope.")
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("Chat context must be a list of objects.")

    question = suffix[1:].strip()
    if not question and payload:
        question = "Describe the selected video clip and answer using visible evidence."
    return question, [dict(item) for item in payload]


def _context_string(item: dict[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def resolve_selected_recorded_video_context(
    context_items: list[dict[str, Any]],
    *,
    repository: Any | None = None,
    asset_store: Any | None = None,
) -> SelectedRecordedVideoContext | None:
    """Resolve client identity through SQLite and the controlled asset store."""
    candidates = [
        item
        for item in context_items
        if _context_string(item, "assetId", "asset_id")
        and _context_string(item, "mediaType", "media_type") in {"", "recorded-video-segment"}
    ]
    if not candidates:
        return None

    asset_ids = {_context_string(item, "assetId", "asset_id") for item in candidates}
    if len(asset_ids) != 1:
        raise ValueError("Select exactly one recorded video before asking a video question.")

    item = candidates[0]
    asset_id = next(iter(asset_ids))
    segment_id = _context_string(item, "segmentId", "segment_id")

    if repository is None or asset_store is None:
        from vsa_agent.config import get_config
        from vsa_agent.recorded_video.assets import LocalAssetStore
        from vsa_agent.recorded_video.repository import JobRepository

        data_root = get_config().recorded_video.data_root
        repository = repository or JobRepository(data_root / "recorded-video.sqlite3")
        asset_store = asset_store or LocalAssetStore(data_root)

    await repository.initialize()
    try:
        asset = await repository.get_asset(asset_id)
    except KeyError as exc:
        raise ValueError("Selected recorded video no longer exists.") from exc

    from vsa_agent.recorded_video.models import AssetStatus

    if asset.status is not AssetStatus.READY or asset.deleted_at is not None:
        raise ValueError("Selected recorded video is not ready for understanding.")

    selected_segment = None
    if segment_id:
        segments = await repository.list_segments(asset_id)
        selected_segment = next((segment for segment in segments if segment.segment_id == segment_id), None)
        if selected_segment is None:
            raise ValueError("Selected recorded-video segment no longer exists.")

    try:
        video_path = await asset_store.resolve_source_path(asset)
    except FileNotFoundError as exc:
        raise ValueError("Selected recorded-video source file is unavailable.") from exc

    resolved = SelectedRecordedVideoContext(
        asset_id=asset.asset_id,
        segment_id=selected_segment.segment_id if selected_segment is not None else "",
        video_name=asset.display_filename,
        video_path=video_path,
        start_offset_sec=(selected_segment.start_offset_ms / 1000) if selected_segment is not None else None,
        end_offset_sec=(selected_segment.end_offset_ms / 1000) if selected_segment is not None else None,
    )
    logger.info(
        "original_ui.chat.context.resolved asset_id=%s segment_id=%s video_name=%r",
        resolved.asset_id,
        resolved.segment_id,
        resolved.video_name,
    )
    return resolved


def _format_offset(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def inject_selected_recorded_video_context(
    user_text: str,
    selected: SelectedRecordedVideoContext,
) -> str:
    """Bind a natural-language question to one server-validated media source."""
    lines = [
        user_text,
        "",
        "Selected recorded video context (server validated):",
        f"asset_id: {selected.asset_id}",
        f"segment_id: {selected.segment_id}",
        f"video_name: {selected.video_name}",
        f"video_path: {selected.video_path}",
    ]
    if selected.start_offset_sec is not None:
        lines.append(f"start_timestamp: {_format_offset(selected.start_offset_sec)}")
    if selected.end_offset_sec is not None:
        lines.append(f"end_timestamp: {_format_offset(selected.end_offset_sec)}")
    lines.append(
        "Use video_understanding with exactly this video_path and time range. "
        "Do not call find_video or list_videos, and do not substitute another video."
    )
    return "\n".join(lines)


def inject_configured_video_context(user_text: str, configured_video_path: str = "") -> str:
    video_path = configured_video_path.strip()
    if not video_path:
        return user_text

    normalized = user_text.lower()
    if "configured video" not in normalized and "default video" not in normalized:
        return user_text
    if video_path in user_text:
        return user_text

    return (
        f"{user_text}\n\n"
        f"Configured video_path: {video_path}\n"
        "Use this video_path directly with video_understanding for the user's request. "
        "Do not call list_videos or ask the user to upload a video."
    )


def _get_configured_video_path() -> str:
    return resolve_runtime_config().runtime.video_path


def _safe_trace_component(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:80] or fallback


def _create_original_ui_trace_dir(
    conversation_id: str,
    user_message_id: str,
    trace_root: str | Path | None,
) -> Path | None:
    root_value = str(trace_root) if trace_root is not None else os.getenv(ORIGINAL_UI_TRACE_ROOT_ENV, "")
    if not root_value.strip():
        return None

    root = Path(root_value)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    conversation = _safe_trace_component(conversation_id, "conversation")
    message = _safe_trace_component(user_message_id, "message")
    trace_dir = root / f"{timestamp}-{conversation}-{message}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "latest.txt").write_text(str(trace_dir), encoding="utf-8")
    return trace_dir


def format_openai_delta(content: str) -> str:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_done() -> str:
    return "data: [DONE]\n\n"


def format_intermediate_data(
    name: str,
    payload: str,
    status: str = "in_progress",
    index: int = 0,
    error: str = "",
) -> str:
    event = {
        "id": f"vsa-agent-step-{index}",
        "status": status,
        "error": error,
        "name": name,
        "payload": payload,
        "parent_id": "vsa-agent",
        "intermediate_parent_id": "vsa-agent",
        "time_stamp": "default",
        "index": index,
    }
    return f"intermediate_data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _format_tool_progress_payload(chunk: AgentMessageChunk) -> str:
    lines = [line for line in chunk.content.splitlines() if line.strip()]
    metadata = chunk.metadata or {}

    additions = []
    if metadata.get("risk_category") and not any(line.startswith("Risk:") for line in lines):
        additions.append(f"Risk: {metadata['risk_category']}")
    if metadata.get("evidence_type") and not any(line.startswith("Evidence type:") for line in lines):
        additions.append(f"Evidence type: {metadata['evidence_type']}")
    if metadata.get("risk_evidence") and not any(line.startswith("Key evidence:") for line in lines):
        additions.append(f"Key evidence: {metadata['risk_evidence']}")
    if metadata.get("frame_count") is not None and not any(line.startswith("Frames:") for line in lines):
        additions.append(f"Frames: {metadata['frame_count']} sampled")
    if metadata.get("raw_artifact_path") and not any(line.startswith("Raw VLM output:") for line in lines):
        additions.append(f"Raw VLM output: {metadata['raw_artifact_path']}")
    if metadata.get("result_artifact_path") and not any(line.startswith("Result JSON:") for line in lines):
        additions.append(f"Result JSON: {metadata['result_artifact_path']}")

    return "\n".join([*lines, *additions])


def format_chunk_for_original_ui(chunk: AgentMessageChunk, index: int) -> list[str]:
    if chunk.type == AgentMessageChunkType.FINAL:
        return [format_openai_delta(chunk.content)]
    if chunk.type == AgentMessageChunkType.THOUGHT:
        return [format_intermediate_data("Thought", chunk.content, index=index)]
    if chunk.type == AgentMessageChunkType.TOOL_CALL:
        return [format_intermediate_data("Tool Call", chunk.content, index=index)]
    if chunk.type == AgentMessageChunkType.TOOL_PROGRESS:
        status = "completed" if chunk.metadata.get("status") == "completed" else "in_progress"
        return [
            format_intermediate_data("Tool Progress", _format_tool_progress_payload(chunk), status=status, index=index)
        ]
    if chunk.type == AgentMessageChunkType.TOOL_RESULT:
        return [format_intermediate_data("Tool Result", chunk.content, status="completed", index=index)]
    if chunk.type == AgentMessageChunkType.ERROR:
        return [format_intermediate_data("Error", chunk.content, status="error", index=index, error=chunk.content)]
    return []


async def build_default_graph_for_original_ui() -> Any:
    from vsa_agent.agents.top_agent import build_graph

    return await build_graph()


async def stream_original_ui_chat(
    request: OriginalUIChatRequest,
    conversation_id: str = "",
    user_message_id: str = "",
    graph_builder: Callable[[], Awaitable[Any]] | None = None,
    configured_video_path: str | None = None,
    trace_root: str | Path | None = None,
    recorded_video_context_resolver: Callable[[list[dict[str, Any]]], Awaitable[SelectedRecordedVideoContext | None]]
    | None = None,
) -> AsyncIterator[str]:
    if graph_builder is None:
        graph_builder = build_default_graph_for_original_ui

    raw_user_text = extract_latest_user_text(request)
    thread_id = conversation_id or "original-ui-chat"
    trace_dir = _create_original_ui_trace_dir(conversation_id, user_message_id, trace_root)
    index = 0
    try:
        question_text, context_items = extract_query_context(raw_user_text)
        context_resolver = recorded_video_context_resolver or resolve_selected_recorded_video_context
        selected_video = await context_resolver(context_items) if context_items else None
        if selected_video is not None:
            user_text = inject_selected_recorded_video_context(question_text, selected_video)
        else:
            if configured_video_path is None:
                configured_video_path = _get_configured_video_path()
            user_text = inject_configured_video_context(question_text, configured_video_path)

        with live_trace_context(
            trace_path=(trace_dir / "trace.jsonl") if trace_dir else None,
            artifact_dir=trace_dir,
        ):
            graph = await graph_builder()
            state = AgentState(current_message=HumanMessage(content=user_text))
            config = RunnableConfig(
                configurable={
                    "thread_id": thread_id,
                    "checkpoint_ns": "original-ui-chat",
                }
            )

            request_payload = {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "message": raw_user_text,
                "resolved_message": user_text,
                "configured_video_path": configured_video_path,
                "query_context": context_items,
                "selected_asset_id": selected_video.asset_id if selected_video else "",
                "selected_segment_id": selected_video.segment_id if selected_video else "",
                "trace_dir": str(trace_dir) if trace_dir else "",
            }
            write_live_json_artifact("request.json", request_payload)
            write_live_trace_event("original_ui.chat.request", request_payload)
            logger.info(
                "original_ui.chat.request conversation_id=%r user_message_id=%r selected_asset_id=%s "
                "selected_segment_id=%s",
                conversation_id,
                user_message_id,
                request_payload["selected_asset_id"],
                request_payload["selected_segment_id"],
            )

            async for chunk in graph.astream(state, config=config, stream_mode="custom"):
                for frame in format_chunk_for_original_ui(chunk, index=index):
                    yield frame
                index += 1
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        with live_trace_context(
            trace_path=(trace_dir / "trace.jsonl") if trace_dir else None,
            artifact_dir=trace_dir,
        ):
            write_live_trace_event(
                "original_ui.chat.error",
                {
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "error": message,
                    "trace_dir": str(trace_dir) if trace_dir else "",
                },
            )
        yield format_intermediate_data("Error", message, status="error", index=index, error=message)
        yield format_openai_delta(f"Error: {message}")
    finally:
        yield format_done()
