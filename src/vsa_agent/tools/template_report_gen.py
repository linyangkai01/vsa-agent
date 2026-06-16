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


@register_tool(
    "template_report_gen",
    description="Assemble multiple event report sections into one markdown report.",
)
async def generate_template_report(
    report_title: str,
    report_sections: list[dict],
) -> TemplateReportGenOutput:
    summary_lines = _build_summary_lines(report_sections)
    detail_blocks = "\n\n".join(
        f"### {section['section_title']}\n\n{section['markdown_content']}"
        for section in report_sections
    )
    markdown_content = (
        f"# {report_title}\n\n"
        "## 报告摘要\n"
        f"{summary_lines}\n\n"
        "## 分事件报告\n\n"
        f"{detail_blocks}\n"
    )
    return TemplateReportGenOutput(
        markdown_content=markdown_content,
        section_count=len(report_sections),
    )
