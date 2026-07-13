"""Single-video report agent for Phase 3."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline
from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
from vsa_agent.observability.live_trace import (
    write_live_json_artifact,
    write_live_text_artifact,
    write_live_trace_event,
)
from vsa_agent.registry import register_tool
from vsa_agent.tools.report_structuring import build_single_section_report, normalize_understanding_result
from vsa_agent.tools.video_understanding import analyze_video

VideoUnderstandingCallable = Callable[..., Awaitable[Any]]
VideoReportCallable = Callable[..., Awaitable[Any]]


class ReportAgentInput(BaseModel):
    """Agent-layer input for single-video report generation."""

    video_path: str | None = Field(default=None, description="Uploaded/local video path")
    sensor_id: str | None = Field(default=None, description="RTSP sensor identifier")
    query: str = Field(default="生成详细报告", description="Report generation request")


def _resolve_source_type(report_input: ReportAgentInput) -> str:
    return "rtsp" if report_input.sensor_id else "video_file"


def _normalize_report_result(report_result: Any) -> tuple[str, dict[str, Any], str]:
    if isinstance(report_result, dict):
        markdown_content = str(report_result.get("markdown_content", ""))
        downloads = dict(report_result.get("downloads", {}))
        summary = str(report_result.get("summary", ""))
        return markdown_content, downloads, summary

    markdown_content = str(getattr(report_result, "markdown_content", ""))
    downloads = dict(getattr(report_result, "downloads", {}))
    summary = str(getattr(report_result, "summary", ""))
    return markdown_content, downloads, summary


async def _default_video_understanding_fn(**kwargs):
    return await analyze_video(**kwargs)


async def _default_video_report_gen_fn(**kwargs):
    from vsa_agent.tools.video_report_gen import generate_video_report

    return await generate_video_report(**kwargs)


async def execute_report_agent(
    report_input: ReportAgentInput,
    video_understanding_fn: VideoUnderstandingCallable | None = None,
    video_report_gen_fn: VideoReportCallable | None = None,
    validation_pipeline: ValidationPipeline | None = None,
) -> AgentOutput:
    """Execute the single-video report generation flow."""
    if not report_input.video_path and not report_input.sensor_id:
        raise ValueError("report_agent 至少需要提供 video_path 或 sensor_id")

    source_type = _resolve_source_type(report_input)
    video_understanding = video_understanding_fn or _default_video_understanding_fn
    video_report_gen = video_report_gen_fn or _default_video_report_gen_fn

    understanding_result = await video_understanding(
        video_path=report_input.video_path or "",
        query=report_input.query,
        source_type=source_type,
        sensor_id=report_input.sensor_id,
    )
    understanding_result = normalize_understanding_result(
        understanding_result=understanding_result,
        user_query=report_input.query,
        source_type=source_type,
    )
    understanding_artifact_path = write_live_json_artifact(
        "tool-results/report-agent-understanding.json",
        understanding_result.model_dump(),
    )
    write_live_trace_event(
        "report_agent.understanding_result",
        {
            "summary_text": understanding_result.summary_text,
            "event_count": len(understanding_result.events),
            "artifact_path": understanding_artifact_path,
        },
    )

    structured_report = build_single_section_report(
        source_name=report_input.sensor_id or report_input.video_path or "uploaded-video",
        source_type=source_type,
        user_query=report_input.query,
        understanding_result=understanding_result,
    )

    pipeline = validation_pipeline or ValidationPipeline([NonEmptyValidator()])
    validation_result = await pipeline.process_report(structured_report)

    report_result = await video_report_gen(
        sensor_id=report_input.sensor_id or "uploaded-video",
        user_query=report_input.query,
        structured_report=structured_report,
    )
    markdown_content, downloads, summary = _normalize_report_result(report_result)
    markdown_artifact_path = write_live_text_artifact("report.md", markdown_content)
    write_live_trace_event(
        "report_agent.result",
        {
            "summary": summary,
            "markdown_length": len(markdown_content),
            "validation_passed": validation_result.passed,
            "artifact_path": markdown_artifact_path,
        },
    )

    return AgentOutput(
        messages=[summary] if summary else [],
        side_effects={
            "markdown_content": markdown_content,
            "downloads": downloads,
        },
        metadata={
            "report_type": "single_video",
            "source_type": source_type,
            "validation_passed": validation_result.passed,
            "validation_feedback": list(structured_report.global_validation_feedback),
        },
        status="success",
    )


@register_tool(
    "report_agent",
    description="Generate a single-video Markdown report from an uploaded video or RTSP sensor clip.",
)
async def report_agent_tool(
    video_path: str = "",
    sensor_id: str = "",
    query: str = "生成详细报告",
) -> str:
    """Tool wrapper for single-video report generation."""
    result = await execute_report_agent(
        ReportAgentInput(
            video_path=video_path or None,
            sensor_id=sensor_id or None,
            query=query,
        )
    )
    return str(result.side_effects.get("markdown_content", ""))
