import pytest
import asyncio
from vsa_agent.agents.top_agent import (
    AgentState, build_graph, agent_node, tool_node, finalize_node, decide_next
)
from vsa_agent.agents.data_models import AgentDecision, AgentMessageChunk, AgentMessageChunkType


class TestAgentState:
    def test_default_state(self):
        state = AgentState()
        assert state.messages == []
        assert state.current_message == ''
        assert state.final_answer == ''
        assert state.retry_count == 0

    def test_build_prompt(self):
        from langchain_core.messages import SystemMessage, HumanMessage
        state = AgentState(current_message='what is safety?')
        prompt = state.build_prompt('You are an assistant.')
        assert len(prompt) == 2
        assert isinstance(prompt[0], SystemMessage)
        assert isinstance(prompt[1], HumanMessage)
        assert prompt[1].content == 'what is safety?'


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
        '''build_graph compiles a DAG with all 3 nodes.'''
        async def _run():
            return await build_graph()
        graph = asyncio.run(_run())
        nodes = list(graph.get_graph().nodes.keys())
        assert 'agent' in nodes
        assert 'tool' in nodes
        assert 'finalize' in nodes
        assert '__start__' in nodes
        assert '__end__' in nodes

    def test_decide_next_no_tools(self):
        state = AgentState()
        assert decide_next(state) == AgentDecision.RESPOND.value

    def test_decide_next_with_tools(self):
        state = AgentState(pending_tool_calls=[{'name': 'echo', 'args': {}, 'id': '1'}])
        assert decide_next(state) == AgentDecision.CALL_TOOL.value
