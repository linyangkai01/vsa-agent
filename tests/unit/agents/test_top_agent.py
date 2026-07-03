from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from vsa_agent.agents.data_models import AgentDecision, AgentState
from vsa_agent.agents.top_agent import _build_langchain_tools
from vsa_agent.agents.top_agent import _is_unrecoverable_tool_error
from vsa_agent.agents.top_agent import _truncate_result
from vsa_agent.agents.top_agent import build_graph
from vsa_agent.agents.top_agent import decide_after_tool
from vsa_agent.agents.top_agent import decide_next


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


class TestDecideAfterTool:
    def test_final_answer_returns_respond(self):
        state = AgentState(final_answer="fatal tool error")
        assert decide_after_tool(state) == AgentDecision.RESPOND.value

    def test_no_final_answer_returns_call_tool(self):
        state = AgentState()
        assert decide_after_tool(state) == AgentDecision.CALL_TOOL.value


class TestBuildGraph:
    def test_graph_compiles(self):
        import asyncio
        graph = asyncio.run(build_graph())
        assert graph is not None


def test_build_langchain_tools_hides_low_level_report_generator(monkeypatch):
    async def fake_report_agent(video_path: str, query: str = ""):
        return "report"

    async def fake_video_report_gen(report_section: str):
        return "low level report"

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {
            "report_agent": fake_report_agent,
            "video_report_gen": fake_video_report_gen,
        },
    )

    tools = _build_langchain_tools()

    assert [tool.name for tool in tools] == ["report_agent"]


def test_detects_unrecoverable_tool_errors():
    result = (
        "Error: Error code: 403 - {'error': {'code': "
        "'AllocationQuota.FreeTierOnly', 'message': 'The free quota has been exhausted.'}}"
    )

    assert _is_unrecoverable_tool_error(result)


def test_does_not_treat_generic_tool_errors_as_unrecoverable():
    assert not _is_unrecoverable_tool_error("Error: temporary network issue")


def test_truncate_video_result_keeps_late_safety_evidence():
    result = (
        "Opening construction-site observations without conclusions.\n"
        + ("general activity around workers and materials\n" * 35)
        + "Throughout the video, the following safety risks and hazards are observable:\n"
        + "Workers on scaffolding are at height without visible harnesses, creating a fall hazard.\n"
        + ("additional middle detail\n" * 50)
        + "Overall assessment: immediate corrective action is required for PPE and fall protection."
    )

    truncated = _truncate_result("video_understanding", result)

    assert "abridged from" in truncated
    assert "KEY SAFETY/RISK EVIDENCE" in truncated
    assert "without visible harnesses" in truncated
    assert "Overall assessment" in truncated
    assert len(truncated) <= 2000


@pytest.mark.asyncio
async def test_tool_node_stops_after_unrecoverable_tool_error(monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    calls = []

    async def quota_tool(video_path: str):
        calls.append(video_path)
        return (
            "Error: Error code: 403 - {'error': {'code': "
            "'AllocationQuota.FreeTierOnly', 'message': 'The free quota has been exhausted.'}}"
        )

    async def should_not_run():
        raise AssertionError("second tool should not run after fatal tool error")

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": quota_tool, "echo": should_not_run},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)

    state = AgentState(
        agent_scratchpad=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "video_understanding",
                        "args": {"video_path": "video.mp4"},
                        "id": "call-1",
                    },
                    {"name": "echo", "args": {}, "id": "call-2"},
                ],
            )
        ]
    )

    await top_agent.tool_node(state, {})

    assert calls == ["video.mp4"]
    assert "video_understanding failed with an unrecoverable model-service error" in state.final_answer
    assert "AllocationQuota.FreeTierOnly" in state.final_answer


@pytest.mark.asyncio
async def test_tool_node_reuses_cached_result_for_duplicate_tool_call(monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    async def should_not_run(video_path: str):
        raise AssertionError(f"duplicate tool should not run for {video_path}")

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": should_not_run},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)

    args = {"video_path": "video.mp4", "query": "safety risks"}
    state = AgentState(
        agent_scratchpad=[
            AIMessage(content="", tool_calls=[{"name": "video_understanding", "args": args, "id": "call-1"}]),
            ToolMessage(content="cached safety analysis", tool_call_id="call-1"),
            AIMessage(content="", tool_calls=[{"name": "video_understanding", "args": args, "id": "call-2"}]),
        ]
    )

    await top_agent.tool_node(state, {})

    assert isinstance(state.agent_scratchpad[-1], ToolMessage)
    assert state.agent_scratchpad[-1].tool_call_id == "call-2"
    assert state.agent_scratchpad[-1].content == "cached safety analysis"
