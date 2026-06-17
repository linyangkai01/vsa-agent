"""Tests for tools/report_structuring.py."""

import pytest

from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult


def test_build_single_section_report_maps_understanding_to_structured_report():
    from vsa_agent.tools.report_structuring import build_single_section_report

    result = UnderstandingResult(
        query="生成报告",
        source_type="rtsp",
        summary_text="forklift stops near doorway",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="event-1",
                label="vehicle",
                description="forklift stops near doorway",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
                evidence=[EvidenceRef(source_type="rtsp", sensor_id="camera-1")],
            )
        ],
    )

    report = build_single_section_report(
        source_name="camera-1",
        source_type="rtsp",
        user_query="生成报告",
        understanding_result=result,
    )

    assert report.report_type == "single_video"
    assert report.sections[0].incidents[0].description == "forklift stops near doorway"
    assert report.sections[0].source_name == "camera-1"


def test_build_single_section_report_sets_location_summary():
    from vsa_agent.tools.report_structuring import build_single_section_report

    result = UnderstandingResult(
        query="生成报告",
        source_type="video_file",
        summary_text="person enters loading dock",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="event-2",
                label="intrusion",
                description="person enters loading dock",
                start_timestamp="00:00:10",
                end_timestamp="00:00:14",
                evidence=[EvidenceRef(source_type="video_file", video_path="video.mp4")],
            )
        ],
    )

    report = build_single_section_report(
        source_name="video.mp4",
        source_type="video_file",
        user_query="生成报告",
        understanding_result=result,
    )

    assert "unknown" in report.sections[0].location_summary
