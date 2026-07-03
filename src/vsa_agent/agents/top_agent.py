import logging
import inspect
import json
from typing import get_type_hints

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunk, AgentMessageChunkType, AgentState
from vsa_agent.config import get_config
from vsa_agent.observability.live_trace import write_live_text_artifact
from vsa_agent.observability.live_trace import write_live_trace_event

logger = logging.getLogger(__name__)

_INJECTION_PARAMS = {"store", "embed_store", "attr_store", "model_adapter",
                     "kwargs", "args", "kwds"}

_MAX_TOOL_RESULT_CHARS = 800
_MAX_VIDEO_TOOL_RESULT_CHARS = 2000
_VIDEO_RESULT_TOOL_NAMES = {"video_understanding", "lvs_video_understanding"}
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
_SENSITIVE_ARG_MARKERS = ("key", "token", "secret", "password", "credential")
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
    if name == "frame_extract":
        try:
            data = json.loads(result)
            if "frames" in data:
                frame_count = len(data["frames"])
                data["frames"] = f"[{frame_count} base64 frames - use frame_key to access]"
                return json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _truncate_result(name: str, result: str) -> str:
    result = _sanitize_tool_result(name, result)
    if len(result) <= _MAX_TOOL_RESULT_CHARS:
        return result
    if name in _VIDEO_RESULT_TOOL_NAMES:
        return _truncate_video_result(result)
    return result[:_MAX_TOOL_RESULT_CHARS] + "..."


def _truncate_video_result(result: str) -> str:
    """Keep enough long-video evidence for the LLM to answer without rerunning it."""
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    keyword_lines = _select_video_keyword_lines(lines)

    head = _truncate_text(result, 420)
    tail = _truncate_text(result[-420:], 420)
    parts = [
        f"[video tool result abridged from {len(result)} chars; full result is saved in the live trace artifact]",
        "[BEGINNING]",
        head,
    ]
    if keyword_lines:
        parts.extend(["[KEY SAFETY/RISK EVIDENCE]", *_fit_lines(keyword_lines, 900)])
    parts.extend(["[ENDING]", tail])

    summary = "\n".join(parts)
    return _truncate_text(summary, _MAX_VIDEO_TOOL_RESULT_CHARS)


def _select_video_keyword_lines(lines: list[str]) -> list[str]:
    selected = []
    seen = set()

    def add_matches(keywords: tuple[str, ...]) -> None:
        for line in lines:
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
    if any(marker in lowered for marker in _SENSITIVE_ARG_MARKERS):
        return "<redacted>"
    if isinstance(value, str):
        return _truncate_text(value, 300)
    if isinstance(value, (int, float, bool)) or value is None:
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
    if len(preview) > 1200:
        preview = _truncate_text(preview, 1200)
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
    prompt: list[BaseMessage] = [SystemMessage(content=cfg.prompts.default_system)]

    if state.conversation_history:
        prompt.extend(state.conversation_history)
    if state.current_message:
        prompt.append(state.current_message)
    if state.agent_scratchpad:
        prompt.extend(state.agent_scratchpad)

    adapter = create_model_adapter()
    lc_tools = _build_langchain_tools()
    if lc_tools:
        adapter.bind_tools(lc_tools)

    writer(
        AgentMessageChunk(
            type=AgentMessageChunkType.THOUGHT,
            content=(
                f"Analyzing user request (LLM iteration {state.iteration_count + 1}; "
                f"{len(lc_tools)} tools available)."
            ),
            metadata={"iteration": state.iteration_count + 1, "tool_count": len(lc_tools)},
        )
    )

    write_live_trace_event(
        "top_agent.agent.request",
        {
            "iteration": state.iteration_count + 1,
            "messages": prompt,
            "tool_count": len(lc_tools),
        },
    )
    response = await adapter.invoke(prompt)
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
        name, args, call_id = tc["name"], tc["args"], tc["id"]
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
            {"tool_name": name, "tool_args": args, "tool_call_id": call_id},
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
        truncated = _truncate_result(name, result_str)
        artifact_path = write_live_text_artifact(
            f"tool-results/{call_id}-{name}.txt",
            result_str,
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
        state.agent_scratchpad.append(ToolMessage(content=truncated, tool_call_id=call_id))

    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    writer = get_stream_writer()
    writer(AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=state.final_answer))
    write_live_trace_event(
        "top_agent.final",
        {"final_answer": state.final_answer},
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
    graph.add_conditional_edges("agent", decide_next, {
        AgentDecision.CALL_TOOL.value: "tool",
        AgentDecision.RESPOND.value: "finalize",
    })
    graph.add_conditional_edges("tool", decide_after_tool, {
        AgentDecision.CALL_TOOL.value: "agent",
        AgentDecision.RESPOND.value: "finalize",
    })
    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=InMemorySaver())
    logger.info("Agent DAG compiled successfully")
    return compiled
