"""Event counting and chart adapter for report generation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class CountWithChartResult(BaseModel):
    """Counts plus minimal chart output."""

    counts: dict[str, int] = Field(default_factory=dict)
    chart: dict[str, Any] = Field(default_factory=dict)


async def _default_chart_generator_fn(**kwargs):
    from vsa_agent.tools.chart_generator import ChartSeriesItem
    from vsa_agent.tools.chart_generator import generate_bar_chart_artifact

    series = [ChartSeriesItem(**item) for item in kwargs["series"]]
    result = await generate_bar_chart_artifact(
        chart_title=kwargs["chart_title"],
        x_label=kwargs["x_label"],
        y_label=kwargs["y_label"],
        series=series,
    )
    return result.model_dump()


@register_tool(
    "fov_counts_with_chart",
    description="Build basic event counts and chart output from understanding results.",
)
async def build_event_count_chart(
    understanding_results: list[dict[str, Any]],
    chart_generator_fn=None,
) -> CountWithChartResult:
    """Count event labels and generate minimal chart output."""
    counter = Counter()
    for result in understanding_results:
        for event in result.get("events", []):
            label = str(event.get("label", "")).strip()
            if label:
                counter[label] += 1

    ordered_items = sorted(counter.items(), key=lambda item: item[0])
    series = [{"label": label, "value": count} for label, count in ordered_items]
    chart_generator = chart_generator_fn or _default_chart_generator_fn
    chart = await chart_generator(
        chart_title="事件计数统计",
        x_label="事件类型",
        y_label="次数",
        series=series,
    )
    return CountWithChartResult(
        counts=dict(counter),
        chart=chart,
    )
