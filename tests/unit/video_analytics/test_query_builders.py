"""Tests for video_analytics/query_builders.py."""
from vsa_agent.video_analytics.query_builders import build_incident_query, build_frames_query, build_behavior_query

class TestBuildIncidentQuery:
    def test_basic(self):
        query = build_incident_query(query="collision")
        assert isinstance(query, dict)
        assert "query" in query

    def test_with_filters(self):
        query = build_incident_query(query="test", filters={"severity": "high"}, time_range=(0.0, 100.0))
        assert isinstance(query, dict)

class TestBuildFramesQuery:
    def test_basic(self):
        query = build_frames_query(sensor_id="s1", time_range=(0.0, 100.0))
        assert isinstance(query, dict)

class TestBuildBehaviorQuery:
    def test_basic(self):
        query = build_behavior_query(behavior_type="running")
        assert isinstance(query, dict)
