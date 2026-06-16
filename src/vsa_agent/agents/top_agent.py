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

logger = logging.getLogger(__name__)

_INJECTION_PARAMS = {"store", "embed_store", "attr_store", "model_adapter",
                     "kwargs", "args", "kwds"}

_MAX_TOOL_RESULT_CHARS = 800


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
    return result[:_MAX_TOOL_RESULT_CHARS] + "..."


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

    writer(AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content="Analyzing..."))

    adapter = create_model_adapter()
    lc_tools = _build_langchain_tools()
    if lc_tools:
        adapter.bind_tools(lc_tools)

    response = await adapter.invoke(prompt)
    state.iteration_count += 1

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
        writer(AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content=f"Calling: {name}"))

        try:
            result = await tools[name](**args) if name in tools else f"Tool not found: {name}"
        except Exception as e:
            result = f"Error: {e}"

        result_str = str(result)
        truncated = _truncate_result(name, result_str)
        state.agent_scratchpad.append(ToolMessage(content=truncated, tool_call_id=call_id))

    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    writer = get_stream_writer()
    writer(AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=state.final_answer))

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
    graph.add_edge("tool", "agent")
    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=InMemorySaver())
    logger.info("Agent DAG compiled successfully")
    return compiled
