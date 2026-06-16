"""Tests for api/video_delete.py."""

import pytest


class TestVideoDelete:
    def test_video_delete_router_imports(self):
        from vsa_agent.api.video_delete import router

        assert router is not None

    @pytest.mark.anyio
    async def test_video_delete_returns_deleted_stub(self):
        from vsa_agent.api.video_delete import delete_video

        result = await delete_video(video_id="video-123")

        assert result["video_id"] == "video-123"
        assert result["deleted"] is True
        assert result["mode"] == "stub"
