"""Tests for structured postprocessing pipeline support."""

import pytest


@pytest.mark.anyio
async def test_process_report_accepts_structured_report():
    from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline
    from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
    from vsa_agent.data_models.report import ReportSection
    from vsa_agent.data_models.report import StructuredReport
    from vsa_agent.data_models.understanding import UnderstandingResult

    report = StructuredReport(
        report_title="多视频聚合报告",
        report_type="multi_video",
        user_query="生成报告",
        sections=[
            ReportSection(
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
        ],
    )

    pipeline = ValidationPipeline([NonEmptyValidator()])
    result = await pipeline.process_report(report)

    assert result.passed is True
