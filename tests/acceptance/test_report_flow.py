"""Acceptance tests for single-video report flow."""

import pytest

from vsa_agent.agents.data_models import AgentOutput

VALIDATION_FEEDBACK = "[non_empty_response_validator] FAILED: Response is empty"


@pytest.mark.anyio
async def test_single_video_report_flow_returns_markdown_side_effect():
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
    from vsa_agent.tools.video_report_gen import generate_video_report

    async def fake_video_understanding_fn(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift",
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
    assert result.side_effects["markdown_content"].startswith("# 单视频分析报告")
    assert "## 视频源" in result.side_effects["markdown_content"]
    assert "## 事件时间线" in result.side_effects["markdown_content"]
    assert "person walking near forklift" in result.side_effects["markdown_content"]


@pytest.mark.anyio
async def test_single_video_report_flow_keeps_markdown_when_postprocessing_fails():
    from vsa_agent.agents.postprocessing.pipeline import PostprocessingResult
    from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
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
    assert "## 校验反馈" in result.side_effects["markdown_content"]


@pytest.mark.anyio
async def test_single_video_report_flow_raises_when_understanding_fails():
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent

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
