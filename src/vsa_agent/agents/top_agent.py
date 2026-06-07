import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunk, AgentMessageChunkType, AgentState
from vsa_agent.config import get_config

logger = logging.getLogger(__name__)


# ===== Nodes =====


async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Main reasoning node — invoke the LLM and decide next action."""
    from vsa_agent.model_adapter import create_model_adapter

    writer = get_stream_writer()
    logger.debug('Starting agent node')

    # Build prompt in the original pattern:
    # system + conversation_history + current_message + agent_scratchpad
    cfg = get_config()
    prompt: list[BaseMessage] = [SystemMessage(content=cfg.prompts.default_system)]

    if state.conversation_history:
        prompt.extend(state.conversation_history)

    if state.current_message:
        prompt.append(state.current_message)

    if state.agent_scratchpad:
        prompt.extend(state.agent_scratchpad)

    writer(AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content='Analyzing...'))

    response = await create_model_adapter().invoke(prompt)
    state.iteration_count += 1

    if isinstance(response, AIMessage) and response.tool_calls:
        state.agent_scratchpad.append(response)
    else:
        content = response.content if isinstance(response, AIMessage) else str(response)
        state.final_answer = content

    return state


async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Execute pending tool calls and record results in scratchpad."""
    from vsa_agent.registry import ToolRegistry

    writer = get_stream_writer()
    logger.debug('Starting tool node')
    tools = ToolRegistry.get_all()

    last_msg = state.agent_scratchpad[-1] if state.agent_scratchpad else None
    if not last_msg or not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return state

    for tc in last_msg.tool_calls:
        name, args, call_id = tc['name'], tc['args'], tc['id']
        writer(AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content=f'Calling: {name}'))

        try:
            result = await tools[name](**args) if name in tools else f'Tool not found: {name}'
        except Exception as e:
            result = f'Error: {e}'

        state.agent_scratchpad.append(ToolMessage(content=str(result), tool_call_id=call_id))

    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Emit final answer and record the turn in conversation history."""
    writer = get_stream_writer()
    writer(AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=state.final_answer))

    if state.current_message:
        state.conversation_history.append(HumanMessage(content=state.current_message.content))
        state.conversation_history.append(AIMessage(content=state.final_answer))

    state.agent_scratchpad = []
    logger.debug('Finalize node: conversation complete')
    return state


# ===== Routing =====


def decide_next(state: AgentState) -> str:
    """Conditional edge: route agent_node to tool or finalize."""
    if not state.agent_scratchpad:
        return AgentDecision.RESPOND.value
    last = state.agent_scratchpad[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return AgentDecision.CALL_TOOL.value
    return AgentDecision.RESPOND.value


# ===== Graph Builder =====


async def build_graph() -> CompiledStateGraph:
    """Build and compile the top agent DAG."""
    graph = StateGraph(AgentState)
    graph.add_node('agent', agent_node)
    graph.add_node('tool', tool_node)
    graph.add_node('finalize', finalize_node)

    graph.set_entry_point('agent')
    graph.add_conditional_edges('agent', decide_next, {
        AgentDecision.CALL_TOOL.value: 'tool',
        AgentDecision.RESPOND.value: 'finalize',
    })
    graph.add_edge('tool', 'agent')
    graph.add_edge('finalize', END)

    compiled = graph.compile(checkpointer=InMemorySaver())
    logger.info('Agent DAG compiled successfully')
    return compiled
