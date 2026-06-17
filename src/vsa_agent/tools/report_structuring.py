"""Structured report assembly helpers."""

from __future__ import annotations

from typing import Any

from vsa_agent.data_models.report import ReportIncident
from vsa_agent.data_models.report import ReportSection
from vsa_agent.data_models.report import StructuredReport
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.geolocation import summarize_geolocation
from vsa_agent.tools.incidents import understanding_to_incidents
from vsa_agent.video_analytics.nvschema import Incident


def _to_geo_incident(report_incident: ReportIncident) -> Incident:
    return Incident(
        id=report_incident.incident_id,
        description=report_incident.description,
        severity=report_incident.severity,
        category=report_incident.category,
        confidence=report_incident.confidence,
    )


def normalize_understanding_result(
    *,
    understanding_result: UnderstandingResult | dict[str, Any],
    user_query: str,
    source_type: str,
) -> UnderstandingResult:
    if isinstance(understanding_result, UnderstandingResult):
        return understanding_result

    normalized_events = []
    for index, item in enumerate(understanding_result.get("events", []), start=1):
        if isinstance(item, DetectedEvent):
            normalized_events.append(item.model_dump())
            continue

        normalized_events.append(
            {
                "event_id": str(item.get("event_id", f"event-{index}")),
                "label": str(item.get("label", "incident")),
                "description": str(item.get("description", "")),
                "start_timestamp": str(item.get("start_timestamp", "")),
                "end_timestamp": str(item.get("end_timestamp", "")),
                "actors": list(item.get("actors", [])),
                "objects": list(item.get("objects", [])),
                "location_hint": item.get("location_hint"),
                "severity": item.get("severity"),
                "evidence": list(item.get("evidence", [])),
            }
        )

    return UnderstandingResult.model_validate(
        {
            "query": str(understanding_result.get("query", user_query)),
            "source_type": str(understanding_result.get("source_type", source_type)),
            "summary_text": str(understanding_result.get("summary_text", "")),
            "chunks": list(understanding_result.get("chunks", [])),
            "events": normalized_events,
            "metadata": dict(understanding_result.get("metadata", {})),
        }
    )


def build_single_section_report(
    *,
    source_name: str,
    source_type: str,
    user_query: str,
    understanding_result: UnderstandingResult | dict[str, Any],
    section_title: str | None = None,
) -> StructuredReport:
    parsed_understanding = normalize_understanding_result(
        understanding_result=understanding_result,
        user_query=user_query,
        source_type=source_type,
    )

    incidents = [
        ReportIncident(
            incident_id=item.id,
            category=item.category,
            description=item.description,
            severity=item.severity,
            confidence=item.confidence,
            start_timestamp=str(item.metadata.get("start_timestamp", "")),
            end_timestamp=str(item.metadata.get("end_timestamp", "")),
            metadata=item.metadata,
        )
        for item in understanding_to_incidents(parsed_understanding)
    ]

    section = ReportSection(
        section_id=f"{source_name}-section",
        section_title=section_title or f"事件 - {source_name}",
        source_name=source_name,
        source_type=source_type,
        user_query=user_query,
        summary_text=parsed_understanding.summary_text,
        understanding_result=parsed_understanding,
        incidents=incidents,
        location_summary=summarize_geolocation([_to_geo_incident(item) for item in incidents]),
    )
    return StructuredReport(
        report_title=user_query,
        report_type="single_video",
        user_query=user_query,
        sections=[section],
        global_summary=parsed_understanding.summary_text,
    )
