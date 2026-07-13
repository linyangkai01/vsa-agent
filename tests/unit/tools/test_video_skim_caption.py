"""Tests for tools/video_skim_caption.py."""

import pytest


@pytest.mark.anyio
async def test_skim_caption_adds_brief_prompt_prefix(monkeypatch):
    from vsa_agent.tools.video_skim_caption import video_skim_caption_tool

    captured = {}

    async def fake_video_caption_tool(**kwargs):
        captured.update(kwargs)
        return "brief caption"

    monkeypatch.setattr(
        "vsa_agent.tools.video_skim_caption.video_caption_tool",
        fake_video_caption_tool,
    )
    text = await video_skim_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "brief caption"
    assert "简要" in captured["user_prompt"]
    assert "describe" in captured["user_prompt"]
