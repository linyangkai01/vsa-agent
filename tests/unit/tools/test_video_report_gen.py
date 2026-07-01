import pytest

from vsa_agent.data_models.report import ReportSection
from vsa_agent.data_models.report import StructuredReport
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.video_report_gen import VideoReportGenOutput
from vsa_agent.tools.video_report_gen import generate_video_report


@pytest.mark.anyio
async def test_generate_video_report_returns_markdown_and_download_metadata():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="generate detailed report",
        understanding_result={
            "query": "generate detailed report",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )

    assert isinstance(result, VideoReportGenOutput)
    assert result.markdown_content.startswith("# Video Analysis Report")
    assert result.downloads["markdown"]["filename"].endswith(".md")


@pytest.mark.anyio
async def test_generate_video_report_uses_fixed_sections():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="generate detailed report",
        understanding_result={
            "query": "generate detailed report",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )

    assert result.markdown_content.startswith("# Video Analysis Report")
    assert "## Video Source" in result.markdown_content
    assert "## User Question" in result.markdown_content
    assert "## Summary" in result.markdown_content
    assert "## Event Timeline" in result.markdown_content
    assert "- No structured events" in result.markdown_content


@pytest.mark.anyio
async def test_generate_video_report_formats_event_timeline():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="generate detailed report",
        understanding_result={
            "query": "generate detailed report",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift",
                }
            ],
        },
    )

    assert "- [00:00:05 - 00:00:09] person walking near forklift" in result.markdown_content


def test_generate_video_report_is_registered_as_tool():
    assert getattr(generate_video_report, "_tool_name", "") == "video_report_gen"


@pytest.mark.anyio
async def test_generate_video_report_accepts_report_section():
    section = _make_report_section()

    result = await generate_video_report(report_section=section)

    assert isinstance(result, VideoReportGenOutput)
    assert "forklift stops near doorway" in result.markdown_content


@pytest.mark.anyio
async def test_generate_video_report_accepts_structured_report():
    section = _make_report_section()
    structured_report = StructuredReport(
        report_title="report-title",
        report_type="single_video",
        user_query="generate detailed report",
        sections=[section],
    )

    result = await generate_video_report(structured_report=structured_report)

    assert isinstance(result, VideoReportGenOutput)
    assert "forklift stops near doorway" in result.markdown_content


@pytest.mark.anyio
async def test_generate_video_report_renders_validation_feedback_section():
    structured_report = StructuredReport(
        report_title="report-title",
        report_type="single_video",
        user_query="generate detailed report",
        sections=[
            ReportSection(
                section_id="section-1",
                section_title="event - camera-1",
                source_name="camera-1",
                source_type="rtsp",
                user_query="generate detailed report",
                summary_text="",
                understanding_result=UnderstandingResult(
                    query="generate detailed report",
                    source_type="rtsp",
                    summary_text="",
                    chunks=[],
                    events=[],
                ),
                validation_feedback=["[non_empty_response_validator] FAILED: Response is empty"],
            )
        ],
        global_validation_feedback=["[non_empty_response_validator] FAILED: Response is empty"],
    )

    result = await generate_video_report(structured_report=structured_report)

    assert "## Validation Feedback" in result.markdown_content
    assert "- [non_empty_response_validator] FAILED: Response is empty" in result.markdown_content


def _make_report_section() -> ReportSection:
    return ReportSection(
        section_id="section-1",
        section_title="event 1 - camera-1",
        source_name="camera-1",
        source_type="rtsp",
        user_query="generate detailed report",
        summary_text="forklift stops near doorway",
        understanding_result=UnderstandingResult(
            query="generate detailed report",
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
        ),
    )
