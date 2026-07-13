"""Video analytics layer for vsa-agent.

Provides video search, analysis, and embedding operations.
Mirrors NVIDIA video_analytics module structure.
"""

from vsa_agent.video_analytics.interface import VideoAnalyticsInterface
from vsa_agent.video_analytics.nvschema import Incident, Location, Place
from vsa_agent.video_analytics.query_builders import (
    build_behavior_query,
    build_frames_query,
    build_incident_query,
)
from vsa_agent.video_analytics.tools import (
    analyze_incident_timeline,
    summarize_incidents,
)
from vsa_agent.video_analytics.utils import (
    check_event_overlap,
    create_time_buckets,
    merge_overlapping_events,
)

__all__ = [
    "Incident",
    "Location",
    "Place",
    "VideoAnalyticsInterface",
    "build_incident_query",
    "build_frames_query",
    "build_behavior_query",
    "create_time_buckets",
    "check_event_overlap",
    "merge_overlapping_events",
    "analyze_incident_timeline",
    "summarize_incidents",
]
