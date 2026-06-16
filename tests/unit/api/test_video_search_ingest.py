"""Tests for api/video_search_ingest.py."""
class TestVideoSearchIngest:
    def test_router_imports(self):
        from vsa_agent.api.video_search_ingest import router
        assert router is not None
