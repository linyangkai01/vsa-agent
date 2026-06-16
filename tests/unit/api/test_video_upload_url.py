"""Tests for api/video_upload_url.py."""
class TestVideoUploadUrl:
    def test_router_imports(self):
        from vsa_agent.api.video_upload_url import router
        assert router is not None
