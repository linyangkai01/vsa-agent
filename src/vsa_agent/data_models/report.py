"""Report domain structured models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from vsa_agent.data_models.understanding import UnderstandingResult


class ReportIncident(BaseModel):
    incident_id: str
    category: str
    description: str
    severity: str = "medium"
    confidence: float = 0.0
    start_timestamp: str = ""
    end_timestamp: str = ""
    location_name: str = ""
    zone_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportSection(BaseModel):
    section_id: str
    section_title: str
    source_name: str
    source_type: str
    user_query: str
    summary_text: str
    understanding_result: UnderstandingResult | dict[str, Any]
    incidents: list[ReportIncident] = Field(default_factory=list)
    location_summary: str = ""
    validation_feedback: list[str] = Field(default_factory=list)


class StructuredReport(BaseModel):
    report_title: str
    report_type: Literal["single_video", "multi_video"]
    user_query: str
    sections: list[ReportSection] = Field(default_factory=list)
    global_summary: str = ""
    global_validation_feedback: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
