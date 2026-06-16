"""Tests for tools/chart_generator.py."""

import pytest


@pytest.mark.anyio
async def test_generate_bar_chart_artifact_returns_chart_metadata_and_markdown_table():
    from vsa_agent.tools.chart_generator import ChartArtifact
    from vsa_agent.tools.chart_generator import ChartSeriesItem
    from vsa_agent.tools.chart_generator import generate_bar_chart_artifact

    result = await generate_bar_chart_artifact(
        chart_title="事件计数统计",
        x_label="事件类型",
        y_label="次数",
        series=[
            ChartSeriesItem(label="walking", value=2),
            ChartSeriesItem(label="forklift", value=1),
        ],
    )

    assert isinstance(result, ChartArtifact)
    assert result.chart_type == "bar"
    assert result.title == "事件计数统计"
    assert result.spec["labels"] == ["walking", "forklift"]
    assert "| 事件类型 | 次数 |" in result.markdown_table
