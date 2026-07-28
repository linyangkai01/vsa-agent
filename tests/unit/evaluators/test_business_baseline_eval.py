from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from vsa_agent.evaluators.business_baseline_eval import (
    evaluate_business_answer,
    evaluate_business_attempts,
    evaluate_business_search,
)
from vsa_agent.recorded_video.business_manifest import ConceptGroup, load_business_manifest
from vsa_agent.tools.search import SearchOutput, SearchResult


def _result(
    *,
    asset_id: str,
    start: datetime,
    end: datetime,
    segment_id: str = "segment-1",
) -> SearchResult:
    return SearchResult(
        asset_id=asset_id,
        segment_id=segment_id,
        job_id="job-1",
        video_name="forklift.mp4",
        description="forklift operating near a pedestrian",
        start_time=start.isoformat().replace("+00:00", "Z"),
        end_time=end.isoformat().replace("+00:00", "Z"),
        sensor_id=asset_id,
        screenshot_url="/thumbnail",
        similarity=0.91,
        object_ids=[],
    )


def test_answer_evaluation_matches_synonym_groups_without_language_contract() -> None:
    result = evaluate_business_answer(
        "A lift truck is operating close to a worker in the shared aisle.",
        required_concept_groups=(
            ConceptGroup(group_id="forklift", alternatives=("forklift", "lift truck")),
            ConceptGroup(group_id="person", alternatives=("person", "worker", "pedestrian")),
            ConceptGroup(group_id="proximity", alternatives=("near", "close to", "shared aisle")),
        ),
        forbidden_concepts=("no worker is present",),
        minimum_coverage=0.8,
    )

    assert result.passed is True
    assert result.coverage == 1.0
    assert result.matched_group_ids == ("forklift", "person", "proximity")


def test_answer_evaluation_fails_on_forbidden_conclusion_even_with_full_coverage() -> None:
    result = evaluate_business_answer(
        "A forklift and worker are close, but no worker is present.",
        required_concept_groups=(
            ConceptGroup(group_id="forklift", alternatives=("forklift",)),
            ConceptGroup(group_id="person", alternatives=("worker",)),
        ),
        forbidden_concepts=("no worker is present",),
        minimum_coverage=0.8,
    )

    assert result.coverage == 1.0
    assert result.forbidden_matches == ("no worker is present",)
    assert result.passed is False


def test_search_evaluation_accepts_expected_asset_in_top_five_with_temporal_overlap() -> None:
    anchor = datetime(2026, 7, 28, tzinfo=UTC)
    wrong = _result(asset_id="other-asset", start=anchor, end=anchor + timedelta(seconds=10))
    expected = _result(
        asset_id="expected-asset",
        start=anchor + timedelta(seconds=24),
        end=anchor + timedelta(seconds=34),
    )

    result = evaluate_business_search(
        SearchOutput(data=[wrong, expected]),
        expected_asset_id="expected-asset",
        expected_start=anchor + timedelta(seconds=20),
        expected_end=anchor + timedelta(seconds=30),
        top_k=5,
        tolerance_sec=5.0,
    )

    assert result.passed is True
    assert result.matched_rank == 2
    assert result.matched_segment_id == "segment-1"


def test_search_evaluation_rejects_correct_asset_outside_expected_time_window() -> None:
    anchor = datetime(2026, 7, 28, tzinfo=UTC)
    result = evaluate_business_search(
        SearchOutput(
            data=[
                _result(
                    asset_id="expected-asset",
                    start=anchor + timedelta(seconds=40),
                    end=anchor + timedelta(seconds=50),
                )
            ]
        ),
        expected_asset_id="expected-asset",
        expected_start=anchor + timedelta(seconds=20),
        expected_end=anchor + timedelta(seconds=30),
        top_k=5,
        tolerance_sec=5.0,
    )

    assert result.asset_found is True
    assert result.temporal_match is False
    assert result.passed is False


def test_release_attempts_require_two_passes_and_zero_forbidden_conclusions() -> None:
    groups = (ConceptGroup(group_id="forklift", alternatives=("forklift",)),)
    attempts = (
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("unclear scene", groups, (), minimum_coverage=0.8),
    )

    result = evaluate_business_attempts(attempts, required_passes=2)

    assert result.passed is True
    assert result.pass_count == 2


def test_release_attempts_fail_if_any_attempt_contains_forbidden_conclusion() -> None:
    groups = (ConceptGroup(group_id="forklift", alternatives=("forklift",)),)
    attempts = (
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("forklift collision", groups, ("collision",), minimum_coverage=0.8),
    )

    result = evaluate_business_attempts(attempts, required_passes=2)

    assert result.pass_count == 2
    assert result.forbidden_attempts == (3,)
    assert result.passed is False


def test_formal_collaboration_case_accepts_observed_coordination_wording() -> None:
    manifest = load_business_manifest(Path("tests/fixtures/business_video_baseline/manifest.yaml"))
    case = next(item for item in manifest.cases if item.case_id == "worker-close-collaboration")

    result = evaluate_business_answer(
        "Three workers coordinate a common task at close range in a shared work area.",
        case.required_concept_groups,
        case.forbidden_concepts,
        minimum_coverage=manifest.profiles["release"].minimum_concept_coverage,
    )

    assert result.passed is True
    assert result.matched_group_ids == ("multiple_people", "close_range", "collaboration")
