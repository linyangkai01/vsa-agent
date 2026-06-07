import logging
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunkType

logger = logging.getLogger(__name__)


class AgentState(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    current_message: str = ''
    final_answer: str = ''
    agent_scratchpad: list[dict] = Field(default_factory=list)
    retry_count: int = 0


async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    from vsa_agent.model_adapter import create_model_adapter

    writer = get_stream_writer()
    adapter = create_model_adapter()

    system_msg = SystemMessage(content='You are an industrial safety video analysis agent.')
    msgs: list = [system_msg]

    for m in state.messages:
        role = m.get('role', 'user')
        content = m.get('content', '')
        if role == 'user':
            msgs.append(HumanMessage(content=content))
        elif role == 'assistant':
            msgs.append(AIMessage(content=content))

    msgs.append(HumanMessage(content=state.current_message))

    for tm in state.agent_scratchpad:
        if tm.get('role') == 'tool':
            msgs.append(ToolMessage(content=tm['content'], tool_call_id=tm.get('tool_call_id', '')))

    writer({'type': AgentMessageChunkType.THOUGHT.value, 'content': 'Agent thinking...'})
    response = await adapter.invoke(msgs)
    content = response.content if hasattr(response, 'content') else str(response)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        state.agent_scratchpad.append({'role': 'assistant', 'content': content, 'tool_calls': [
            {'name': tc['name'], 'args': tc['args'], 'id': tc['id']}
            for tc in response.tool_calls
        ]})
        state.messages.append({'role': 'assistant', 'content': content})
    else:
        state.final_answer = content
        state.messages.append({'role': 'assistant', 'content': content})

    return state


async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    from vsa_agent.registry import ToolRegistry

    writer = get_stream_writer()
    last = state.agent_scratchpad[-1] if state.agent_scratchpad else None

    if not last or 'tool_calls' not in last:
        return state

    tools = ToolRegistry.get_all()
    for tc in last['tool_calls']:
        tool_name = tc['name']
        writer({'type': AgentMessageChunkType.TOOL_CALL.value, 'content': f'Calling: {tool_name}'})

        if tool_name in tools:
            try:
                result = await tools[tool_name](**tc['args'])
                state.agent_scratchpad.append({'role': 'tool', 'content': str(result), 'tool_call_id': tc['id']})
            except Exception as e:
                state.agent_scratchpad.append({'role': 'tool', 'content': f'Error: {e}', 'tool_call_id': tc['id']})

    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    writer = get_stream_writer()
    writer({'type': AgentMessageChunkType.FINAL.value, 'content': state.final_answer})
    state.agent_scratchpad = []
    return state


def decide_next(state: AgentState) -> str:
    last = state.agent_scratchpad[-1] if state.agent_scratchpad else None
    if last and 'tool_calls' in last:
        return AgentDecision.CALL_TOOL.value
    return AgentDecision.RESPOND.value
