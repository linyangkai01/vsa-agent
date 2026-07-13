"""NVIDIA VSS schema data models for video analytics.

Mirrors NVIDIA nvschema.py — defines Incident, Location, Place data models
for structured video analysis output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Location:
    """Location information for a video event."""

    name: str = ""
    description: str = ""
    coordinates: tuple[float, float] | None = None  # (lat, lon)
    zone: str = ""  # e.g., "red_zone", "loading_dock"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Place:
    """Place information — a specific area within a location."""

    name: str = ""
    description: str = ""
    location: Location | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Incident:
    """A detected incident in video footage.

    Mirrors NVIDIA Incident data model with full schema alignment.
    """

    id: str = ""
    timestamp_sec: float = 0.0
    duration_sec: float = 0.0
    description: str = ""
    severity: str = "unknown"  # low, medium, high, critical
    category: str = ""  # e.g., "no_helmet", "fall", "fire", "intrusion"
    subcategory: str = ""
    location: Location | None = None
    place: Place | None = None
    confidence: float = 0.0
    detected_objects: list[str] = field(default_factory=list)
    detected_actions: list[str] = field(default_factory=list)
    frame_indices: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
