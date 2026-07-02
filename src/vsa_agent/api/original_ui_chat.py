from __future__ import annotations

import json
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.agents.data_models import AgentState
from vsa_agent.config import resolve_runtime_config
from vsa_agent.observability.live_trace import write_live_trace_event


class OriginalUIChatMessage(BaseModel):
    role: str
    content: str | list[Any] | dict[str, Any] = ""


class OriginalUIChatRequest(BaseModel):
    messages: list[OriginalUIChatMessage] = Field(default_factory=list)


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


def format_chunk_for_original_ui(chunk: AgentMessageChunk, index: int) -> list[str]:
    if chunk.type == AgentMessageChunkType.FINAL:
        return [format_openai_delta(chunk.content)]
    if chunk.type == AgentMessageChunkType.THOUGHT:
        return [format_intermediate_data("Thought", chunk.content, index=index)]
    if chunk.type == AgentMessageChunkType.TOOL_CALL:
        return [format_intermediate_data("Tool Call", chunk.content, index=index)]
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
) -> AsyncIterator[str]:
    if graph_builder is None:
        graph_builder = build_default_graph_for_original_ui

    raw_user_text = extract_latest_user_text(request)
    if configured_video_path is None:
        configured_video_path = _get_configured_video_path()
    user_text = inject_configured_video_context(raw_user_text, configured_video_path)
    thread_id = conversation_id or "original-ui-chat"
    index = 0
    try:
        graph = await graph_builder()
        state = AgentState(current_message=HumanMessage(content=user_text))
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id,
                "checkpoint_ns": "original-ui-chat",
            }
        )

        write_live_trace_event(
            "original_ui.chat.request",
            {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "message": raw_user_text,
                "resolved_message": user_text,
                "configured_video_path": configured_video_path,
            },
        )

        async for chunk in graph.astream(state, config=config, stream_mode="custom"):
            for frame in format_chunk_for_original_ui(chunk, index=index):
                yield frame
            index += 1
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        write_live_trace_event(
            "original_ui.chat.error",
            {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "error": message,
            },
        )
        yield format_intermediate_data("Error", message, status="error", index=index, error=message)
        yield format_openai_delta(f"Error: {message}")
    finally:
        yield format_done()
