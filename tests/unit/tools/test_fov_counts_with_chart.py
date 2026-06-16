"""Tests for tools/fov_counts_with_chart.py."""

import pytest


@pytest.mark.anyio
async def test_build_event_count_chart_counts_events_by_label():
    from vsa_agent.tools.fov_counts_with_chart import CountWithChartResult
    from vsa_agent.tools.fov_counts_with_chart import build_event_count_chart

    chart_calls = []

    async def fake_chart_generator(**kwargs):
        chart_calls.append(kwargs)
        return {
            "chart_type": "bar",
            "title": "事件计数统计",
            "spec": {"labels": ["walking", "forklift"], "values": [2, 1]},
            "markdown_table": "| 事件类型 | 次数 |\n| --- | --- |\n| walking | 2 |\n| forklift | 1 |",
        }

    result = await build_event_count_chart(
        understanding_results=[
            {
                "events": [
                    {"label": "walking", "description": "person walking"},
                    {"label": "walking", "description": "person walking again"},
                ]
            },
            {
                "events": [
                    {"label": "forklift", "description": "forklift turning"},
                ]
            },
        ],
        chart_generator_fn=fake_chart_generator,
    )

    assert isinstance(result, CountWithChartResult)
    assert result.counts == {"walking": 2, "forklift": 1}
    assert result.chart["title"] == "事件计数统计"
    assert chart_calls[0]["chart_title"] == "事件计数统计"
