from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.api import original_ui_chat
from vsa_agent.api.routes import app


class FakeGraph:
    async def astream(self, state, config=None, stream_mode=None) -> AsyncIterator[AgentMessageChunk]:
        yield AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content="Analyzing...")
        yield AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=f"answer for {state.current_message.content}")


async def fake_build_graph():
    return FakeGraph()


def test_chat_stream_route_returns_original_ui_compatible_stream(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(original_ui_chat, "build_default_graph_for_original_ui", fake_build_graph, raising=False)
    client = TestClient(app)

    response = client.post(
        "/chat/stream",
        json={"messages": [{"role": "user", "content": "inspect video"}]},
        headers={"Conversation-Id": "conversation-1", "User-Message-ID": "message-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "intermediate_data: " in response.text
    assert '"answer for inspect video"' in response.text
    assert "data: [DONE]" in response.text


def test_chat_stream_route_rejects_empty_messages():
    client = TestClient(app)

    response = client.post("/chat/stream", json={"messages": []})

    assert response.status_code == 400
    assert "No user message" in response.text


def test_existing_api_chat_route_still_exists():
    route_paths = {route.path for route in app.routes}

    assert "/api/chat" in route_paths
    assert "/chat/stream" in route_paths


def test_existing_api_chat_route_streams_tool_progress_chunk(monkeypatch: pytest.MonkeyPatch):
    import vsa_agent.agents.top_agent as top_agent

    class ApiChatFakeGraph:
        async def astream(self, state, config=None, stream_mode=None) -> AsyncIterator[AgentMessageChunk]:
            yield AgentMessageChunk(
                type=AgentMessageChunkType.TOOL_PROGRESS,
                content="Completed video chunk 1/2",
                metadata={"status": "completed", "chunk_index": 1, "chunk_count": 2},
            )
            yield AgentMessageChunk(type=AgentMessageChunkType.FINAL, content="done")

    async def fake_build_graph_for_api_chat():
        return ApiChatFakeGraph()

    monkeypatch.setattr(top_agent, "build_graph", fake_build_graph_for_api_chat)
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "inspect video"})

    assert response.status_code == 200
    assert '"type": "tool_progress"' in response.text
    assert "Completed video chunk 1/2" in response.text
    assert "data: [DONE]" in response.text
