import json

import pytest

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.api.original_ui_chat import OriginalUIChatRequest
from vsa_agent.api.original_ui_chat import extract_latest_user_text
from vsa_agent.api.original_ui_chat import format_chunk_for_original_ui
from vsa_agent.api.original_ui_chat import format_done
from vsa_agent.api.original_ui_chat import format_intermediate_data
from vsa_agent.api.original_ui_chat import format_openai_delta


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
