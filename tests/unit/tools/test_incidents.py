"""Tests for tools/incidents.py."""

import json

from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


def test_understanding_to_incidents_maps_events_to_nvschema():
    from vsa_agent.tools.incidents import understanding_to_incidents

    event = DetectedEvent(
        event_id="event-1",
        label="intrusion",
        description="person enters restricted area",
        start_timestamp="00:00:05",
        end_timestamp="00:00:12",
        evidence=[EvidenceRef(source_type="video_file", video_path="video.mp4")],
    )
    result = UnderstandingResult(
        query="find intrusion",
        source_type="video_file",
        summary_text="person enters restricted area",
        chunks=[],
        events=[event],
    )

    incidents = understanding_to_incidents(result)

    assert len(incidents) == 1
    assert incidents[0].id == "event-1"
    assert incidents[0].category == "intrusion"
    assert incidents[0].description == "person enters restricted area"
    assert incidents[0].confidence == 0.0
    assert incidents[0].metadata["query"] == "find intrusion"
    assert incidents[0].metadata["start_timestamp"] == "00:00:05"


def test_search_output_to_incidents_uses_clip_time_and_description():
    from vsa_agent.tools.incidents import search_output_to_incidents

    output = SearchOutput(
        data=[
            SearchResult(
                video_name="camera-1",
                description="forklift enters loading zone",
                start_time="2025-01-01T10:00:00Z",
                end_time="2025-01-01T10:00:10Z",
                sensor_id="camera-1",
                similarity=0.88,
            )
        ]
    )

    incidents = search_output_to_incidents(output)

    assert len(incidents) == 1
    assert incidents[0].category == "search_hit"
    assert incidents[0].description == "forklift enters loading zone"
    assert incidents[0].confidence == 0.88
    assert incidents[0].metadata["video_name"] == "camera-1"
    assert incidents[0].metadata["start_time"] == "2025-01-01T10:00:00Z"


def test_search_output_to_incidents_preserves_video_metadata():
    from vsa_agent.tools.incidents import search_output_to_incidents

    output = SearchOutput(
        data=[
            SearchResult(
                video_name="cam-04.mp4",
                description="person crosses lane",
                start_time="2026-06-19T10:20:00",
                end_time="2026-06-19T10:20:07",
                sensor_id="cam-04",
                screenshot_url="shot.png",
                similarity=0.79,
                object_ids=["obj-1"],
            )
        ]
    )

    incidents = search_output_to_incidents(output)

    assert incidents[0].metadata["video_name"] == "cam-04.mp4"
    assert incidents[0].metadata["start_time"] == "2026-06-19T10:20:00"
    assert incidents[0].metadata["end_time"] == "2026-06-19T10:20:07"
    assert incidents[0].metadata["sensor_id"] == "cam-04"
    assert incidents[0].metadata["screenshot_url"] == "shot.png"
    assert incidents[0].metadata["object_ids"] == ["obj-1"]


def test_incidents_to_tagged_json_wraps_payload():
    from vsa_agent.tools.incidents import incidents_to_tagged_json
    from vsa_agent.video_analytics.nvschema import Incident

    payload = incidents_to_tagged_json(
        [
            Incident(
                id="incident-1",
                description="person enters restricted area",
                category="intrusion",
                confidence=0.91,
            )
        ]
    )

    assert payload.startswith("<incidents>\n")
    assert payload.endswith("\n</incidents>")

    json_text = payload.removeprefix("<incidents>\n").removesuffix("\n</incidents>")
    parsed = json.loads(json_text)
    assert parsed["incidents"][0]["id"] == "incident-1"
    assert parsed["incidents"][0]["category"] == "intrusion"


def test_understanding_to_incidents_returns_empty_for_no_events():
    from vsa_agent.tools.incidents import understanding_to_incidents

    result = UnderstandingResult(
        query="find intrusion",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[],
    )

    assert understanding_to_incidents(result) == []
