"""Tests for tools/video_detailed_caption.py."""

import pytest


@pytest.mark.anyio
async def test_detailed_caption_adds_detail_prompt_prefix(monkeypatch):
    from vsa_agent.tools.video_detailed_caption import video_detailed_caption_tool

    captured = {}

    async def fake_video_caption_tool(**kwargs):
        captured.update(kwargs)
        return "detailed caption"

    monkeypatch.setattr(
        "vsa_agent.tools.video_detailed_caption.video_caption_tool",
        fake_video_caption_tool,
    )
    text = await video_detailed_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "detailed caption"
    assert "详细" in captured["user_prompt"]
    assert "describe" in captured["user_prompt"]

