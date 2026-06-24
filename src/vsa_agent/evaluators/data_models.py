"""Shared data models for deterministic evaluation helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class MetricScore(BaseModel):
    """One evaluator metric and its supporting details."""

    name: str
    score: float
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Top-level evaluation result returned by deterministic evaluators."""

    evaluator_name: str
    score: float
    passed: bool | None = None
    metrics: list[MetricScore] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_passed(self) -> "EvaluationResult":
        if self.passed is None:
            self.passed = all(metric.passed for metric in self.metrics) if self.metrics else self.score >= 1.0
        return self


class ExpectedEvent(BaseModel):
    """Expected event fixture for understanding evaluation."""

    label: str
    description_terms: list[str] = Field(default_factory=list)
    start_timestamp: str | None = None
    end_timestamp: str | None = None


class ExpectedSearchHit(BaseModel):
    """Expected hit fixture for search evaluation."""

    video_name: str
    description_terms: list[str] = Field(default_factory=list)
    sensor_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class ExpectedReportSection(BaseModel):
    """Expected report section fixture for markdown evaluation."""

    title: str
    required_terms: list[str] = Field(default_factory=list)
