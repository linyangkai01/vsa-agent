import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from vsa_agent.agents.data_models import AgentMessageChunk, AgentMessageChunkType
from vsa_agent.api.original_ui_chat import (
    OriginalUIChatRequest,
    extract_latest_user_text,
    format_chunk_for_original_ui,
    format_done,
    format_intermediate_data,
    format_openai_delta,
    inject_configured_video_context,
    stream_original_ui_chat,
)


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


def test_inject_configured_video_context_for_configured_video_request():
    prompt = inject_configured_video_context(
        "Analyze the configured video and identify safety risks.",
        "/data/project/lyk/video/1597042367-1-192.mp4",
    )

    assert "Configured video_path: /data/project/lyk/video/1597042367-1-192.mp4" in prompt
    assert "Do not call list_videos" in prompt


def test_inject_configured_video_context_ignores_unrelated_text():
    prompt = inject_configured_video_context(
        "Say hello from vsa-agent.",
        "/data/project/lyk/video/1597042367-1-192.mp4",
    )

    assert prompt == "Say hello from vsa-agent."


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
        AgentMessageChunk(
            type=AgentMessageChunkType.TOOL_CALL,
            content="Calling: video_understanding\nInputs:\n- video_path: video.mp4",
        ),
        index=2,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Call"
    assert "Calling: video_understanding" in payload["payload"]
    assert "video_path: video.mp4" in payload["payload"]


def test_format_chunk_for_original_ui_maps_tool_result_to_completed_intermediate_data():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(
            type=AgentMessageChunkType.TOOL_RESULT,
            content="Completed: video_understanding\nResult length: 123 chars",
        ),
        index=3,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Result"
    assert payload["status"] == "completed"
    assert "Result length: 123 chars" in payload["payload"]


def test_format_chunk_for_original_ui_maps_tool_progress_to_intermediate_data():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(
            type=AgentMessageChunkType.TOOL_PROGRESS,
            content="Completed video chunk 2/7\nElapsed: 9.3s",
            metadata={"status": "completed"},
        ),
        index=4,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Progress"
    assert payload["status"] == "completed"
    assert "Completed video chunk 2/7" in payload["payload"]


def test_format_chunk_for_original_ui_enriches_tool_progress_from_metadata():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(
            type=AgentMessageChunkType.TOOL_PROGRESS,
            content="Completed video chunk 2/7",
            metadata={
                "status": "completed",
                "chunk_index": 2,
                "chunk_count": 7,
                "start_timestamp": 30.0,
                "end_timestamp": 60.0,
                "elapsed_sec": 12.345,
                "frame_count": 8,
                "risk_category": "Fire / hot work",
                "risk_evidence": "Welding sparks without a visible face shield.",
                "evidence_type": "observed",
                "raw_artifact_path": "/tmp/raw.txt",
                "result_artifact_path": "/tmp/result.json",
            },
        ),
        index=4,
    )

    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Progress"
    assert "Risk: Fire / hot work" in payload["payload"]
    assert "Evidence type: observed" in payload["payload"]
    assert "Raw VLM output: /tmp/raw.txt" in payload["payload"]
    assert "Result JSON: /tmp/result.json" in payload["payload"]


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
async def test_stream_original_ui_chat_injects_configured_video_path():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(
        messages=[{"role": "user", "content": "Analyze the configured video and identify safety risks."}]
    )

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            graph_builder=lambda: build_fake_graph(fake_graph),
            configured_video_path="/data/project/lyk/video/1597042367-1-192.mp4",
        )
    ]

    assert frames[-1] == "data: [DONE]\n\n"
    assert "Configured video_path: /data/project/lyk/video/1597042367-1-192.mp4" in (
        fake_graph.received_state.current_message.content
    )


@pytest.mark.asyncio
async def test_stream_original_ui_chat_writes_conversation_trace():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])
    trace_root = Path("artifacts/test-original-ui-chat-trace")
    shutil.rmtree(trace_root, ignore_errors=True)

    try:
        frames = [
            frame
            async for frame in stream_original_ui_chat(
                request,
                conversation_id="conversation/1",
                user_message_id="message:1",
                graph_builder=lambda: build_fake_graph(fake_graph),
                trace_root=trace_root,
            )
        ]

        assert frames[-1] == "data: [DONE]\n\n"
        run_dirs = [path for path in trace_root.iterdir() if path.is_dir()]
        assert len(run_dirs) == 1
        trace_path = run_dirs[0] / "trace.jsonl"
        request_path = run_dirs[0] / "request.json"
        assert trace_path.exists()
        assert request_path.exists()
        events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        assert "original_ui.chat.request" in [event["event_type"] for event in events]
        assert json.loads(request_path.read_text(encoding="utf-8"))["conversation_id"] == "conversation/1"
        assert (trace_root / "latest.txt").read_text(encoding="utf-8").strip() == str(run_dirs[0])
    finally:
        shutil.rmtree(trace_root, ignore_errors=True)


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
