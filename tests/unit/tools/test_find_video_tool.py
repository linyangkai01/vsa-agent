"""Tests for tools/find_video_tool.py."""
from vsa_agent.tools.find_video_tool import find_video_tool, list_videos_tool

class TestFindVideoTool:
    async def test_unknown_video_returns_message(self):
        result = await find_video_tool(name="nonexistent_video")
        assert "not found" in result.lower()

    async def test_list_videos_returns_string(self):
        result = await list_videos_tool()
        assert isinstance(result, str)

    async def test_list_videos_ignores_extra_llm_arguments(self):
        result = await list_videos_tool(config={})
        assert isinstance(result, str)
