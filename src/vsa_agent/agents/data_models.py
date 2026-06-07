import enum

from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from pydantic import Field


# ========== Agent Decision & Streaming Types ==========


class AgentDecision(enum.StrEnum):
    """Decision of the agent node — drives LangGraph conditional edges."""
    CALL_TOOL = 'call_tool'
    RESPOND = 'respond'


class AgentMessageChunkType(enum.StrEnum):
    """Type of the streaming message chunk emitted by DAG nodes."""
    THOUGHT = 'thought'
    TOOL_CALL = 'tool_call'
    FINAL = 'final'
    ERROR = 'error'


class AgentMessageChunk(BaseModel):
    """Streaming chunk emitted by agent nodes during graph traversal."""
    type: AgentMessageChunkType = Field(default=AgentMessageChunkType.THOUGHT)
    content: str = Field(default='')


class AgentState(BaseModel):
    """State for the Top Agent conversation tracking.

    Mirrors NVIDIA's TopAgentState pattern:
    - current_message: latest user query as a BaseMessage
    - agent_scratchpad: AI thought steps + tool results during a tool-call loop
    - conversation_history: finished HumanMessage/AIMessage pairs between turns
    - iteration_count: how many LLM calls so far
    - final_answer: terminal answer string
    - plan / previous_conversation / reasoning fields: reserved for future features
    """
    current_message: BaseMessage | None = Field(default=None)
    agent_scratchpad: list[BaseMessage] = Field(default_factory=list)
    conversation_history: list[BaseMessage] = Field(default_factory=list)
    iteration_count: int = Field(default=0)
    final_answer: str = Field(default='')

    # --- Reserved for future features ---
    plan: str = Field(default='')
    previous_conversation: str = Field(default='')
    llm_reasoning: bool = Field(default=False)
    vlm_reasoning: bool | None = Field(default=None)
    search_source_type: str = Field(default='video_file')


class AgentOutput(BaseModel):
    """Standardized output model for agents."""
    messages: list[str] = Field(default_factory=list)
    side_effects: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    status: str = Field(default='success')
