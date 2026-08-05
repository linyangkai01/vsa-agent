import inspect
import json
import logging
import uuid
from typing import get_type_hints

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field, create_model

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunk, AgentMessageChunkType, AgentState
from vsa_agent.config import get_config
from vsa_agent.observability.live_trace import write_live_text_artifact, write_live_trace_event
from vsa_agent.privacy.gateway import RemoteProviderGateway
from vsa_agent.privacy.schemas import PrivacyPolicyError, RemoteSafeSearchQuery, opaque_result_ref

logger = logging.getLogger(__name__)

_INJECTION_PARAMS = {"store", "embed_store", "attr_store", "model_adapter", "kwargs", "args", "kwds"}

_MAX_TOOL_RESULT_CHARS = 800
_MAX_VIDEO_TOOL_RESULT_CHARS = 3200
_VIDEO_RESULT_TOOL_NAMES = {"video_understanding", "lvs_video_understanding"}
_SELECTED_VIDEO_TOOL_NAME = "video_understanding"
_LOCAL_METADATA_TOOL_NAMES = {
    "attribute_search",
    "critic_agent",
    "embed_search",
    "find_video",
    "find_video_by_name",
    "fov_counts_with_chart",
    "frame_extract",
    "geolocation",
    "incidents",
    "lvs_video_understanding",
    "multi_incident_formatter",
    "multi_report_agent",
    "report_agent",
    "report_gen",
    "search",
    "search_agent",
    "template_report_gen",
    "video_caption",
    "video_detailed_caption",
    "video_frame_timestamp",
    "video_report_gen",
    "video_skim_caption",
    "video_understanding",
    "vss_summarize",
}
_PRIMARY_VIDEO_RESULT_KEYWORDS = (
    "risk",
    "hazard",
    "unsafe",
    "safety",
    "ppe",
    "fall",
    "harness",
    "severity",
    "violation",
    "dangerous",
    "missing",
    "lack",
    "absence",
)
_SECONDARY_VIDEO_RESULT_KEYWORDS = (
    "scaffold",
    "guardrail",
    "toe board",
    "glove",
    "vehicle",
    "electrical",
    "fire",
)
_VIDEO_RISK_CATEGORIES = (
    (
        "Eye / face protection",
        ("eye protection", "safety goggles", "face shield", "flying sparks", "flying debris"),
    ),
    (
        "PPE / visibility",
        (
            "ppe",
            "hard hat",
            "safety vest",
            "high-visibility",
            "eye protection",
            "goggles",
            "face shield",
            "glove",
            "ear protection",
            "respiratory",
            "mask",
        ),
    ),
    (
        "Fire / hot work",
        ("fire", "spark", "welding", "grinding", "angle grinder", "hot work", "flammable"),
    ),
    (
        "Slip / trip / housekeeping",
        ("slip", "trip", "wet", "muddy", "debris", "clutter", "uneven", "gravel", "dust"),
    ),
    (
        "Fall / work at height",
        ("fall", "height", "scaffold", "rebar framework", "guardrail", "toe board", "harness", "lanyard"),
    ),
    (
        "Heavy equipment / struck-by",
        ("crane", "vehicle", "excavator", "hydraulic breaker", "heavy machinery", "struck", "barrier"),
    ),
    (
        "Machine guarding / pinch points",
        ("machine", "bending", "moving parts", "guard", "entanglement", "pinch"),
    ),
    (
        "Chemical / respiratory exposure",
        ("chemical", "fume", "smoke", "respiratory", "dust", "ventilation", "inhalation"),
    ),
)
_SENSITIVE_ARG_MARKERS = ("key", "token", "secret", "password", "credential")
_LOCAL_ONLY_ARG_NAMES = {
    "asset_id",
    "end_timestamp",
    "segment_id",
    "sensor_id",
    "start_timestamp",
    "video_path",
}
_UNRECOVERABLE_TOOL_ERROR_MARKERS = (
    "AllocationQuota.FreeTierOnly",
    "free quota has been exhausted",
    "AuthenticationError",
    "PermissionDeniedError",
    "invalid_api_key",
    "Incorrect API key",
    "api_key client option must be set",
)
_HIDDEN_LANGCHAIN_TOOLS = {
    # report_agent owns this lower-level formatter. Exposing it directly causes
    # models to pass ReportSection fields as unsupported top-level kwargs.
    "video_report_gen",
}


def _build_tool_schema(fn) -> type[BaseModel] | None:
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    fields = {}
    for pname, param in sig.parameters.items():
        if pname in _INJECTION_PARAMS:
            continue
        if pname == "return":
            continue
        if pname.startswith("_"):
            continue
        ptype = hints.get(pname, str)
        default = param.default if param.default is not inspect.Parameter.empty else ...
        has_default = default is not ...
        fields[pname] = (ptype, Field(default=default if has_default else ..., description=f"Parameter {pname}"))
    if not fields:
        return None
    return create_model(f"{fn.__name__}_args", **fields)


def _build_langchain_tools() -> list[StructuredTool]:
    from vsa_agent.registry import ToolRegistry

    tools = ToolRegistry.get_all()
    lc_tools = []
    for name, fn in tools.items():
        if name in _HIDDEN_LANGCHAIN_TOOLS:
            continue
        schema = _build_tool_schema(fn)
        description = getattr(fn, "_tool_description", "") or fn.__doc__ or ""

        def _make_coro(f):
            async def _coroutine(**kw):
                return await f(**kw)

            return _coroutine

        t = StructuredTool(
            name=name,
            description=description,
            args_schema=schema,
            coroutine=_make_coro(fn),
        )
        lc_tools.append(t)
    return lc_tools


def _sanitize_tool_result(name: str, result: str) -> str:
    if name in _LOCAL_METADATA_TOOL_NAMES:
        return "Local media operation completed. Its details are available only in the local UI."
    return result


def _truncate_result(name: str, result: str) -> str:
    if len(result) <= _MAX_TOOL_RESULT_CHARS:
        return result
    if name in _VIDEO_RESULT_TOOL_NAMES:
        return _truncate_video_result(result)
    return result[:_MAX_TOOL_RESULT_CHARS] + "..."


def _truncate_video_result(result: str) -> str:
    """Keep enough long-video evidence for the LLM to answer without rerunning it."""
    if result.startswith("Risk digest by chunk:") and "Only state direct observations as facts." in result:
        return _truncate_text(result, _MAX_VIDEO_TOOL_RESULT_CHARS)

    head = _truncate_text(result, 420)
    tail = _truncate_text(result[-420:], 420)
    parts = [
        f"[video tool result abridged from {len(result)} chars; full result is saved in the live trace artifact]",
        "[BEGINNING]",
        head,
    ]
    digest_lines = _build_video_risk_digest(result)
    if digest_lines:
        parts.extend(["[RISK DIGEST BY CATEGORY]", *_fit_lines(digest_lines, 1850)])
    parts.extend(["[ENDING]", tail])

    summary = "\n".join(parts)
    return _truncate_text(summary, _MAX_VIDEO_TOOL_RESULT_CHARS)


def _build_video_risk_digest(result: str) -> list[str]:
    sections = _split_video_result_sections(result)
    if not sections:
        return []

    digest = []
    used_sections: set[int] = set()
    for category, keywords in _VIDEO_RISK_CATEGORIES:
        matches = _select_category_evidence(sections, keywords, used_sections)
        for index, evidence in matches:
            used_sections.add(index)
            digest.append(f"- {category}: {evidence}")
            break

    if len(digest) < 6:
        fallback_lines = _select_video_keyword_lines([section for _, section in sections], used_sections)
        digest.extend(f"- Additional evidence: {line}" for line in fallback_lines[: 6 - len(digest)])

    if digest:
        digest.insert(0, f"Coverage: selected {len(digest)} risk snippets from {len(sections)} observed sections.")
    return digest


def _split_video_result_sections(result: str) -> list[tuple[int, str]]:
    raw_sections = [section.strip() for section in result.split("\n\n") if section.strip()]
    if len(raw_sections) <= 1:
        raw_sections = [line.strip() for line in result.splitlines() if line.strip()]
    return [(index, section) for index, section in enumerate(raw_sections)]


def _select_category_evidence(
    sections: list[tuple[int, str]],
    keywords: tuple[str, ...],
    used_sections: set[int],
) -> list[tuple[int, str]]:
    preferred = []
    fallback = []
    for index, section in sections:
        lowered = section.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        evidence = _truncate_text(" ".join(section.split()), 260)
        if index in used_sections:
            fallback.append((index, evidence))
        else:
            preferred.append((index, evidence))
    return preferred or fallback


def _select_video_keyword_lines(lines: list[str], used_indexes: set[int] | None = None) -> list[str]:
    used_indexes = used_indexes or set()
    selected = []
    seen = set()

    def add_matches(keywords: tuple[str, ...]) -> None:
        for index, line in enumerate(lines):
            if index in used_indexes:
                continue
            lowered = line.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            if line in seen:
                continue
            seen.add(line)
            selected.append(_truncate_text(line, 220))
            if len(selected) >= 8:
                return

    add_matches(_PRIMARY_VIDEO_RESULT_KEYWORDS)
    if len(selected) < 8:
        add_matches(_SECONDARY_VIDEO_RESULT_KEYWORDS)
    return selected


def _fit_lines(lines: list[str], max_chars: int) -> list[str]:
    fitted = []
    used = 0
    for line in lines:
        remaining = max_chars - used
        if remaining <= 0:
            break
        clipped = _truncate_text(line, min(len(line), remaining))
        fitted.append(clipped)
        used += len(clipped) + 1
    return fitted


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return "." * max_chars
    return value[: max_chars - 3].rstrip() + "..."


def _is_unrecoverable_tool_error(result: str) -> bool:
    if not result.lower().lstrip().startswith("error:"):
        return False
    return any(marker in result for marker in _UNRECOVERABLE_TOOL_ERROR_MARKERS)


def _format_unrecoverable_tool_error_answer(tool_name: str, result: str) -> str:
    return (
        f"{tool_name} failed with an unrecoverable model-service error.\n\n"
        f"{_truncate_result(tool_name, result)}\n\n"
        "The agent stopped instead of trying fallback tools, because this class of error "
        "usually requires changing model-service quota, credentials, or runtime profile."
    )


def _redact_tool_arg(name: str, value) -> str:
    lowered = name.lower()
    if lowered in _LOCAL_ONLY_ARG_NAMES or any(marker in lowered for marker in _SENSITIVE_ARG_MARKERS):
        return "<redacted>"
    if isinstance(value, str):
        return _truncate_text(value, 300)
    if isinstance(value, int | float | bool) or value is None:
        return str(value)
    try:
        return _truncate_text(json.dumps(value, ensure_ascii=False, default=str), 300)
    except TypeError:
        return _truncate_text(str(value), 300)


def _summarize_tool_args(args: dict) -> dict[str, str]:
    summarized = {}
    for key in sorted(args):
        summarized[key] = _redact_tool_arg(key, args[key])
    return summarized


def _format_tool_call_step(name: str, args: dict) -> str:
    lines = [f"Calling: {name}"]
    summarized_args = _summarize_tool_args(args)
    if summarized_args:
        lines.append("Inputs:")
        for key, value in summarized_args.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _format_tool_result_step(
    name: str,
    result: str,
    artifact_path: str,
    *,
    cached: bool = False,
) -> str:
    preview = _truncate_result(name, result)
    if len(preview) > 1800:
        preview = _truncate_text(preview, 1800)
    status = "Reused cached result" if cached else "Completed"
    lines = [
        f"{status}: {name}",
        f"Result length: {len(result)} chars",
    ]
    if artifact_path:
        lines.append(f"Full result: {artifact_path}")
    if preview:
        lines.extend(["Selected preview:", preview])
    return "\n".join(lines)


def _tool_cache_key(name: str, args: dict) -> str:
    try:
        args_text = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        args_text = str(sorted(args.items()))
    return f"{name}:{args_text}"


def _normalize_tool_args(state: AgentState, name: str, args: dict) -> dict:
    """Fill model-omitted arguments that are already present in agent state."""
    normalized = dict(args)
    if name not in _VIDEO_RESULT_TOOL_NAMES:
        return normalized

    query = normalized.get("query")
    if not isinstance(query, str) or not query.strip():
        current_content = getattr(state.current_message, "content", "")
        if isinstance(current_content, str) and current_content.strip():
            normalized["query"] = current_content.strip()
    for key in ("video_path", "sensor_id", "start_timestamp", "end_timestamp"):
        value = state.local_video_context.get(key)
        if value is not None and value != "":
            normalized[key] = value
    return normalized


def _route_selected_video_response(response: object, query: str) -> tuple[AIMessage, str]:
    """Guarantee one local video-analysis call for server-validated context."""
    if (
        isinstance(response, AIMessage)
        and len(response.tool_calls) == 1
        and response.tool_calls[0].get("name") == _SELECTED_VIDEO_TOOL_NAME
    ):
        return response, "model_confirmed"

    return (
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": _SELECTED_VIDEO_TOOL_NAME,
                    "args": {"query": query},
                    "id": f"selected-video-{uuid.uuid4().hex}",
                }
            ],
        ),
        "runtime_enforced",
    )


def _find_cached_tool_result(state: AgentState, name: str, args: dict) -> str | None:
    target_key = _tool_cache_key(name, args)
    result_by_call_id = {
        getattr(message, "tool_call_id", ""): str(message.content)
        for message in state.agent_scratchpad[:-1]
        if isinstance(message, ToolMessage)
    }
    for message in state.agent_scratchpad[:-1]:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls:
            if _tool_cache_key(tool_call["name"], tool_call["args"]) != target_key:
                continue
            cached = result_by_call_id.get(tool_call["id"])
            if cached:
                return cached
    return None


async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    from vsa_agent.model_adapter import create_model_adapter

    writer = get_stream_writer()
    logger.debug("Starting agent node")

    cfg = get_config()
    current_content = getattr(state.current_message, "content", "")
    if not isinstance(current_content, str) or not current_content.strip():
        state.final_answer = "The request is empty."
        return state
    try:
        safe_query = RemoteSafeSearchQuery(query=current_content)
    except (PrivacyPolicyError, ValueError):
        state.final_answer = (
            "The request contains local identifiers or other sensitive details. "
            "Use the local search controls, or rewrite it without paths, camera IDs, "
            "absolute times, locations, or personal identifiers."
        )
        return state

    adapter = create_model_adapter()
    lc_tools = _build_langchain_tools()
    has_selected_video = state.selected_recorded_video
    if has_selected_video:
        lc_tools = [tool for tool in lc_tools if tool.name == _SELECTED_VIDEO_TOOL_NAME]
    if lc_tools:
        adapter.bind_tools(lc_tools)

    writer(
        AgentMessageChunk(
            type=AgentMessageChunkType.THOUGHT,
            content=(
                f"Analyzing user request (LLM iteration {state.iteration_count + 1}; {len(lc_tools)} tools available)."
            ),
            metadata={"iteration": state.iteration_count + 1, "tool_count": len(lc_tools)},
        )
    )

    write_live_trace_event(
        "top_agent.agent.request",
        {
            "iteration": state.iteration_count + 1,
            "query_sha256": safe_query.query_sha256,
            "query_length": len(safe_query.query),
            "tool_count": len(lc_tools),
        },
    )
    system_prompt = cfg.prompts.default_system
    if has_selected_video:
        system_prompt += (
            "\n\nRUNTIME CONTEXT:\n"
            "A server-validated recorded-video clip is selected. Call video_understanding exactly once. "
            "The runtime injects its private path and time range; do not call discovery tools."
        )
    response = await RemoteProviderGateway().invoke_agent(
        safe_query,
        adapter,
        system_prompt=system_prompt,
    )
    if has_selected_video:
        response, route_source = _route_selected_video_response(response, safe_query.query)
        write_live_trace_event(
            "top_agent.selected_video.route",
            {
                "tool_name": _SELECTED_VIDEO_TOOL_NAME,
                "tool_count": 1,
                "has_tool_calls": True,
                "source_type": route_source,
            },
        )
    state.iteration_count += 1
    write_live_trace_event(
        "top_agent.agent.response",
        {
            "iteration": state.iteration_count,
            "response": response,
            "has_tool_calls": bool(isinstance(response, AIMessage) and response.tool_calls),
        },
    )

    if isinstance(response, AIMessage) and response.tool_calls:
        state.agent_scratchpad.append(response)
    else:
        content = response.content if isinstance(response, AIMessage) else str(response)
        state.final_answer = content

    return state


async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    from vsa_agent.registry import ToolRegistry

    writer = get_stream_writer()
    logger.debug("Starting tool node")
    tools = ToolRegistry.get_all()

    last_msg = state.agent_scratchpad[-1] if state.agent_scratchpad else None
    if not last_msg or not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return state

    for tc in last_msg.tool_calls:
        name, call_id = tc["name"], tc["id"]
        args = _normalize_tool_args(state, name, tc["args"])
        tc["args"] = args
        writer(
            AgentMessageChunk(
                type=AgentMessageChunkType.TOOL_CALL,
                content=_format_tool_call_step(name, args),
                metadata={
                    "tool_name": name,
                    "tool_args": _summarize_tool_args(args),
                    "tool_call_id": call_id,
                },
            )
        )
        write_live_trace_event(
            "top_agent.tool.call",
            {"tool_name": name, "tool_args": _summarize_tool_args(args), "tool_call_id": call_id},
        )

        cached_result = _find_cached_tool_result(state, name, args)
        if cached_result is not None:
            state.agent_scratchpad.append(ToolMessage(content=cached_result, tool_call_id=call_id))
            writer(
                AgentMessageChunk(
                    type=AgentMessageChunkType.TOOL_RESULT,
                    content=_format_tool_result_step(name, cached_result, "", cached=True),
                    metadata={
                        "tool_name": name,
                        "tool_call_id": call_id,
                        "cached": True,
                        "result_length": len(cached_result),
                    },
                )
            )
            write_live_trace_event(
                "top_agent.tool.cached_result",
                {
                    "tool_name": name,
                    "tool_call_id": call_id,
                    "cached_result_length": len(cached_result),
                    "cached_result_preview": _truncate_text(cached_result, _MAX_TOOL_RESULT_CHARS),
                },
            )
            continue

        try:
            result = await tools[name](**args) if name in tools else f"Tool not found: {name}"
        except Exception as e:
            result = f"Error: {e}"

        result_str = str(result)
        remote_safe_result = _sanitize_tool_result(name, result_str)
        truncated = _truncate_result(name, remote_safe_result)
        artifact_path = (
            None
            if name in _LOCAL_METADATA_TOOL_NAMES
            else write_live_text_artifact(f"tool-results/{call_id}-{name}.txt", result_str)
        )
        write_live_trace_event(
            "top_agent.tool.result",
            {
                "tool_name": name,
                "tool_call_id": call_id,
                "result_length": len(result_str),
                "result_preview": truncated,
                "artifact_path": artifact_path,
            },
        )
        if _is_unrecoverable_tool_error(result_str):
            state.final_answer = _format_unrecoverable_tool_error_answer(name, result_str)
            writer(AgentMessageChunk(type=AgentMessageChunkType.ERROR, content=state.final_answer))
            write_live_trace_event(
                "top_agent.tool.unrecoverable_error",
                {
                    "tool_name": name,
                    "tool_call_id": call_id,
                    "result_preview": truncated,
                    "final_answer": state.final_answer,
                },
            )
            return state
        writer(
            AgentMessageChunk(
                type=AgentMessageChunkType.TOOL_RESULT,
                content=_format_tool_result_step(name, result_str, artifact_path),
                metadata={
                    "tool_name": name,
                    "tool_call_id": call_id,
                    "cached": False,
                    "result_length": len(result_str),
                    "artifact_path": artifact_path,
                },
            )
        )
        state.agent_scratchpad.append(
            ToolMessage(
                content=(
                    f"{truncated} Local result reference: {opaque_result_ref(name, call_id)}."
                    if name in _LOCAL_METADATA_TOOL_NAMES
                    else truncated
                ),
                tool_call_id=call_id,
            )
        )
        if name in _LOCAL_METADATA_TOOL_NAMES:
            state.final_answer = result_str

    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    writer = get_stream_writer()
    writer(AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=state.final_answer))
    write_live_trace_event(
        "top_agent.final",
        {"final_answer_length": len(state.final_answer)},
    )

    if state.current_message:
        state.conversation_history.append(HumanMessage(content=state.current_message.content))
        state.conversation_history.append(AIMessage(content=state.final_answer))

    logger.debug("Finalize node: conversation complete")
    return state


def decide_next(state: AgentState) -> str:
    if not state.agent_scratchpad:
        return AgentDecision.RESPOND.value
    last = state.agent_scratchpad[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return AgentDecision.CALL_TOOL.value
    return AgentDecision.RESPOND.value


def decide_after_tool(state: AgentState) -> str:
    if state.final_answer:
        return AgentDecision.RESPOND.value
    return AgentDecision.CALL_TOOL.value


async def build_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        decide_next,
        {
            AgentDecision.CALL_TOOL.value: "tool",
            AgentDecision.RESPOND.value: "finalize",
        },
    )
    graph.add_conditional_edges(
        "tool",
        decide_after_tool,
        {
            AgentDecision.CALL_TOOL.value: "agent",
            AgentDecision.RESPOND.value: "finalize",
        },
    )
    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=InMemorySaver())
    logger.info("Agent DAG compiled successfully")
    return compiled
