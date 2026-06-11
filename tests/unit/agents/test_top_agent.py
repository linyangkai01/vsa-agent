"""Tests for agents/top_agent.py."""
from langchain_core.messages import AIMessage, HumanMessage
from vsa_agent.agents.data_models import AgentDecision, AgentState
from vsa_agent.agents.top_agent import decide_next, build_graph

class TestDecideNext:
    def test_empty_scratchpad_returns_respond(self):
        state = AgentState()
        assert decide_next(state) == AgentDecision.RESPOND.value

    def test_tool_call_returns_call_tool(self):
        msg = AIMessage(content="", tool_calls=[{"name": "test", "args": {}, "id": "1"}])
        state = AgentState(agent_scratchpad=[msg])
        assert decide_next(state) == AgentDecision.CALL_TOOL.value

    def test_ai_message_no_tool_calls_returns_respond(self):
        msg = AIMessage(content="final answer")
        state = AgentState(agent_scratchpad=[msg])
        assert decide_next(state) == AgentDecision.RESPOND.value

class TestBuildGraph:
    def test_graph_compiles(self):
        import asyncio
        graph = asyncio.run(build_graph())
        assert graph is not None
