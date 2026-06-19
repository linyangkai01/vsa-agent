"""Single-video Markdown report generation for Phase 3."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.data_models.report import ReportSection
from vsa_agent.data_models.report import StructuredReport
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.registry import register_tool


class VideoReportGenOutput(BaseModel):
    """Output contract for generated single-video reports."""

    markdown_content: str
    downloads: dict[str, dict[str, str]] = Field(default_factory=dict)
    summary: str = ""


def _get_events(
    understanding_result: UnderstandingResult | dict[str, Any],
) -> list[DetectedEvent | dict[str, Any]]:
    if isinstance(understanding_result, dict):
        return list(understanding_result.get("events", []))
    return list(understanding_result.events)


def _format_event_line(event: DetectedEvent | dict[str, Any]) -> str:
    if isinstance(event, dict):
        start_timestamp = str(event.get("start_timestamp", ""))
        end_timestamp = str(event.get("end_timestamp", ""))
        description = str(event.get("description", "")).strip()
    else:
        start_timestamp = event.start_timestamp
        end_timestamp = event.end_timestamp
        description = event.description.strip()

    if start_timestamp or end_timestamp:
        return f"- [{start_timestamp} - {end_timestamp}] {description}".rstrip()
    return f"- {description}" if description else ""


def _format_timeline(
    understanding_result: UnderstandingResult | dict[str, Any],
) -> str:
    lines = [_format_event_line(event) for event in _get_events(understanding_result)]
    non_empty_lines = [line for line in lines if line]
    if not non_empty_lines:
        return "- 无结构化事件"
    return "\n".join(non_empty_lines)


def _format_validation_feedback(section: ReportSection) -> str:
    if not section.validation_feedback:
        return ""
    lines = ["## 校验反馈"]
    lines.extend(f"- {item}" for item in section.validation_feedback)
    return "\n".join(lines)


def _coerce_report_section(
    *,
    report_section: ReportSection | None = None,
    structured_report: StructuredReport | None = None,
    sensor_id: str = "",
    user_query: str = "",
    understanding_result: UnderstandingResult | dict[str, Any] | None = None,
) -> ReportSection:
    if report_section is not None:
        return report_section

    if structured_report is not None:
        if not structured_report.sections:
            raise ValueError("structured_report must contain at least one section")
        return structured_report.sections[0]

    raw_understanding = understanding_result or {
        "query": user_query,
        "source_type": "video_file",
        "summary_text": "",
        "chunks": [],
        "events": [],
    }
    if isinstance(raw_understanding, UnderstandingResult):
        parsed_understanding = raw_understanding
    else:
        parsed_understanding = UnderstandingResult(
            query=str(raw_understanding.get("query", user_query)),
            source_type=str(raw_understanding.get("source_type", "video_file")),
            summary_text=str(raw_understanding.get("summary_text", "")),
            chunks=[],
            events=[],
        )
    return ReportSection(
        section_id=f"{sensor_id or 'report'}-section",
        section_title=f"事件 - {sensor_id or 'uploaded-video'}",
        source_name=sensor_id or "uploaded-video",
        source_type=parsed_understanding.source_type,
        user_query=user_query,
        summary_text=parsed_understanding.summary_text,
        understanding_result=(
            raw_understanding if isinstance(raw_understanding, UnderstandingResult) else raw_understanding
        ),
    )


@register_tool(
    "video_report_gen",
    description="Generate a single-video Markdown report from a structured understanding result.",
)
async def generate_video_report(
    sensor_id: str = "",
    user_query: str = "",
    understanding_result: UnderstandingResult | dict[str, Any] | None = None,
    report_section: ReportSection | None = None,
    structured_report: StructuredReport | None = None,
) -> VideoReportGenOutput:
    """Generate a Markdown report from a video understanding result."""
    section = _coerce_report_section(
        report_section=report_section,
        structured_report=structured_report,
        sensor_id=sensor_id,
        user_query=user_query,
        understanding_result=understanding_result,
    )
    summary_text = section.summary_text
    timeline_text = _format_timeline(section.understanding_result)
    validation_feedback_text = _format_validation_feedback(section)
    markdown_content = (
        "# 单视频分析报告\n"
        "## 视频源\n"
        f"- sensor_id: {section.source_name}\n\n"
        "## 用户问题\n"
        f"{section.user_query}\n\n"
        "## 摘要\n"
        f"{summary_text}\n\n"
        "## 事件时间线\n"
        f"{timeline_text}\n"
    )
    if validation_feedback_text:
        markdown_content = f"{markdown_content}\n\n{validation_feedback_text}\n"
    return VideoReportGenOutput(
        markdown_content=markdown_content,
        downloads={
            "markdown": {
                "filename": f"{section.source_name}-report.md",
                "content_type": "text/markdown",
            }
        },
        summary=summary_text,
    )
