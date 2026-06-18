"""Tests for data_models/vss.py."""

from vsa_agent.data_models import Incident
from vsa_agent.data_models import Location
from vsa_agent.data_models import MediaInfoOffset
from vsa_agent.data_models import Place

class TestMediaInfoOffset:
    def test_defaults(self):
        m = MediaInfoOffset()
        assert m.video_path == ""
        assert m.duration_sec == 0.0

    def test_custom_values(self):
        m = MediaInfoOffset(video_path="/path/to/video.mp4", duration_sec=120.5, fps=30.0)
        assert m.video_path == "/path/to/video.mp4"
        assert m.duration_sec == 120.5

    def test_current_frame_index_uses_offset_and_fps(self):
        m = MediaInfoOffset(duration_sec=30.0, fps=10.0, current_offset_sec=2.6)
        assert m.current_frame_index == 26

    def test_remaining_duration_is_clamped(self):
        m = MediaInfoOffset(duration_sec=10.0, current_offset_sec=12.0)
        assert m.remaining_duration_sec == 0.0

    def test_to_dict_round_trip_preserves_metadata(self):
        m = MediaInfoOffset(
            video_path="demo.mp4",
            duration_sec=12.5,
            fps=25.0,
            total_frames=312,
            current_offset_sec=4.0,
            metadata={"sensor_id": "cam-1"},
        )
        restored = MediaInfoOffset.from_dict(m.to_dict())
        assert restored == m

class TestIncident:
    def test_defaults(self):
        inc = Incident()
        assert inc.description == ""
        assert inc.severity == "unknown"

    def test_with_values(self):
        inc = Incident(description="A person fell", timestamp_sec=100.0, severity="high")
        assert inc.description == "A person fell"
        assert inc.severity == "high"


class TestCompatExports:
    def test_reexports_location_place_and_incident(self):
        assert Location.__name__ == "Location"
        assert Place.__name__ == "Place"
        assert Incident.__name__ == "Incident"
