"""Video analytics tool functions.

Provides high-level video analysis operations using the
video_analytics layer. Mirrors NVIDIA video_analytics/tools.py.
"""

from __future__ import annotations

import logging
from typing import Any

from vsa_agent.video_analytics.nvschema import Incident
from vsa_agent.video_analytics.utils import check_event_overlap, create_time_buckets

logger = logging.getLogger(__name__)


async def analyze_incident_timeline(
    incidents: list[Incident],
    bucket_duration_sec: float = 60.0,
) -> list[dict[str, Any]]:
    """Analyze an incident timeline, grouping events into time buckets.

    Args:
        incidents: List of incidents to analyze.
        bucket_duration_sec: Duration of each time bucket.

    Returns:
        List of bucket analysis dicts with incident summaries.
    """
    if not incidents:
        return []

    sorted_incidents = sorted(incidents, key=lambda i: i.timestamp_sec)
    time_start = sorted_incidents[0].timestamp_sec
    time_end = sorted_incidents[-1].timestamp_sec + sorted_incidents[-1].duration_sec

    buckets = create_time_buckets(time_start, time_end, bucket_duration_sec)
    results: list[dict[str, Any]] = []

    for bucket_start, bucket_end in buckets:
        bucket_incidents = [
            inc
            for inc in sorted_incidents
            if check_event_overlap(
                (inc.timestamp_sec, inc.timestamp_sec + inc.duration_sec),
                (bucket_start, bucket_end),
            )
        ]

        if bucket_incidents:
            results.append(
                {
                    "time_range": (bucket_start, bucket_end),
                    "incident_count": len(bucket_incidents),
                    "severity_distribution": _count_severities(bucket_incidents),
                    "incidents": [
                        {
                            "id": inc.id,
                            "description": inc.description,
                            "severity": inc.severity,
                            "category": inc.category,
                            "confidence": inc.confidence,
                        }
                        for inc in bucket_incidents
                    ],
                }
            )

    return results


def _count_severities(incidents: list[Incident]) -> dict[str, int]:
    """Count incidents by severity level.

    Args:
        incidents: List of incidents.

    Returns:
        Dict mapping severity → count.
    """
    counts: dict[str, int] = {}
    for inc in incidents:
        counts[inc.severity] = counts.get(inc.severity, 0) + 1
    return counts


async def summarize_incidents(
    incidents: list[Incident],
    max_incidents: int = 20,
) -> str:
    """Generate a text summary of incidents.

    Args:
        incidents: List of incidents to summarize.
        max_incidents: Maximum incidents to include in summary.

    Returns:
        Text summary string.
    """
    if not incidents:
        return "No incidents detected."

    top_incidents = sorted(incidents, key=lambda i: i.confidence, reverse=True)[:max_incidents]

    lines = [f"Found {len(incidents)} incidents (showing top {len(top_incidents)}):", ""]
    for i, inc in enumerate(top_incidents, 1):
        lines.append(
            f"{i}. [{inc.severity.upper()}] {inc.category}: {inc.description} "
            f"(t={inc.timestamp_sec:.1f}s, confidence={inc.confidence:.2f})"
        )

    return "\n".join(lines)
