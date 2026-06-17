"""Acceptance tests for Phase 6 report postprocessing flow."""

import pytest

from vsa_agent.agents.data_models import AgentOutput


@pytest.mark.anyio
async def test_phase6_single_video_report_flow():
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
    assert "# 单视频分析报告" in result.side_effects["markdown_content"]
    assert "person walking near forklift" in result.side_effects["markdown_content"]


@pytest.mark.anyio
async def test_phase6_multi_video_report_flow():
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
    from vsa_agent.tools.report_gen import generate_multi_report

    async def fake_video_understanding_fn(**kwargs):
        source_name = kwargs.get("sensor_id") or kwargs.get("video_path")
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {source_name}",
            "chunks": [],
            "events": [{"label": "walking", "description": "person walking"}],
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[
                MultiReportSourceItem(sensor_id="camera-1"),
                MultiReportSourceItem(video_path="video-a.mp4"),
            ],
        ),
        video_understanding_fn=fake_video_understanding_fn,
        report_gen_fn=generate_multi_report,
    )

    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert "## 报告摘要" in result.side_effects["markdown_content"]
    assert "### 事件 1 - camera-1" in result.side_effects["markdown_content"]
    assert "### 事件 2 - video-a.mp4" in result.side_effects["markdown_content"]
