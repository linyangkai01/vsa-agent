import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunk, AgentMessageChunkType
from vsa_agent.prompt import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ===== State =====


class AgentState(BaseModel):
    '''Typed state flowing through all DAG nodes.'''
    messages: list[BaseMessage] = Field(default_factory=list)
    current_message: str = ''
    final_answer: str = ''
    pending_tool_calls: list[dict] = Field(default_factory=list)
    retry_count: int = 0

    def build_prompt(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> list[BaseMessage]:
        '''Assemble the full LLM prompt from conversation history + current message.'''
        prompt: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        prompt.extend(self.messages)
        prompt.append(HumanMessage(content=self.current_message))
        return prompt


# ===== Nodes =====


async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Main reasoning node — invoke the LLM and decide next action.'''
    from vsa_agent.model_adapter import create_model_adapter

    writer = get_stream_writer()
    logger.debug('Starting agent node')

    prompt = state.build_prompt()
    writer(AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content='Analyzing...'))

    response = await create_model_adapter().invoke(prompt)

    if isinstance(response, AIMessage) and response.tool_calls:
        state.pending_tool_calls = [
            {'name': tc['name'], 'args': tc['args'], 'id': tc['id']}
            for tc in response.tool_calls
        ]
        state.messages.append(response)
    else:
        content = response.content if isinstance(response, AIMessage) else str(response)
        state.final_answer = content
        state.messages.append(response)

    return state


async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Execute pending tool calls and record results in messages.'''
    from vsa_agent.registry import ToolRegistry

    writer = get_stream_writer()
    logger.debug('Starting tool node')
    tools = ToolRegistry.get_all()

    for tc in state.pending_tool_calls:
        name, args, call_id = tc['name'], tc['args'], tc['id']
        writer(AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content=f'Calling: {name}'))

        try:
            result = await tools[name](**args) if name in tools else f'Tool not found: {name}'
        except Exception as e:
            result = f'Error: {e}'

        state.messages.append(ToolMessage(content=str(result), tool_call_id=call_id))

    state.pending_tool_calls = []
    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Emit final answer and reset per-round state.'''
    writer = get_stream_writer()
    writer(AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=state.final_answer))
    logger.debug('Finalize node: conversation complete')
    return state


# ===== Routing =====


def decide_next(state: AgentState) -> str:
    '''Conditional edge: route agent_node to tool or finalize.'''
    if state.pending_tool_calls:
        return AgentDecision.CALL_TOOL.value
    return AgentDecision.RESPOND.value


# ===== Graph Builder =====


async def build_graph() -> CompiledStateGraph:
    '''Build and compile the top agent DAG.'''
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
