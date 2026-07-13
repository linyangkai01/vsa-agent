"""Acceptance tests for single-video report flow."""

import pytest

from vsa_agent.agents.data_models import AgentOutput

VALIDATION_FEEDBACK = "[non_empty_response_validator] FAILED: Response is empty"


def _heading_levels(markdown_content: str) -> list[int]:
    return [
        len(line) - len(line.lstrip("#"))
        for line in markdown_content.splitlines()
        if line.startswith("#") and line.lstrip("#").startswith(" ")
    ]


@pytest.mark.anyio
async def test_single_video_report_flow_returns_markdown_side_effect():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.tools.video_report_gen import generate_video_report

    async def fake_video_understanding_fn(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "forklift proximity summary",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift event",
                }
            ],
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding_fn,
        video_report_gen_fn=generate_video_report,
    )

    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    markdown = result.side_effects["markdown_content"]
    assert _heading_levels(markdown) == [1, 2, 2, 2, 2]
    assert "- sensor_id: video.mp4" in markdown
    assert "生成详细报告" in markdown
    assert "forklift proximity summary" in markdown
    assert "person walking near forklift event" in markdown
    assert "[00:00:05 - 00:00:09]" in markdown


@pytest.mark.anyio
async def test_single_video_report_flow_keeps_markdown_when_postprocessing_fails():
    from vsa_agent.agents.postprocessing.pipeline import PostprocessingResult, ValidationPipeline
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.tools.video_report_gen import generate_video_report

    class FailingValidationPipeline(ValidationPipeline):
        async def process(self, output: str) -> PostprocessingResult:
            return PostprocessingResult(passed=False, feedback=VALIDATION_FEEDBACK)

    async def fake_video_understanding_fn(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "",
            "chunks": [],
            "events": [],
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding_fn,
        video_report_gen_fn=generate_video_report,
        validation_pipeline=FailingValidationPipeline(),
    )

    assert result.status == "success"
    assert result.metadata["validation_passed"] is False
    assert result.metadata["validation_feedback"] == [VALIDATION_FEEDBACK]
    markdown = result.side_effects["markdown_content"]
    assert _heading_levels(markdown) == [1, 2, 2, 2, 2, 2]
    assert VALIDATION_FEEDBACK in markdown


@pytest.mark.anyio
async def test_single_video_report_flow_raises_when_understanding_fails():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent

    called = {"value": False}

    async def broken_video_understanding(**kwargs):
        raise RuntimeError("vlm call failed")

    async def fake_video_report_gen(**kwargs):
        called["value"] = True
        return kwargs

    with pytest.raises(RuntimeError, match="vlm call failed"):
        await execute_report_agent(
            ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
            video_understanding_fn=broken_video_understanding,
            video_report_gen_fn=fake_video_report_gen,
        )

    assert called["value"] is False
