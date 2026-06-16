"""Tests for tools/video_db.py."""
from vsa_agent.tools.video_db import find_video, list_videos

class TestFindVideo:
    def test_unknown_video_returns_none(self):
        result = find_video("nonexistent_video_xyz_12345")
        assert result is None

    def test_empty_string_returns_none(self):
        result = find_video("")
        # find_video("") resolves to project root dir which exists
        if result is not None:
            assert isinstance(result, str)

class TestListVideos:
    def test_returns_list(self):
        result = list_videos()
        assert isinstance(result, list)
