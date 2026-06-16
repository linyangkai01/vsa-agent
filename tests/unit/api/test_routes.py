"""Tests for api/routes.py."""
class TestChatEndpoint:
    def test_router_imports(self):
        from vsa_agent.api.routes import app
        assert app is not None
