"""ES query builders for video analytics.

Mirrors NVIDIA query_builders.py — builds Elasticsearch queries
for incident, frame, and behavior searches.
"""

from __future__ import annotations

from typing import Any


def build_incident_query(
    query: str,
    filters: dict[str, Any] | None = None,
    time_range: tuple[float, float] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Build an Elasticsearch query for incident search.

    Args:
        query: Natural language query string.
        filters: Optional field filters (e.g., {"severity": "high"}).
        time_range: Optional (start_sec, end_sec) time range.
        top_k: Maximum results to return.

    Returns:
        ES query dict.
    """
    must_clauses: list[dict] = [{"match": {"description": {"query": query, "fuzziness": "AUTO"}}}]

    if filters:
        for field, value in filters.items():
            must_clauses.append({"term": {field: value}})

    if time_range:
        must_clauses.append(
            {
                "range": {
                    "timestamp_sec": {
                        "gte": time_range[0],
                        "lte": time_range[1],
                    }
                }
            }
        )

    return {
        "size": top_k,
        "query": {"bool": {"must": must_clauses}},
        "sort": [{"timestamp_sec": {"order": "desc"}}],
    }


def build_frames_query(
    sensor_id: str,
    time_range: tuple[float, float],
    top_k: int = 50,
) -> dict[str, Any]:
    """Build an Elasticsearch query for frame retrieval.

    Args:
        sensor_id: Camera/sensor identifier.
        time_range: (start_sec, end_sec) time range.
        top_k: Maximum frames to return.

    Returns:
        ES query dict.
    """
    return {
        "size": top_k,
        "query": {
            "bool": {
                "must": [
                    {"term": {"sensor_id": sensor_id}},
                    {
                        "range": {
                            "timestamp_sec": {
                                "gte": time_range[0],
                                "lte": time_range[1],
                            }
                        }
                    },
                ]
            }
        },
        "sort": [{"timestamp_sec": {"order": "asc"}}],
    }


def build_behavior_query(
    behavior_type: str,
    confidence_min: float = 0.5,
    time_range: tuple[float, float] | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    """Build an Elasticsearch query for behavior search.

    Args:
        behavior_type: Type of behavior to search for.
        confidence_min: Minimum confidence threshold.
        time_range: Optional (start_sec, end_sec) time range.
        top_k: Maximum results to return.

    Returns:
        ES query dict.
    """
    must_clauses: list[dict] = [
        {"term": {"behavior_type": behavior_type}},
        {"range": {"confidence": {"gte": confidence_min}}},
    ]

    if time_range:
        must_clauses.append(
            {
                "range": {
                    "timestamp_sec": {
                        "gte": time_range[0],
                        "lte": time_range[1],
                    }
                }
            }
        )

    return {
        "size": top_k,
        "query": {"bool": {"must": must_clauses}},
        "sort": [{"confidence": {"order": "desc"}}],
    }
