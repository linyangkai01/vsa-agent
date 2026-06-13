"""Shared understanding result data models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SharedContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(SharedContractModel):
    source_type: Literal["video_file", "rtsp"]
    video_path: str | None = None
    sensor_id: str | None = None
    frame_indices: list[int] = Field(default_factory=list)
    frame_timestamps: list[str] = Field(default_factory=list)
    start_timestamp: str | None = None
    end_timestamp: str | None = None

    @model_validator(mode="after")
    def validate_source_specific_fields(self) -> "EvidenceRef":
        if self.source_type == "video_file":
            if not self.video_path:
                raise ValueError("video_path is required when source_type is video_file")
            if self.sensor_id is not None:
                raise ValueError("sensor_id is not allowed when source_type is video_file")
        if self.source_type == "rtsp":
            if not self.sensor_id:
                raise ValueError("sensor_id is required when source_type is rtsp")
            if self.video_path is not None:
                raise ValueError("video_path is not allowed when source_type is rtsp")
        return self


class ObservationChunk(SharedContractModel):
    chunk_id: str
    start_timestamp: str
    end_timestamp: str
    prompt_used: str
    raw_model_output: str
    normalized_text: str
    thinking: str | None = None
    confidence: float | None = None
    evidence: EvidenceRef


class DetectedEvent(SharedContractModel):
    event_id: str
    label: str
    description: str
    start_timestamp: str
    end_timestamp: str
    actors: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    location_hint: str | None = None
    severity: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class UnderstandingResult(SharedContractModel):
    query: str
    source_type: Literal["video_file", "rtsp"]
    summary_text: str
    chunks: list[ObservationChunk] = Field(default_factory=list)
    events: list[DetectedEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummaryResult(SharedContractModel):
    query: str
    text_output: str
    structured_output: UnderstandingResult
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DetectedEvent",
    "EvidenceRef",
    "ObservationChunk",
    "SummaryResult",
    "UnderstandingResult",
]
