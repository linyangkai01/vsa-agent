"""Multi-report generation orchestrator."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class ReportSectionInput(BaseModel):
    """Input payload for one report section."""

    section_title: str
    sensor_id: str
    user_query: str
    understanding_result: dict[str, Any]


class MultiReportGenOutput(BaseModel):
    """Output contract for aggregated multi-report generation."""

    markdown_content: str
    downloads: dict[str, dict[str, str]] = Field(default_factory=dict)
    summary: str = ""
    section_count: int = 0


async def _default_single_report_gen(**kwargs):
    from vsa_agent.tools.video_report_gen import generate_video_report

    return await generate_video_report(**kwargs)


async def _default_template_report_gen(**kwargs):
    from vsa_agent.tools.template_report_gen import generate_template_report

    return await generate_template_report(**kwargs)


async def _default_count_chart_builder_fn(**kwargs):
    from vsa_agent.tools.fov_counts_with_chart import build_event_count_chart

    return await build_event_count_chart(**kwargs)


@register_tool(
    "report_gen",
    description="Generate one markdown report from multiple structured video understanding results.",
)
async def generate_multi_report(
    report_title: str,
    report_sections: list[ReportSectionInput],
    single_report_gen_fn=None,
    template_report_gen_fn=None,
    count_chart_builder_fn=None,
) -> MultiReportGenOutput:
    """Generate one aggregated markdown report from multiple sections."""
    single_report_gen = single_report_gen_fn or _default_single_report_gen
    template_report_gen = template_report_gen_fn or _default_template_report_gen
    count_chart_builder = count_chart_builder_fn or _default_count_chart_builder_fn

    normalized_sections = []
    summaries = []
    understanding_results: list[dict[str, Any]] = []

    for section in report_sections:
        report = await single_report_gen(
            sensor_id=section.sensor_id,
            user_query=section.user_query,
            understanding_result=section.understanding_result,
        )
        report_dict = report if isinstance(report, dict) else report.model_dump()
        normalized_sections.append(
            {
                "section_title": section.section_title,
                "summary": report_dict["summary"],
                "markdown_content": report_dict["markdown_content"],
            }
        )
        summaries.append(report_dict["summary"])
        understanding_results.append(section.understanding_result)

    count_chart = await count_chart_builder(
        understanding_results=understanding_results,
    )
    count_chart_dict = count_chart if isinstance(count_chart, dict) else count_chart.model_dump()

    template = await template_report_gen(
        report_title=report_title,
        report_sections=normalized_sections,
        counts=count_chart_dict["counts"],
        chart=count_chart_dict["chart"],
    )
    template_dict = template if isinstance(template, dict) else template.model_dump()

    return MultiReportGenOutput(
        markdown_content=template_dict["markdown_content"],
        downloads={
            "markdown": {
                "filename": "multi-report.md",
                "content_type": "text/markdown",
            }
        },
        summary="; ".join(text for text in summaries if text),
        section_count=template_dict["section_count"],
    )
