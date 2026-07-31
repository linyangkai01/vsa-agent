import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from vsa_agent.agents.data_models import AgentState


@pytest.mark.asyncio
async def test_top_agent_remote_boundary_excludes_all_local_canaries(tmp_path, monkeypatch):
    import vsa_agent.agents.top_agent as top_agent

    canaries = (
        "private-forklift-video.mp4",
        "/data/private/private-forklift-video.mp4",
        "camera-secret-77",
        "2026-07-30T09:15:00Z",
        "worker clothing evidence canary",
        "history evidence canary",
        "tool result evidence canary",
    )
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    class FakeAdapter:
        def __init__(self):
            self.messages = []

        def bind_tools(self, tools):
            self.tools = tools

        async def invoke(self, messages):
            self.messages = messages
            return AIMessage(content="safe remote answer")

    adapter = FakeAdapter()
    monkeypatch.setattr("vsa_agent.model_adapter.create_model_adapter", lambda: adapter)
    monkeypatch.setattr(top_agent, "_build_langchain_tools", lambda: [])
    monkeypatch.setattr(top_agent, "get_stream_writer", lambda: lambda chunk: None)
    state = AgentState(
        current_message=HumanMessage(content="forklift near worker"),
        local_video_context={
            "video_name": canaries[0],
            "video_path": canaries[1],
            "sensor_id": canaries[2],
            "start_timestamp": canaries[3],
            "local_evidence": canaries[4],
        },
        conversation_history=[HumanMessage(content=canaries[5])],
        agent_scratchpad=[ToolMessage(content=canaries[6], tool_call_id="local-call")],
    )

    result = await top_agent.agent_node(state, {})

    outbound = json.dumps([message.content for message in adapter.messages], default=str)
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "forklift near worker" in outbound
    for canary in canaries:
        assert canary not in outbound
        assert canary not in trace_text
    assert result.final_answer == "safe remote answer"
