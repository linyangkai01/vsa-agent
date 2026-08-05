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
    assert "final_answer" not in events[event_types.index("top_agent.final")]["payload"]
    assert "final answer" not in trace_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "model_response",
    [
        AIMessage(content="answer without local evidence"),
        AIMessage(
            content="",
            tool_calls=[{"name": "find_video", "args": {"name": "clip"}, "id": "wrong-tool"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "video_understanding", "args": {}, "id": "duplicate-video"},
                {"name": "find_video", "args": {"name": "clip"}, "id": "extra-tool"},
            ],
        ),
    ],
)
@pytest.mark.asyncio
async def test_selected_video_context_enforces_video_understanding_route(
    trace_dir,
    monkeypatch,
    model_response,
):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    class FakeAdapter:
        def bind_tools(self, tools):
            self.tools = tools

        async def invoke(self, messages):
            return model_response

    monkeypatch.setattr("vsa_agent.model_adapter.create_model_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(top_agent, "_build_langchain_tools", lambda: [])
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)

    state = AgentState(
        current_message=HumanMessage(content="What safety issue is visible?"),
        local_video_context={"video_path": "/private/selected.mp4"},
        selected_recorded_video=True,
    )
    state = await top_agent.agent_node(state, {})

    assert state.final_answer == ""
    assert len(state.agent_scratchpad) == 1
    tool_calls = state.agent_scratchpad[0].tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "video_understanding"
    assert tool_calls[0]["args"] == {"query": "What safety issue is visible?"}

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    route = next(event for event in events if event["event_type"] == "top_agent.selected_video.route")
    assert route["payload"]["tool_name"] == "video_understanding"
    assert route["payload"]["source_type"] == "runtime_enforced"
    assert "/private/selected.mp4" not in trace_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_selected_video_context_preserves_one_correct_model_tool_call(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "video_understanding",
                "args": {"query": "Inspect pedestrian separation."},
                "id": "model-video-tool",
            }
        ],
    )

    class FakeAdapter:
        def bind_tools(self, tools):
            self.tools = tools

        async def invoke(self, messages):
            return response

    monkeypatch.setattr("vsa_agent.model_adapter.create_model_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(top_agent, "_build_langchain_tools", lambda: [])
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)

    state = AgentState(
        current_message=HumanMessage(content="What happened?"),
        local_video_context={"video_path": "/private/selected.mp4"},
        selected_recorded_video=True,
    )
    state = await top_agent.agent_node(state, {})

    assert state.agent_scratchpad[0].tool_calls == response.tool_calls
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    route = next(event for event in events if event["event_type"] == "top_agent.selected_video.route")
    assert route["payload"]["source_type"] == "model_confirmed"


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
    assert result_event["payload"]["result_length"] == len("tool output")
    assert "artifact_path" not in result_event["payload"]


@pytest.mark.asyncio
async def test_top_agent_trace_records_filled_video_query(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))

    async def fake_tool(video_path: str, query: str):
        return f"{query}: {video_path}"

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": fake_tool},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)
    state = AgentState(
        current_message=HumanMessage(content="Describe the routine work visible in the clip."),
        agent_scratchpad=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "video_understanding",
                        "args": {"video_path": "video.mp4"},
                        "id": "call-1",
                    }
                ],
            )
        ],
    )

    await top_agent.tool_node(state, {})

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    call_event = next(event for event in events if event["event_type"] == "top_agent.tool.call")
    assert "tool_args" not in call_event["payload"]
    assert "Describe the routine work visible in the clip." not in trace_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_tool_node_injects_local_video_context_without_tracing_it(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))
    captured = {}

    async def fake_tool(video_path: str, query: str, start_timestamp: float, end_timestamp: float):
        captured.update(
            video_path=video_path,
            query=query,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        return "local evidence canary"

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": fake_tool},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)
    state = AgentState(
        current_message=HumanMessage(content="What happened?"),
        local_video_context={
            "video_path": "/private/video-canary.mp4",
            "start_timestamp": 1.0,
            "end_timestamp": 2.0,
        },
        agent_scratchpad=[
            AIMessage(
                content="",
                tool_calls=[{"name": "video_understanding", "args": {}, "id": "call-local"}],
            )
        ],
    )

    await top_agent.tool_node(state, {})

    assert captured == {
        "video_path": "/private/video-canary.mp4",
        "query": "What happened?",
        "start_timestamp": 1.0,
        "end_timestamp": 2.0,
    }
    assert state.final_answer == "local evidence canary"
    assert not (trace_dir / "tool-results" / "call-local-video_understanding.txt").exists()
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "/private/video-canary.mp4" not in trace_text
    assert "local evidence canary" not in trace_text


@pytest.mark.asyncio
async def test_tool_node_overrides_model_local_path_even_when_query_is_present(trace_dir, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_dir / "trace.jsonl"))
    captured = {}

    async def fake_tool(video_path: str, query: str, start_timestamp: float, end_timestamp: float):
        captured.update(
            video_path=video_path,
            query=query,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        return "local result"

    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get_all",
        lambda: {"video_understanding": fake_tool},
    )
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)
    state = AgentState(
        current_message=HumanMessage(content="What happened?"),
        local_video_context={
            "video_path": "/private/selected.mp4",
            "start_timestamp": 3.0,
            "end_timestamp": 8.0,
        },
        agent_scratchpad=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "video_understanding",
                        "args": {
                            "video_path": "/model/chosen.mp4",
                            "query": "Inspect PPE.",
                            "start_timestamp": 0.0,
                            "end_timestamp": 99.0,
                        },
                        "id": "model-call",
                    }
                ],
            )
        ],
    )

    await top_agent.tool_node(state, {})

    assert captured == {
        "video_path": "/private/selected.mp4",
        "query": "Inspect PPE.",
        "start_timestamp": 3.0,
        "end_timestamp": 8.0,
    }
