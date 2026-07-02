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
