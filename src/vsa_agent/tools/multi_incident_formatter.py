"""Format multiple incidents into stable markdown output."""

from __future__ import annotations

from typing import Any

from vsa_agent.data_models.report import ReportIncident
from vsa_agent.registry import register_tool


def _normalize_incident(item: ReportIncident | dict[str, Any]) -> ReportIncident:
    if isinstance(item, ReportIncident):
        return item
    return ReportIncident.model_validate(item)


def format_multi_incidents(
    incidents: list[ReportIncident | dict[str, Any]],
    heading: str = "事件列表",
) -> str:
    """Format incidents as a markdown section."""
    if not incidents:
        return f"## {heading}\n\n- 无事件"

    normalized = [_normalize_incident(item) for item in incidents]
    lines = [f"## {heading}", ""]
    for incident in normalized:
        time_window = ""
        if incident.start_timestamp or incident.end_timestamp:
            time_window = f" [{incident.start_timestamp} - {incident.end_timestamp}]"
        lines.append(
            f"- {incident.category}{time_window}: {incident.description} "
            f"(severity={incident.severity}, confidence={incident.confidence:.2f})"
        )
    return "\n".join(lines)


@register_tool(
    "multi_incident_formatter",
    description="Format multiple structured incidents into markdown output.",
)
async def multi_incident_formatter_tool(
    incidents: list[dict[str, Any]] | None = None,
    heading: str = "事件列表",
) -> str:
    """Tool wrapper for formatting multiple incidents."""
    return format_multi_incidents(incidents or [], heading=heading)
