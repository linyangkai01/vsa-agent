import json
from pathlib import Path

import pytest

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.evaluators import ExpectedEvent
from vsa_agent.evaluators import ExpectedReportSection
from vsa_agent.evaluators import ExpectedSearchHit
from vsa_agent.evaluators import evaluate_report_markdown
from vsa_agent.evaluators import evaluate_search_output
from vsa_agent.evaluators import evaluate_understanding_result
from vsa_agent.tools.search import SearchOutput


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "evaluator_regression.json"


def load_regression_cases() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def evaluate_case(case: dict):
    evaluator_type = case["evaluator_type"]

    if evaluator_type == "understanding":
        actual = UnderstandingResult.model_validate(case["actual"])
        expected_events = [ExpectedEvent.model_validate(item) for item in case["expected"].get("events", [])]
        return evaluate_understanding_result(
            actual,
            expected_summary_terms=case["expected"].get("summary_terms", []),
            expected_events=expected_events,
        )

    if evaluator_type == "search":
        actual = SearchOutput.model_validate(case["actual"])
        expected_hits = [ExpectedSearchHit.model_validate(item) for item in case["expected"].get("hits", [])]
        return evaluate_search_output(
            actual,
            expected_hits=expected_hits,
        )

    if evaluator_type == "report":
        expected_sections = [ExpectedReportSection.model_validate(item) for item in case["expected"].get("sections", [])]
        return evaluate_report_markdown(
            case["actual"]["markdown"],
            expected_sections=expected_sections,
            required_terms=case["expected"].get("required_terms", []),
        )

    raise ValueError(f"Unknown evaluator_type: {evaluator_type}")


def evaluate_case_by_name(case_name: str):
    for case in load_regression_cases():
        if case["name"] == case_name:
            return evaluate_case(case)
    raise KeyError(f"Unknown regression case: {case_name}")


def test_load_regression_cases_returns_three_cases():
    cases = load_regression_cases()

    assert len(cases) == 3
    assert {case["evaluator_type"] for case in cases} == {"understanding", "search", "report"}


@pytest.mark.parametrize("case_name", ["understanding-basic", "search-basic", "report-basic"])
def test_regression_case_passes(case_name):
    result = evaluate_case_by_name(case_name)

    assert result.passed is True
    assert result.score >= 1.0
