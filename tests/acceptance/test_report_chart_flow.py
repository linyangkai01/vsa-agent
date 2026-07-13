"""Acceptance tests for chart-enhanced report flow."""

import pytest

from vsa_agent.agents.data_models import AgentOutput


@pytest.mark.anyio
async def test_multi_report_flow_with_chart_blocks():
    from vsa_agent.agents.multi_report_agent import (
        MultiReportAgentInput,
        MultiReportSourceItem,
        execute_multi_report_agent,
    )
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
    assert "## 统计概览" in result.side_effects["markdown_content"]
    assert "## 图表" in result.side_effects["markdown_content"]
    assert "| 事件类型 | 次数 |" in result.side_effects["markdown_content"]
