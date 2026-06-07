import pytest
import asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from vsa_agent.agents.data_models import (
    AgentDecision, AgentMessageChunk, AgentMessageChunkType, AgentState
)
from vsa_agent.agents.top_agent import (
    build_graph, agent_node, tool_node, finalize_node, decide_next
)


class TestAgentState:
    def test_default_state(self):
        state = AgentState()
        assert state.current_message is None
        assert state.agent_scratchpad == []
        assert state.conversation_history == []
        assert state.final_answer == ''
        assert state.iteration_count == 0

    def test_state_with_message(self):
        msg = HumanMessage(content='hello')
        state = AgentState(current_message=msg)
        assert state.current_message is not None
        assert state.current_message.content == 'hello'


class TestAgentDecision:
    def test_call_tool_value(self):
        assert AgentDecision.CALL_TOOL.value == 'call_tool'

    def test_respond_value(self):
        assert AgentDecision.RESPOND.value == 'respond'


class TestAgentMessageChunk:
    def test_chunk_creation(self):
        chunk = AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content='thinking...')
        assert chunk.type == AgentMessageChunkType.THOUGHT
        assert chunk.content == 'thinking...'

    def test_chunk_serialization(self):
        chunk = AgentMessageChunk(type=AgentMessageChunkType.FINAL, content='done')
        d = chunk.model_dump()
        assert d['content'] == 'done'


class TestAgentDAG:
    def test_build_graph(self):
        """build_graph compiles a DAG with all 3 nodes."""
        async def _run():
            return await build_graph()
        graph = asyncio.run(_run())
        nodes = list(graph.get_graph().nodes.keys())
        assert 'agent' in nodes
        assert 'tool' in nodes
        assert 'finalize' in nodes
        assert '__start__' in nodes
        assert '__end__' in nodes

    def test_decide_next_no_scratchpad(self):
        state = AgentState()
        assert decide_next(state) == AgentDecision.RESPOND.value

    def test_decide_next_no_tool_calls(self):
        """Scratchpad has only ToolMessage -> no pending tool calls -> RESPOND."""
        from langchain_core.messages import ToolMessage
        state = AgentState()
        state.agent_scratchpad.append(ToolMessage(content='done', tool_call_id='1'))
        assert decide_next(state) == AgentDecision.RESPOND.value

    def test_decide_next_with_tool_calls(self):
        """Scratchpad ends with AIMessage containing tool_calls -> CALL_TOOL."""
        ai_msg = AIMessage(content='', tool_calls=[{'name': 'echo', 'args': {}, 'id': '1'}])
        state = AgentState(agent_scratchpad=[ai_msg])
        assert decide_next(state) == AgentDecision.CALL_TOOL.value
