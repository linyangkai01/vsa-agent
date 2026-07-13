"""Offline geolocation helpers for Phase 4."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from vsa_agent.registry import register_tool
from vsa_agent.video_analytics.nvschema import Incident, Location


def enrich_incidents_with_location(
    incidents: list[Incident],
    *,
    default_location_name: str = "",
    default_zone: str = "",
) -> list[Incident]:
    enriched: list[Incident] = []
    for incident in incidents:
        if incident.location is None:
            incident = replace(
                incident,
                location=Location(name=default_location_name, zone=default_zone),
            )
        enriched.append(incident)
    return enriched


def summarize_geolocation(incidents: list[Incident]) -> str:
    if not incidents:
        return "No location data available."

    counts = Counter(
        (
            (incident.location.name if incident.location else "") or "unknown",
            (incident.location.zone if incident.location else "") or "unknown",
        )
        for incident in incidents
    )
    lines = []
    for (location_name, zone), count in sorted(counts.items(), key=lambda item: item[0]):
        lines.append(f"{location_name} / {zone}: {count}")
    return "\n".join(lines)


@register_tool(
    "geolocation",
    description="Enrich incidents with default location metadata and summarize zones.",
)
async def geolocation_tool(
    incidents: list[dict] | None = None,
    default_location_name: str = "",
    default_zone: str = "",
) -> str:
    parsed = [Incident.model_validate(item) for item in (incidents or [])]
    enriched = enrich_incidents_with_location(
        parsed,
        default_location_name=default_location_name,
        default_zone=default_zone,
    )
    return summarize_geolocation(enriched)
