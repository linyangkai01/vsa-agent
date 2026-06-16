"""Multi-source report agent for Phase 3."""

from __future__ import annotations

from typing import Any
from typing import Awaitable
from typing import Callable

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.registry import register_tool
from vsa_agent.tools.report_gen import ReportSectionInput
from vsa_agent.tools.video_understanding import analyze_video

VideoUnderstandingCallable = Callable[..., Awaitable[Any]]
ReportGenCallable = Callable[..., Awaitable[Any]]


class MultiReportSourceItem(BaseModel):
    """One source item for multi-report generation."""

    video_path: str | None = Field(default=None)
    sensor_id: str | None = Field(default=None)


class MultiReportAgentInput(BaseModel):
    """Input model for multi-report generation."""

    report_title: str = Field(default="多视频聚合报告")
    query: str = Field(default="生成聚合报告")
    sources: list[MultiReportSourceItem] = Field(default_factory=list)


def _resolve_source_type(item: MultiReportSourceItem) -> str:
    return "rtsp" if item.sensor_id else "video_file"


async def _default_video_understanding_fn(**kwargs):
    return await analyze_video(**kwargs)


async def _default_report_gen_fn(**kwargs):
    from vsa_agent.tools.report_gen import generate_multi_report

    return await generate_multi_report(**kwargs)


async def execute_multi_report_agent(
    report_input: MultiReportAgentInput,
    video_understanding_fn: VideoUnderstandingCallable | None = None,
    report_gen_fn: ReportGenCallable | None = None,
) -> AgentOutput:
    """Execute multi-source report generation flow."""
    if not report_input.sources:
        raise ValueError("multi_report_agent 至少需要一个 source")

    video_understanding = video_understanding_fn or _default_video_understanding_fn
    report_gen = report_gen_fn or _default_report_gen_fn

    sections: list[ReportSectionInput] = []
    for index, item in enumerate(report_input.sources, start=1):
        if not item.video_path and not item.sensor_id:
            raise ValueError("每个 source 必须提供 video_path 或 sensor_id")

        understanding = await video_understanding(
            video_path=item.video_path or "",
            query=report_input.query,
            source_type=_resolve_source_type(item),
            sensor_id=item.sensor_id,
        )
        source_name = item.sensor_id or item.video_path or f"source-{index}"
        sections.append(
            ReportSectionInput(
                section_title=f"事件 {index} - {source_name}",
                sensor_id=source_name,
                user_query=report_input.query,
                understanding_result=(
                    understanding if isinstance(understanding, dict) else understanding.model_dump()
                ),
            )
        )

    report = await report_gen(
        report_title=report_input.report_title,
        report_sections=sections,
    )
    report_dict = report if isinstance(report, dict) else report.model_dump()

    return AgentOutput(
        messages=[report_dict["summary"]] if report_dict.get("summary") else [],
        side_effects={
            "markdown_content": report_dict["markdown_content"],
            "downloads": report_dict["downloads"],
        },
        metadata={
            "report_type": "multi_video",
            "source_count": len(report_input.sources),
        },
        status="success",
    )


@register_tool(
    "multi_report_agent",
    description="Generate one markdown report from multiple uploaded videos or RTSP sensors.",
)
async def multi_report_agent_tool(
    sources: list[dict[str, str]] | None = None,
    report_title: str = "多视频聚合报告",
    query: str = "生成聚合报告",
) -> str:
    """Tool wrapper for multi-report generation."""
    normalized_sources = [MultiReportSourceItem(**source) for source in (sources or [])]
    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title=report_title,
            query=query,
            sources=normalized_sources,
        )
    )
    return str(result.side_effects.get("markdown_content", ""))
