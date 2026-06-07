import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunkType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(BaseModel):
    '''Typed state flowing through the DAG nodes.

    Design Note: messages holds full conversation history as LangChain
    messages. Pydantic serializes them natively for LangGraph checkpointing.
    pending_tool_calls holds only the current round's tool requests — it is
    cleared each time tool_node consumes them.
    '''
    messages: list[BaseMessage] = Field(default_factory=list)
    current_message: str = ''
    final_answer: str = ''
    pending_tool_calls: list[dict] = Field(default_factory=list)
    retry_count: int = 0

    def build_prompt(self, system_prompt: str) -> list[BaseMessage]:
        '''Build the full prompt from conversation history + current message.

        This is the single place where we assemble the LLM prompt. No other
        node needs to touch message conversion logic.
        '''
        prompt: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        prompt.extend(self.messages)
        prompt.append(HumanMessage(content=self.current_message))
        return prompt


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    'You are an industrial safety video analysis agent. '
    'You can use tools to analyze videos and generate safety reports. '
    'Use tools when needed, and respond directly when done.'
)


async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Main reasoning node — call the LLM and decide next action.'''
    from vsa_agent.model_adapter import create_model_adapter

    writer = get_stream_writer()

    prompt = state.build_prompt(DEFAULT_SYSTEM_PROMPT)
    writer({'type': AgentMessageChunkType.THOUGHT.value, 'content': 'Agent thinking...'})

    response = await create_model_adapter().invoke(prompt)

    if isinstance(response, AIMessage) and response.tool_calls:
        state.pending_tool_calls = [
            {'name': tc['name'], 'args': tc['args'], 'id': tc['id']}
            for tc in response.tool_calls
        ]
        state.messages.append(response)
    else:
        state.final_answer = response.content if isinstance(response, AIMessage) else str(response)
        state.messages.append(response)

    return state


async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Execute pending tool calls and append results back to messages.'''
    from vsa_agent.registry import ToolRegistry

    writer = get_stream_writer()
    tools = ToolRegistry.get_all()

    for tc in state.pending_tool_calls:
        name, args, call_id = tc['name'], tc['args'], tc['id']
        writer({'type': AgentMessageChunkType.TOOL_CALL.value, 'content': f'Calling: {name}'})

        try:
            result = await tools[name](**args) if name in tools else f'Tool not found: {name}'
        except Exception as e:
            result = f'Error: {e}'

        state.messages.append(ToolMessage(content=str(result), tool_call_id=call_id))

    state.pending_tool_calls = []  # consumed
    return state


async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    '''Emit final answer and reset per-round state.'''
    writer = get_stream_writer()
    writer({'type': AgentMessageChunkType.FINAL.value, 'content': state.final_answer})
    return state


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def decide_next(state: AgentState) -> str:
    return AgentDecision.CALL_TOOL.value if state.pending_tool_calls else AgentDecision.RESPOND.value
