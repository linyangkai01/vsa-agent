import json
from collections.abc import AsyncIterator

import pytest

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.api.original_ui_chat import OriginalUIChatRequest
from vsa_agent.api.original_ui_chat import extract_latest_user_text
from vsa_agent.api.original_ui_chat import format_chunk_for_original_ui
from vsa_agent.api.original_ui_chat import format_done
from vsa_agent.api.original_ui_chat import format_intermediate_data
from vsa_agent.api.original_ui_chat import format_openai_delta
from vsa_agent.api.original_ui_chat import stream_original_ui_chat


def test_extract_latest_user_text_uses_last_user_message():
    request = OriginalUIChatRequest(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "analyze the configured video"},
        ]
    )

    assert extract_latest_user_text(request) == "analyze the configured video"


def test_extract_latest_user_text_supports_multimodal_text_parts():
    request = OriginalUIChatRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe safety risk"},
                    {"type": "image", "image_url": "ignored"},
                ],
            }
        ]
    )

    assert extract_latest_user_text(request) == "describe safety risk"


def test_extract_latest_user_text_rejects_empty_payload():
    request = OriginalUIChatRequest(messages=[{"role": "assistant", "content": "no user"}])

    with pytest.raises(ValueError, match="No user message"):
        extract_latest_user_text(request)


def test_extract_latest_user_text_rejects_user_message_without_text_content():
    request = OriginalUIChatRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "image_url": "ignored"},
                    {"type": "text", "text": "   "},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="No user message"):
        extract_latest_user_text(request)


def test_format_openai_delta_frame_matches_original_ui_proxy():
    frame = format_openai_delta("hello")

    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame.removeprefix("data: ").strip())
    assert payload["choices"][0]["delta"]["content"] == "hello"


def test_format_done_frame():
    assert format_done() == "data: [DONE]\n\n"


def test_format_intermediate_data_frame():
    frame = format_intermediate_data(
        name="Tool Call",
        payload="Calling: video_understanding",
        status="in_progress",
        index=3,
    )

    assert frame.startswith("intermediate_data: ")
    payload = json.loads(frame.removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Call"
    assert payload["payload"] == "Calling: video_understanding"
    assert payload["status"] == "in_progress"
    assert payload["index"] == 3


def test_format_chunk_for_original_ui_maps_final_to_delta():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(type=AgentMessageChunkType.FINAL, content="final answer"),
        index=1,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["choices"][0]["delta"]["content"] == "final answer"


def test_format_chunk_for_original_ui_maps_tool_call_to_intermediate_data():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content="Calling: video_understanding"),
        index=2,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Call"
    assert payload["payload"] == "Calling: video_understanding"


class FakeGraph:
    def __init__(self):
        self.received_state = None
        self.received_config = None

    async def astream(self, state, config=None, stream_mode=None) -> AsyncIterator[AgentMessageChunk]:
        self.received_state = state
        self.received_config = config
        assert stream_mode == "custom"
        yield AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content="Analyzing...")
        yield AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content="Calling: video_understanding")
        yield AgentMessageChunk(type=AgentMessageChunkType.FINAL, content="The worker is on a platform.")


async def build_fake_graph(fake_graph: FakeGraph):
    return fake_graph


@pytest.mark.asyncio
async def test_stream_original_ui_chat_runs_graph_and_emits_compatible_frames():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            conversation_id="conversation-1",
            user_message_id="message-1",
            graph_builder=lambda: build_fake_graph(fake_graph),
        )
    ]

    assert any(frame.startswith("intermediate_data: ") for frame in frames)
    assert any('"The worker is on a platform."' in frame for frame in frames)
    assert frames[-1] == "data: [DONE]\n\n"
    assert fake_graph.received_state.current_message.content == "inspect video"
    assert fake_graph.received_config["configurable"]["thread_id"] == "conversation-1"


@pytest.mark.asyncio
async def test_stream_original_ui_chat_uses_default_thread_id_when_header_missing():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            graph_builder=lambda: build_fake_graph(fake_graph),
        )
    ]

    assert frames[-1] == "data: [DONE]\n\n"
    assert fake_graph.received_config["configurable"]["thread_id"] == "original-ui-chat"


@pytest.mark.asyncio
async def test_stream_original_ui_chat_emits_error_and_done_when_graph_setup_fails():
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])

    async def broken_graph_builder():
        raise RuntimeError("graph unavailable")

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            graph_builder=broken_graph_builder,
        )
    ]

    assert frames[0].startswith("intermediate_data: ")
    assert '"status": "error"' in frames[0]
    assert "RuntimeError: graph unavailable" in frames[0]
    assert "RuntimeError: graph unavailable" in frames[1]
    assert frames[-1] == "data: [DONE]\n\n"
