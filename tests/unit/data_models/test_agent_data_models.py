"""Tests for agents/data_models.py."""
from langchain_core.messages import HumanMessage, AIMessage
from vsa_agent.agents.data_models import (
    AgentDecision, AgentMessageChunkType, AgentMessageChunk,
    AgentState, AgentOutput,
)

class TestAgentDecision:
    def test_values(self):
        assert AgentDecision.CALL_TOOL.value == "call_tool"
        assert AgentDecision.RESPOND.value == "respond"

class TestAgentMessageChunkType:
    def test_values(self):
        assert AgentMessageChunkType.THOUGHT.value == "thought"
        assert AgentMessageChunkType.TOOL_CALL.value == "tool_call"
        assert AgentMessageChunkType.TOOL_PROGRESS.value == "tool_progress"
        assert AgentMessageChunkType.TOOL_RESULT.value == "tool_result"
        assert AgentMessageChunkType.FINAL.value == "final"

class TestAgentMessageChunk:
    def test_defaults(self):
        chunk = AgentMessageChunk()
        assert chunk.type == AgentMessageChunkType.THOUGHT
        assert chunk.content == ""
        assert chunk.metadata == {}

class TestAgentState:
    def test_defaults(self):
        state = AgentState()
        assert state.current_message is None
        assert state.iteration_count == 0
        assert state.search_source_type == "video_file"

    def test_with_message(self):
        msg = HumanMessage(content="test query")
        state = AgentState(current_message=msg)
        assert state.current_message.content == "test query"

class TestAgentOutput:
    def test_defaults(self):
        out = AgentOutput()
        assert out.messages == []
        assert out.status == "success"

    def test_error_status(self):
        out = AgentOutput(status="error")
        assert out.status == "error"
