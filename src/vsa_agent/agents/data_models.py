import enum

from pydantic import BaseModel
from pydantic import Field


# ========== Agent Decision & Streaming Types ==========


class AgentDecision(enum.StrEnum):
    '''Decision of the agent node — drives LangGraph conditional edges.'''
    CALL_TOOL = 'call_tool'
    RESPOND = 'respond'


class AgentMessageChunkType(enum.StrEnum):
    '''Type of the streaming message chunk emitted by DAG nodes.'''
    THOUGHT = 'thought'
    TOOL_CALL = 'tool_call'
    FINAL = 'final'
    ERROR = 'error'


class AgentMessageChunk(BaseModel):
    '''Streaming chunk emitted by agent nodes during graph traversal.

    Each DAG node writes chunks of these types so the frontend can
    render thoughts, tool calls, and final responses differently.
    Ref: NVIDIA original uses identical pattern with get_stream_writer().
    '''
    type: AgentMessageChunkType = Field(default=AgentMessageChunkType.THOUGHT, description='The type of the message chunk')
    content: str = Field(default='', description='The content of the message chunk')


class AgentOutput(BaseModel):
    '''Standardized output model for agents.

    Separates conversational messages from generated artifacts (reports,
    charts, media URLs) and execution metadata (timing, tool calls, etc.).
    '''
    messages: list[str] = Field(default_factory=list, description='Conversational output for the user')
    side_effects: dict = Field(default_factory=dict, description='Generated artifacts')
    metadata: dict = Field(default_factory=dict, description='Execution metadata')
    status: str = Field(default='success', description='Execution status')
