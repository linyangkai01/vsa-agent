"""Tests for tools/video_caption.py."""

import pytest

from vsa_agent.data_models.understanding import UnderstandingResult


@pytest.mark.anyio
async def test_video_caption_short_path_delegates_to_analyze_video(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return type("Result", (), {"summary_text": "short caption", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)

    text = await video_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "short caption"
    assert captured["video_path"] == "video.mp4"
    assert captured["query"] == "describe"
    assert captured["source_type"] == "video_file"


@pytest.mark.anyio
async def test_video_caption_long_path_uses_summary_text_from_long_pipeline(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool

    async def fake_analyze_video(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="long caption summary",
            chunks=[],
            events=[],
            metadata={"chunk_count": 2},
        )

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)
    text = await video_caption_tool(video_path="video.mp4", user_prompt="describe")
    assert text == "long caption summary"


@pytest.mark.anyio
async def test_video_caption_rtsp_input_sets_rtsp_source_type(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return type("Result", (), {"summary_text": "rtsp caption", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)

    text = await video_caption_tool(
        sensor_id="camera-1",
        user_prompt="describe",
        start_timestamp="PT5S",
        end_timestamp="PT10S",
    )

    assert text == "rtsp caption"
    assert captured["sensor_id"] == "camera-1"
    assert captured["source_type"] == "rtsp"
    assert captured["start_timestamp"] == "PT5S"
    assert captured["end_timestamp"] == "PT10S"

