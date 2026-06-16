"""Tests for api/routes.py."""
class TestChatEndpoint:
    def test_router_imports(self):
        from vsa_agent.api.routes import app
        assert app is not None

    def test_routes_register_rtsp_endpoint(self):
        from vsa_agent.api.routes import app

        paths = {route.path for route in app.routes}
        assert "/api/rtsp/analyze" in paths

    def test_routes_register_video_delete_endpoint(self):
        from vsa_agent.api.routes import app

        paths = {route.path for route in app.routes}
        assert "/api/video/{video_id}" in paths
