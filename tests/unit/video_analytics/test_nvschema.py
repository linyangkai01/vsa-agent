"""Tests for video_analytics/nvschema.py."""
from vsa_agent.video_analytics.nvschema import Incident, Location, Place

class TestIncident:
    def test_defaults(self):
        inc = Incident()
        assert inc.description == ""
        assert inc.severity == "unknown"

    def test_with_values(self):
        inc = Incident(description="Forklift accident", timestamp_sec=100.0, severity="high", category="collision")
        assert inc.description == "Forklift accident"
        assert inc.severity == "high"

class TestLocation:
    def test_defaults(self):
        loc = Location()
        assert loc.name == ""

    def test_with_values(self):
        loc = Location(name="Warehouse A", coordinates=(37.7749, -122.4194))
        assert loc.name == "Warehouse A"

class TestPlace:
    def test_defaults(self):
        p = Place()
        assert p.name == ""

    def test_with_values(self):
        p = Place(name="Main Gate")
        assert p.name == "Main Gate"
