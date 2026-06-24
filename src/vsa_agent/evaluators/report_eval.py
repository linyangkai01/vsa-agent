"""Deterministic evaluation helpers for generated markdown reports."""

from __future__ import annotations

from vsa_agent.evaluators.data_models import EvaluationResult
from vsa_agent.evaluators.data_models import ExpectedReportSection
from vsa_agent.evaluators.data_models import MetricScore


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _contains_term(text: str, term: str) -> bool:
    return _normalize_text(term) in _normalize_text(text)


def _section_matches(markdown: str, expected_section: ExpectedReportSection) -> bool:
    section_marker = f"## {expected_section.title}"
    if section_marker not in markdown:
        return False

    if not expected_section.required_terms:
        return True

    after_marker = markdown.split(section_marker, 1)[1]
    next_section_index = after_marker.find("\n## ")
    section_body = after_marker if next_section_index == -1 else after_marker[:next_section_index]
    return all(_contains_term(section_body, term) for term in expected_section.required_terms)


def evaluate_report_markdown(
    markdown: str,
    *,
    expected_sections: list[ExpectedReportSection] | None = None,
    required_terms: list[str] | None = None,
) -> EvaluationResult:
    """Score required section presence and global term coverage."""

    sections = expected_sections or []
    terms = required_terms or []

    matched_sections: list[str] = []
    if sections:
        matched_count = 0
        for section in sections:
            if _section_matches(markdown, section):
                matched_count += 1
                matched_sections.append(section.title)
        section_score = matched_count / len(sections)
    else:
        section_score = 1.0

    matched_terms = [term for term in terms if _contains_term(markdown, term)]
    term_score = (len(matched_terms) / len(terms)) if terms else 1.0

    metrics = [
        MetricScore(
            name="sections",
            score=section_score,
            passed=section_score >= 1.0,
            details={"matched_sections": matched_sections, "expected_section_count": len(sections)},
        ),
        MetricScore(
            name="required_terms",
            score=term_score,
            passed=term_score >= 1.0,
            details={"matched_terms": matched_terms, "expected_terms": terms},
        ),
    ]
    return EvaluationResult(
        evaluator_name="report",
        score=(section_score + term_score) / 2.0,
        metrics=metrics,
    )
