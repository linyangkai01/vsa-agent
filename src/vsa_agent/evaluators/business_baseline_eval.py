"""Deterministic answer, search, and attempt gates for business-video regression."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from vsa_agent.recorded_video.business_manifest import ConceptGroup
from vsa_agent.tools.search import SearchOutput


class _ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BusinessAnswerEvaluation(_ResultModel):
    coverage: float = Field(ge=0.0, le=1.0)
    matched_group_ids: tuple[str, ...]
    missed_group_ids: tuple[str, ...]
    forbidden_matches: tuple[str, ...]
    passed: bool


class BusinessSearchEvaluation(_ResultModel):
    asset_found: bool
    temporal_match: bool
    matched_rank: int | None = Field(default=None, ge=1)
    matched_segment_id: str | None = None
    passed: bool


class BusinessAttemptEvaluation(_ResultModel):
    attempt_count: int = Field(ge=1)
    required_passes: int = Field(ge=1)
    pass_count: int = Field(ge=0)
    forbidden_attempts: tuple[int, ...]
    passed: bool


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def evaluate_business_answer(
    answer: str,
    required_concept_groups: tuple[ConceptGroup, ...],
    forbidden_concepts: tuple[str, ...],
    *,
    minimum_coverage: float,
) -> BusinessAnswerEvaluation:
    """Evaluate one answer without imposing a language or fixed-sentence contract."""

    if not 0.0 <= minimum_coverage <= 1.0:
        raise ValueError("minimum_coverage must be between 0 and 1")
    if not required_concept_groups:
        raise ValueError("at least one required concept group is required")
    normalized = _normalize_text(answer)
    matched = tuple(
        group.group_id
        for group in required_concept_groups
        if any(_normalize_text(alternative) in normalized for alternative in group.alternatives)
    )
    matched_set = set(matched)
    missed = tuple(group.group_id for group in required_concept_groups if group.group_id not in matched_set)
    forbidden = tuple(concept for concept in forbidden_concepts if _normalize_text(concept) in normalized)
    coverage = len(matched) / len(required_concept_groups)
    return BusinessAnswerEvaluation(
        coverage=coverage,
        matched_group_ids=matched,
        missed_group_ids=missed,
        forbidden_matches=forbidden,
        passed=coverage >= minimum_coverage and not forbidden,
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def evaluate_business_search(
    output: SearchOutput,
    *,
    expected_asset_id: str,
    expected_start: datetime,
    expected_end: datetime,
    top_k: int,
    tolerance_sec: float,
) -> BusinessSearchEvaluation:
    """Require the expected run-scoped asset and an overlapping event window in Top-K."""

    if top_k < 1 or tolerance_sec < 0:
        raise ValueError("top_k must be positive and tolerance_sec must be non-negative")
    if expected_start.tzinfo is None or expected_end.tzinfo is None or expected_end <= expected_start:
        raise ValueError("expected search window must be an increasing timezone-aware interval")
    expanded_start = expected_start - timedelta(seconds=tolerance_sec)
    expanded_end = expected_end + timedelta(seconds=tolerance_sec)
    asset_found = False
    for rank, result in enumerate(output.data[:top_k], start=1):
        candidate_asset_id = result.asset_id or result.sensor_id
        if candidate_asset_id != expected_asset_id:
            continue
        asset_found = True
        actual_start = _parse_timestamp(result.start_time)
        actual_end = _parse_timestamp(result.end_time)
        temporal_match = bool(
            actual_start
            and actual_end
            and actual_end >= actual_start
            and actual_end >= expanded_start
            and actual_start <= expanded_end
        )
        if temporal_match:
            return BusinessSearchEvaluation(
                asset_found=True,
                temporal_match=True,
                matched_rank=rank,
                matched_segment_id=result.segment_id or None,
                passed=True,
            )
    return BusinessSearchEvaluation(
        asset_found=asset_found,
        temporal_match=False,
        passed=False,
    )


def evaluate_business_attempts(
    attempts: tuple[BusinessAnswerEvaluation, ...],
    *,
    required_passes: int,
) -> BusinessAttemptEvaluation:
    """Aggregate model attempts while requiring zero forbidden conclusions."""

    if not attempts:
        raise ValueError("at least one answer attempt is required")
    if required_passes < 1 or required_passes > len(attempts):
        raise ValueError("required_passes must be between one and the attempt count")
    pass_count = sum(attempt.passed for attempt in attempts)
    forbidden_attempts = tuple(index for index, attempt in enumerate(attempts, start=1) if attempt.forbidden_matches)
    return BusinessAttemptEvaluation(
        attempt_count=len(attempts),
        required_passes=required_passes,
        pass_count=pass_count,
        forbidden_attempts=forbidden_attempts,
        passed=pass_count >= required_passes and not forbidden_attempts,
    )


__all__ = [
    "BusinessAnswerEvaluation",
    "BusinessAttemptEvaluation",
    "BusinessSearchEvaluation",
    "evaluate_business_answer",
    "evaluate_business_attempts",
    "evaluate_business_search",
]
