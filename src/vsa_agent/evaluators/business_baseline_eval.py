"""Deterministic answer, search, and attempt gates for business-video regression."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from vsa_agent.recorded_video.business_manifest import ForbiddenConceptGroup, RequiredConceptGroup
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
    matched_job_id: str | None = None
    matched_segment_id: str | None = None
    passed: bool


class BusinessAttemptEvaluation(_ResultModel):
    attempt_count: int = Field(ge=1)
    required_passes: int = Field(ge=1)
    pass_count: int = Field(ge=0)
    forbidden_attempts: tuple[int, ...]
    passed: bool


_CANONICAL_TOKEN_ALIASES = {
    "absence": "missing",
    "absent": "missing",
    "man": "person",
    "men": "people",
    "woman": "person",
    "women": "people",
    "individual": "person",
    "individuals": "people",
    "worn": "wearing",
    "closely": "close",
    "closer": "close",
    "closest": "close",
    "work": "working",
}
_CANONICAL_TOKEN_PATTERN = re.compile(
    rf"(?<![a-z0-9_])({'|'.join(map(re.escape, _CANONICAL_TOKEN_ALIASES))})(?![a-z0-9_])"
)
_CANONICAL_PHRASE_ALIASES = (
    (
        re.compile(
            r"(?<![a-z0-9_])(?:no visible|no specific|lack of specific) "
            r"(?:personal protective equipment|ppe)"
            r"(?![a-z0-9_]|\s+(?:issue|problem|violation)\b)"
        ),
        "missing ppe",
    ),
)
_ASCII_PLURAL_FORMS = {
    "operator": "operators",
    "pedestrian": "pedestrians",
    "person": "people",
    "surveyor": "surveyors",
    "worker": "workers",
}


def _normalize_text(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    normalized = normalized.replace("-", " ")
    for pattern, replacement in _CANONICAL_PHRASE_ALIASES:
        normalized = pattern.sub(replacement, normalized)
    return _CANONICAL_TOKEN_PATTERN.sub(lambda match: _CANONICAL_TOKEN_ALIASES[match.group(1)], normalized)


_CLAUSE_BOUNDARY = re.compile(r"[.!?;|\n\r\u3002\uff01\uff1f\uff1b]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _split_clauses(value: str) -> tuple[str, ...]:
    return tuple(clause for part in _CLAUSE_BOUNDARY.split(value) if (clause := _normalize_text(part)))


def _contains_phrase(text: str, phrase: str) -> bool:
    """Match CJK literally and ASCII on whole word or phrase boundaries."""

    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if _CJK.search(normalized_phrase):
        return normalized_phrase in text
    alternatives = [normalized_phrase]
    if plural := _ASCII_PLURAL_FORMS.get(normalized_phrase):
        alternatives.append(plural)
    elif normalized_phrase.startswith("no "):
        singular = normalized_phrase.removeprefix("no ")
        if plural := _ASCII_PLURAL_FORMS.get(singular):
            alternatives.append(f"no {plural}")
    pattern = rf"(?<![a-z0-9_])(?:{'|'.join(map(re.escape, alternatives))})(?![a-z0-9_])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _required_group_matches(clauses: tuple[str, ...], group: RequiredConceptGroup) -> bool:
    for clause in clauses:
        if not any(_contains_phrase(clause, alternative) for alternative in group.alternatives):
            continue
        if any(_contains_phrase(clause, negated) for negated in group.negated_alternatives):
            continue
        return True
    return False


def _forbidden_group_matches(clauses: tuple[str, ...], group: ForbiddenConceptGroup) -> bool:
    for clause in clauses:
        if not any(_contains_phrase(clause, alternative) for alternative in group.alternatives):
            continue
        if any(_contains_phrase(clause, negated) for negated in group.negated_alternatives):
            continue
        return True
    return False


def evaluate_business_answer(
    answer: str,
    required_concept_groups: tuple[RequiredConceptGroup, ...],
    forbidden_concept_groups: tuple[ForbiddenConceptGroup, ...],
    *,
    minimum_coverage: float,
) -> BusinessAnswerEvaluation:
    """Evaluate one answer without imposing a language or fixed-sentence contract."""

    if not 0.0 <= minimum_coverage <= 1.0:
        raise ValueError("minimum_coverage must be between 0 and 1")
    if not required_concept_groups:
        raise ValueError("at least one required concept group is required")
    clauses = _split_clauses(answer)
    matched = tuple(group.group_id for group in required_concept_groups if _required_group_matches(clauses, group))
    matched_set = set(matched)
    missed = tuple(group.group_id for group in required_concept_groups if group.group_id not in matched_set)
    forbidden = tuple(group.group_id for group in forbidden_concept_groups if _forbidden_group_matches(clauses, group))
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
    temporal_candidate: tuple[int, str | None, str | None] | None = None
    for rank, result in enumerate(output.data[:top_k], start=1):
        if not result.asset_id or result.asset_id != expected_asset_id:
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
            job_id = result.job_id or None
            segment_id = result.segment_id or None
            if temporal_candidate is None:
                temporal_candidate = (rank, job_id, segment_id)
            if not job_id or not segment_id:
                continue
            return BusinessSearchEvaluation(
                asset_found=True,
                temporal_match=True,
                matched_rank=rank,
                matched_job_id=job_id,
                matched_segment_id=segment_id,
                passed=True,
            )
    if temporal_candidate is not None:
        rank, job_id, segment_id = temporal_candidate
        return BusinessSearchEvaluation(
            asset_found=True,
            temporal_match=True,
            matched_rank=rank,
            matched_job_id=job_id,
            matched_segment_id=segment_id,
            passed=False,
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
