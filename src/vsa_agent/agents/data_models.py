from enum import StrEnum


class AgentDecision(StrEnum):
    '''Agent routing decisions for the LangGraph DAG.

    Design Pattern #3: Typed agent decisions. Using StrEnum instead of plain
    strings means LangGraph conditional edges are type-safe and IDE-supported.
    '''
    CALL_TOOL = 'call_tool'
    RESPOND = 'respond'


class AgentMessageChunkType(StrEnum):
    '''Types of streaming chunks emitted by agent nodes.

    Design Pattern #18: Node-level streaming. Each DAG node emits typed chunks
    so the frontend can render thoughts, tool calls, and final responses differently.
    '''
    THOUGHT = 'thought'
    TOOL_CALL = 'tool_call'
    FINAL = 'final'
    ERROR = 'error'
