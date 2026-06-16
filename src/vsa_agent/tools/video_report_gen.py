"""Single-video Markdown report generation for Phase 3."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.registry import register_tool


class VideoReportGenOutput(BaseModel):
    """Output contract for generated single-video reports."""

    markdown_content: str
    downloads: dict[str, dict[str, str]] = Field(default_factory=dict)
    summary: str = ""


def _get_summary_text(understanding_result: UnderstandingResult | dict[str, Any]) -> str:
    if isinstance(understanding_result, dict):
        return str(understanding_result.get("summary_text", ""))
    return understanding_result.summary_text


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
    lines = [
        _format_event_line(event)
        for event in _get_events(understanding_result)
    ]
    non_empty_lines = [line for line in lines if line]
    if not non_empty_lines:
        return "- 无结构化事件"
    return "\n".join(non_empty_lines)


@register_tool(
    "video_report_gen",
    description="Generate a single-video Markdown report from a structured understanding result.",
)
async def generate_video_report(
    sensor_id: str,
    user_query: str,
    understanding_result: UnderstandingResult | dict[str, Any],
) -> VideoReportGenOutput:
    """Generate a Markdown report from a video understanding result."""
    summary_text = _get_summary_text(understanding_result)
    timeline_text = _format_timeline(understanding_result)
    markdown_content = (
        "# 单视频分析报告\n\n"
        "## 视频源\n"
        f"- sensor_id: {sensor_id}\n\n"
        "## 用户问题\n"
        f"{user_query}\n\n"
        "## 摘要\n"
        f"{summary_text}\n\n"
        "## 事件时间线\n"
        f"{timeline_text}\n"
    )
    return VideoReportGenOutput(
        markdown_content=markdown_content,
        downloads={
            "markdown": {
                "filename": f"{sensor_id}-report.md",
                "content_type": "text/markdown",
            }
        },
        summary=summary_text,
    )
