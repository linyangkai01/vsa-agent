"""Tests for api/health.py."""


class TestHealthEndpoint:
    def test_health_imports(self):
        from vsa_agent.api.health import app

        assert app is not None
