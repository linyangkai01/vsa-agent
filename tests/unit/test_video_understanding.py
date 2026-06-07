"""Tests for the video_understanding tool — VLM-based video frame analysis."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.registry import ToolRegistry


# ===== Helpers =====


def _mock_model_adapter(response_text: str):
    """Create a mock model adapter that returns the given text."""
    adapter = MagicMock()
    response = MagicMock()
    response.content = response_text
    adapter.invoke = AsyncMock(return_value=response)
    return adapter


# ===== Tests =====


class TestVideoUnderstanding:
    """Test the video_understanding registered tool."""

    def test_basic_caption(self):
        """A basic query with a few frames should return a string caption."""
        fn = ToolRegistry.get("video_understanding")
        assert fn is not None, "video_understanding tool must be registered"

        adapter = _mock_model_adapter("Person wearing a red hard hat walking near machinery")
        result = asyncio.run(fn(
            frames=["/9j/base64frame1", "/9j/base64frame2"],
            query="Describe the safety conditions in this video",
            model_adapter=adapter,
        ))

        assert isinstance(result, str)
        assert len(result) > 0
        assert "red hard hat" in result
        adapter.invoke.assert_called_once()

    def test_empty_frames_returns_error(self):
        """Empty frames list should raise ValueError."""
        fn = ToolRegistry.get("video_understanding")
        adapter = _mock_model_adapter("unused")

        with pytest.raises(ValueError, match="At least one frame"):
            asyncio.run(fn(
                frames=[],
                query="What do you see?",
                model_adapter=adapter,
            ))
        adapter.invoke.assert_not_called()

    def test_vlm_prompt_includes_query(self):
        """The query should appear in the prompt sent to the VLM."""
        fn = ToolRegistry.get("video_understanding")
        adapter = _mock_model_adapter("ok")

        asyncio.run(fn(
            frames=["frame1"],
            query="Are workers wearing helmets?",
            model_adapter=adapter,
        ))

        # The prompt sent to VLM should include the query
        call_args = adapter.invoke.call_args
        messages = call_args[0][0]  # first positional arg = messages list
        # Find the text content in the human message
        found = False
        for msg in messages:
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    if "Are workers wearing helmets?" in content:
                        found = True
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            if "Are workers wearing helmets?" in part.get("text", ""):
                                found = True
        assert found, f"Query not found in VLM messages: {messages}"
        adapter.invoke.assert_called_once()

    def test_multiple_frames_are_included(self):
        """All provided frames should appear as image_urls in the VLM message."""
        fn = ToolRegistry.get("video_understanding")
        adapter = _mock_model_adapter("Three frames analyzed")

        frames = ["frame_a", "frame_b", "frame_c"]
        asyncio.run(fn(
            frames=frames,
            query="Analyze",
            model_adapter=adapter,
        ))

        call_args = adapter.invoke.call_args
        messages = call_args[0][0]
        image_count = 0
        for msg in messages:
            content = msg.content if hasattr(msg, "content") else []
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        image_count += 1
        assert image_count == 3, f"Expected 3 image_url parts, got {image_count}"

    def test_uses_vlm_format_instruction(self):
        """The system prompt should include the VLM format instruction from config."""
        fn = ToolRegistry.get("video_understanding")
        adapter = _mock_model_adapter("Caption text")

        asyncio.run(fn(
            frames=["frame1"],
            query="Look at this",
            model_adapter=adapter,
        ))

        call_args = adapter.invoke.call_args
        messages = call_args[0][0]
        # The first message should be a system message with format instructions
        system_msgs = [m for m in messages if hasattr(m, "type") and m.type == "system"]
        assert len(system_msgs) >= 1, "Expected at least one system message"

    def test_long_response(self):
        """Tool should handle long VLM responses correctly."""
        fn = ToolRegistry.get("video_understanding")
        long_text = "A detailed analysis. " * 50
        adapter = _mock_model_adapter(long_text)

        result = asyncio.run(fn(
            frames=["frame1"],
            query="Give me a detailed analysis",
            model_adapter=adapter,
        ))

        assert isinstance(result, str)
        assert len(result) > 100
