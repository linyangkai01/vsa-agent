"""Deterministic evaluation helpers for search outputs."""

from __future__ import annotations

from vsa_agent.evaluators.data_models import EvaluationResult, ExpectedSearchHit, MetricScore
from vsa_agent.tools.search import SearchOutput, SearchResult


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _hit_matches(actual: SearchResult, expected: ExpectedSearchHit) -> bool:
    if actual.video_name != expected.video_name:
        return False
    if expected.sensor_id and actual.sensor_id != expected.sensor_id:
        return False
    if expected.start_time and actual.start_time != expected.start_time:
        return False
    if expected.end_time and actual.end_time != expected.end_time:
        return False

    description = _normalize_text(actual.description)
    for term in expected.description_terms:
        if _normalize_text(term) not in description:
            return False
    return True


def evaluate_search_output(
    actual: SearchOutput,
    *,
    expected_hits: list[ExpectedSearchHit] | None = None,
) -> EvaluationResult:
    """Score top-hit correctness and expected-hit coverage."""

    hits = expected_hits or []
    top_hit_score = 1.0
    matched_hits: list[str] = []

    if hits:
        top_hit_score = 0.0
        if actual.data and _hit_matches(actual.data[0], hits[0]):
            top_hit_score = 1.0

        matched_count = 0
        for expected in hits:
            if any(_hit_matches(candidate, expected) for candidate in actual.data):
                matched_count += 1
                matched_hits.append(expected.video_name)
        coverage_score = matched_count / len(hits)
    else:
        coverage_score = 1.0

    metrics = [
        MetricScore(
            name="top_hit",
            score=top_hit_score,
            passed=top_hit_score >= 1.0,
            details={"expected_video_name": hits[0].video_name if hits else None},
        ),
        MetricScore(
            name="hit_coverage",
            score=coverage_score,
            passed=coverage_score >= 1.0,
            details={"matched_hits": matched_hits, "expected_hit_count": len(hits)},
        ),
    ]
    return EvaluationResult(
        evaluator_name="search",
        score=(top_hit_score + coverage_score) / 2.0,
        metrics=metrics,
    )
