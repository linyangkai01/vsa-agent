import json
import shutil
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from vsa_agent.agents.data_models import AgentState

TEST_TRACE_DIR = Path("artifacts/test-top-agent-live-trace")


@pytest.fixture
def trace_dir():
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)
    TEST_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_TRACE_DIR
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)


@pytest.mark.asyncio
async def test_top_agent_logs_agent_request_response_and_final(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    class FakeAdapter:
        def bind_tools(self, tools):
            self.tools = tools

        async def invoke(self, messages):
            return AIMessage(content="final answer")

    monkeypatch.setattr("vsa_agent.model_adapter.create_model_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(top_agent, "_build_langchain_tools", lambda: [])
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)

    state = AgentState(current_message=HumanMessage(content="hello"))
    state = await top_agent.agent_node(state, {})
    state = await top_agent.finalize_node(state, {})

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "top_agent.agent.request" in event_types
    assert "top_agent.agent.response" in event_types
    assert "top_agent.final" in event_types
    assert events[event_types.index("top_agent.final")]["payload"]["final_answer"] == "final answer"


@pytest.mark.asyncio
async def test_top_agent_logs_tool_call_and_result_artifact(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))

    async def fake_tool(video_path: str):
        return "tool output"

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": fake_tool},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)
    state = AgentState(
        agent_scratchpad=[
            AIMessage(
                content="",
                tool_calls=[{"name": "video_understanding", "args": {"video_path": "video.mp4"}, "id": "call-1"}],
            )
        ]
    )

    await top_agent.tool_node(state, {})

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "top_agent.tool.call" in event_types
    assert "top_agent.tool.result" in event_types
    result_event = events[event_types.index("top_agent.tool.result")]
    assert result_event["payload"]["tool_name"] == "video_understanding"
    assert Path(result_event["payload"]["artifact_path"]).exists()
