"""Tests for data_models/report.py."""

from vsa_agent.data_models.understanding import UnderstandingResult


def test_structured_report_defaults_and_serialization():
    from vsa_agent.data_models.report import ReportSection
    from vsa_agent.data_models.report import StructuredReport

    section = ReportSection(
        section_id="section-1",
        section_title="事件 1 - camera-1",
        source_name="camera-1",
        source_type="rtsp",
        user_query="生成报告",
        summary_text="forklift stops near doorway",
        understanding_result=UnderstandingResult(
            query="生成报告",
            source_type="rtsp",
            summary_text="forklift stops near doorway",
            chunks=[],
            events=[],
        ),
    )
    report = StructuredReport(
        report_title="多视频聚合报告",
        report_type="multi_video",
        user_query="生成报告",
        sections=[section],
    )

    assert report.report_title == "多视频聚合报告"
    assert report.sections[0].section_title == "事件 1 - camera-1"
    assert report.model_dump()["sections"][0]["source_type"] == "rtsp"
