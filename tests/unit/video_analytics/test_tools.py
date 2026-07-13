"""Tests for video_analytics/tools.py."""

from vsa_agent.video_analytics.nvschema import Incident
from vsa_agent.video_analytics.tools import analyze_incident_timeline, summarize_incidents


class TestAnalyzeIncidentTimeline:
    async def test_empty_incidents(self):
        result = await analyze_incident_timeline([])
        assert result == []

    async def test_single_incident(self):
        inc = Incident(description="Test incident", timestamp_sec=10.0, duration_sec=5.0)
        result = await analyze_incident_timeline([inc])
        assert isinstance(result, list)


class TestSummarizeIncidents:
    async def test_empty(self):
        result = await summarize_incidents([])
        assert isinstance(result, str)
        assert "No incidents" in result

    async def test_with_incidents(self):
        inc = Incident(
            description="Test incident", timestamp_sec=10.0, duration_sec=5.0, severity="high", confidence=0.9
        )
        result = await summarize_incidents([inc])
        assert isinstance(result, str)
        assert "Test incident" in result
