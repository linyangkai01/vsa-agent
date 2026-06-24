"""Deterministic evaluation helpers for understanding results."""

from __future__ import annotations

from collections.abc import Iterable

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.evaluators.data_models import EvaluationResult
from vsa_agent.evaluators.data_models import ExpectedEvent
from vsa_agent.evaluators.data_models import MetricScore


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _score_term_coverage(text: str, terms: Iterable[str]) -> tuple[float, list[str]]:
    normalized_text = _normalize_text(text)
    normalized_terms = [_normalize_text(term) for term in terms if term.strip()]
    if not normalized_terms:
        return 1.0, []

    matched = [term for term in normalized_terms if term in normalized_text]
    return len(matched) / len(normalized_terms), matched


def _event_matches(actual_event, expected_event: ExpectedEvent) -> bool:
    actual_label = _normalize_text(getattr(actual_event, "label", ""))
    actual_description = _normalize_text(getattr(actual_event, "description", ""))
    expected_label = _normalize_text(expected_event.label)
    if expected_label and expected_label != actual_label:
        return False

    for term in expected_event.description_terms:
        if _normalize_text(term) not in actual_description:
            return False

    if expected_event.start_timestamp and expected_event.start_timestamp != getattr(actual_event, "start_timestamp", None):
        return False
    if expected_event.end_timestamp and expected_event.end_timestamp != getattr(actual_event, "end_timestamp", None):
        return False
    return True


def evaluate_understanding_result(
    actual: UnderstandingResult,
    *,
    expected_summary_terms: list[str] | None = None,
    expected_events: list[ExpectedEvent] | None = None,
) -> EvaluationResult:
    """Score summary term coverage and expected event coverage."""

    summary_terms = expected_summary_terms or []
    events = expected_events or []

    summary_score, matched_terms = _score_term_coverage(actual.summary_text, summary_terms)

    matched_event_labels: list[str] = []
    if events:
        matched_count = 0
        for expected_event in events:
            if any(_event_matches(event, expected_event) for event in actual.events):
                matched_count += 1
                matched_event_labels.append(expected_event.label)
        event_score = matched_count / len(events)
    else:
        event_score = 1.0

    metrics = [
        MetricScore(
            name="summary_terms",
            score=summary_score,
            passed=summary_score >= 1.0,
            details={"matched_terms": matched_terms, "expected_terms": summary_terms},
        ),
        MetricScore(
            name="events",
            score=event_score,
            passed=event_score >= 1.0,
            details={"matched_events": matched_event_labels, "expected_event_count": len(events)},
        ),
    ]
    return EvaluationResult(
        evaluator_name="understanding",
        score=(summary_score + event_score) / 2.0,
        metrics=metrics,
    )
