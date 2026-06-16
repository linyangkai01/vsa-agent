"""Incident normalization helpers for Phase 4."""

from __future__ import annotations

import json
from typing import Any

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult
from vsa_agent.video_analytics.nvschema import Incident


def understanding_to_incidents(result: UnderstandingResult) -> list[Incident]:
    incidents: list[Incident] = []
    for index, event in enumerate(result.events, start=1):
        incidents.append(
            Incident(
                id=event.event_id or f"incident-{index}",
                timestamp_sec=0.0,
                duration_sec=0.0,
                description=event.description,
                severity="medium",
                category=event.label or "incident",
                confidence=float(getattr(event, "confidence", 0.0) or 0.0),
                metadata={
                    "query": result.query,
                    "source_type": result.source_type,
                    "start_timestamp": event.start_timestamp,
                    "end_timestamp": event.end_timestamp,
                },
            )
        )
    return incidents


def search_output_to_incidents(search_output: SearchOutput | list[SearchResult]) -> list[Incident]:
    results = search_output.data if hasattr(search_output, "data") else search_output
    incidents: list[Incident] = []
    for index, item in enumerate(results, start=1):
        incidents.append(
            Incident(
                id=f"search-incident-{index}",
                timestamp_sec=0.0,
                duration_sec=0.0,
                description=item.description,
                severity="medium",
                category="search_hit",
                confidence=float(item.similarity),
                metadata={
                    "video_name": item.video_name,
                    "sensor_id": item.sensor_id,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "screenshot_url": item.screenshot_url,
                },
            )
        )
    return incidents


def incidents_to_tagged_json(incidents: list[Incident]) -> str:
    payload: dict[str, Any] = {
        "incidents": [
            {
                "id": incident.id,
                "timestamp_sec": incident.timestamp_sec,
                "duration_sec": incident.duration_sec,
                "description": incident.description,
                "severity": incident.severity,
                "category": incident.category,
                "subcategory": incident.subcategory,
                "confidence": incident.confidence,
                "metadata": incident.metadata,
            }
            for incident in incidents
        ]
    }
    return "<incidents>\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n</incidents>"


@register_tool(
    "incidents",
    description="Normalize understanding or search results into structured incidents.",
)
async def incidents_tool(*, understanding_result: dict[str, Any] | None = None, search_output: dict[str, Any] | None = None) -> str:
    incidents: list[Incident] = []
    if understanding_result is not None:
        incidents.extend(understanding_to_incidents(UnderstandingResult.model_validate(understanding_result)))
    if search_output is not None:
        incidents.extend(search_output_to_incidents(SearchOutput.model_validate(search_output)))
    return incidents_to_tagged_json(incidents)

