"""Minimal chart metadata generator for report embedding."""

from __future__ import annotations

from pydantic import BaseModel, Field

from vsa_agent.registry import register_tool


class ChartSeriesItem(BaseModel):
    """One bar chart series item."""

    label: str
    value: int


class ChartArtifact(BaseModel):
    """Minimal chart artifact for markdown report embedding."""

    chart_type: str
    title: str
    spec: dict = Field(default_factory=dict)
    markdown_table: str = ""


def _build_markdown_table(
    x_label: str,
    y_label: str,
    series: list[ChartSeriesItem],
) -> str:
    lines = [
        f"| {x_label} | {y_label} |",
        "| --- | --- |",
    ]
    for item in series:
        lines.append(f"| {item.label} | {item.value} |")
    return "\n".join(lines)


@register_tool(
    "chart_generator",
    description="Generate minimal chart metadata and markdown table output.",
)
async def generate_bar_chart_artifact(
    chart_title: str,
    x_label: str,
    y_label: str,
    series: list[ChartSeriesItem],
) -> ChartArtifact:
    """Generate a minimal bar chart artifact for report embedding."""
    return ChartArtifact(
        chart_type="bar",
        title=chart_title,
        spec={
            "labels": [item.label for item in series],
            "values": [item.value for item in series],
            "x_label": x_label,
            "y_label": y_label,
        },
        markdown_table=_build_markdown_table(x_label, y_label, series),
    )
