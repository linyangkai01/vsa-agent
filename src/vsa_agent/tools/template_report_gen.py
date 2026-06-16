"""Template-based multi-section report generation."""

from __future__ import annotations

from pydantic import BaseModel

from vsa_agent.registry import register_tool


class TemplateReportGenOutput(BaseModel):
    """Output contract for aggregated markdown reports."""

    markdown_content: str
    section_count: int = 0


def _build_summary_lines(report_sections: list[dict]) -> str:
    if not report_sections:
        return "- 无分事件内容"

    return "\n".join(
        f"- {section['section_title']}: {section['summary']}"
        for section in report_sections
    )


def _build_count_lines(counts: dict[str, int]) -> str:
    if not counts:
        return "- 无统计数据"

    return "\n".join(
        f"- {label}: {count}"
        for label, count in sorted(counts.items())
    )


@register_tool(
    "template_report_gen",
    description="Assemble multiple event report sections into one markdown report.",
)
async def generate_template_report(
    report_title: str,
    report_sections: list[dict],
    counts: dict[str, int] | None = None,
    chart: dict | None = None,
) -> TemplateReportGenOutput:
    """Generate one template-based markdown report."""
    summary_lines = _build_summary_lines(report_sections)
    counts_text = _build_count_lines(counts or {})
    chart_table = (chart or {}).get("markdown_table", "- 无图表数据")
    detail_blocks = "\n\n".join(
        f"### {section['section_title']}\n\n{section['markdown_content']}"
        for section in report_sections
    )
    markdown_content = (
        f"# {report_title}\n\n"
        "## 报告摘要\n"
        f"{summary_lines}\n\n"
        "## 统计概览\n"
        f"{counts_text}\n\n"
        "## 图表\n"
        f"{chart_table}\n\n"
        "## 分事件报告\n\n"
        f"{detail_blocks}\n"
    )
    return TemplateReportGenOutput(
        markdown_content=markdown_content,
        section_count=len(report_sections),
    )
