"""Tests for data_models/vss.py."""
from vsa_agent.data_models.vss import MediaInfoOffset
from vsa_agent.video_analytics.nvschema import Incident

class TestMediaInfoOffset:
    def test_defaults(self):
        m = MediaInfoOffset()
        assert m.video_path == ""
        assert m.duration_sec == 0.0

    def test_custom_values(self):
        m = MediaInfoOffset(video_path="/path/to/video.mp4", duration_sec=120.5, fps=30.0)
        assert m.video_path == "/path/to/video.mp4"
        assert m.duration_sec == 120.5

class TestIncident:
    def test_defaults(self):
        inc = Incident()
        assert inc.description == ""
        assert inc.severity == "unknown"

    def test_with_values(self):
        inc = Incident(description="A person fell", timestamp_sec=100.0, severity="high")
        assert inc.description == "A person fell"
        assert inc.severity == "high"
