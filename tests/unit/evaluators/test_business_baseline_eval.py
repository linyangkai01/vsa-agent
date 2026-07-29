from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from vsa_agent.evaluators.business_baseline_eval import (
    evaluate_business_answer,
    evaluate_business_attempts,
    evaluate_business_search,
)
from vsa_agent.recorded_video.business_manifest import (
    ForbiddenConceptGroup,
    RequiredConceptGroup,
    load_business_manifest,
)
from vsa_agent.tools.search import SearchOutput, SearchResult


def _result(
    *,
    asset_id: str,
    start: datetime,
    end: datetime,
    segment_id: str = "segment-1",
    job_id: str = "job-1",
) -> SearchResult:
    return SearchResult(
        asset_id=asset_id,
        segment_id=segment_id,
        job_id=job_id,
        video_name="forklift.mp4",
        description="forklift operating near a pedestrian",
        start_time=start.isoformat().replace("+00:00", "Z"),
        end_time=end.isoformat().replace("+00:00", "Z"),
        sensor_id=asset_id,
        screenshot_url="/thumbnail",
        similarity=0.91,
        object_ids=[],
    )


def _required(group_id: str, alternatives: tuple[str, ...], negated: tuple[str, ...]) -> RequiredConceptGroup:
    return RequiredConceptGroup(
        group_id=group_id,
        alternatives=alternatives,
        negated_alternatives=negated,
    )


def _forbidden(
    group_id: str,
    alternatives: tuple[str, ...],
    negated: tuple[str, ...] = (),
) -> ForbiddenConceptGroup:
    return ForbiddenConceptGroup(
        group_id=group_id,
        alternatives=alternatives,
        negated_alternatives=negated,
    )


def test_answer_evaluation_matches_synonym_groups_without_language_contract() -> None:
    result = evaluate_business_answer(
        "A lift truck is operating close to a worker in the shared aisle.",
        required_concept_groups=(
            _required("forklift", ("forklift", "lift truck"), ("no forklift", "no lift truck")),
            _required("person", ("person", "worker", "pedestrian"), ("no person", "no worker")),
            _required("proximity", ("near", "close to", "shared aisle"), ("not near", "separated")),
        ),
        forbidden_concept_groups=(_forbidden("no_person", ("no worker is present",)),),
        minimum_coverage=0.8,
    )

    assert result.passed is True
    assert result.coverage == 1.0
    assert result.matched_group_ids == ("forklift", "person", "proximity")


def test_answer_evaluation_normalizes_gender_nouns_and_close_word_forms() -> None:
    result = evaluate_business_answer(
        "A woman stands beside the forklift; the workers are collaborating closely and one moves closer.",
        required_concept_groups=(
            _required("person", ("person", "people"), ("no person", "no people")),
            _required("close_range", ("close",), ("not close",)),
        ),
        forbidden_concept_groups=(),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ("person", "close_range")
    assert result.passed is True


def test_answer_evaluation_preserves_negation_after_word_form_normalization() -> None:
    result = evaluate_business_answer(
        "No woman is visible; the workers are not closer to each other.",
        required_concept_groups=(
            _required("person", ("person",), ("no person",)),
            _required("close_range", ("close",), ("not close",)),
        ),
        forbidden_concept_groups=(),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ()
    assert result.passed is False


def test_answer_evaluation_normalizes_missing_and_wearing_word_forms() -> None:
    result = evaluate_business_answer(
        "PPE is absent and hard hats are not worn by the workers.",
        required_concept_groups=(
            _required("noncompliance", ("missing", "not wearing"), ("nothing is missing", "properly worn")),
        ),
        forbidden_concept_groups=(),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ("noncompliance",)
    assert result.passed is True


def test_answer_evaluation_preserves_properly_worn_negation_after_normalization() -> None:
    result = evaluate_business_answer(
        "The required PPE is properly worn.",
        required_concept_groups=(_required("noncompliance", ("wearing",), ("properly worn",)),),
        forbidden_concept_groups=(),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ()
    assert result.passed is False


def test_answer_evaluation_fails_on_forbidden_conclusion_even_with_full_coverage() -> None:
    result = evaluate_business_answer(
        "A forklift and worker are close, but no worker is present.",
        required_concept_groups=(
            _required("forklift", ("forklift",), ("no forklift",)),
            _required("person", ("worker",), ("no worker",)),
        ),
        forbidden_concept_groups=(_forbidden("no_person", ("no worker is present",)),),
        minimum_coverage=0.8,
    )

    assert result.coverage == 0.5
    assert result.forbidden_matches == ("no_person",)
    assert result.passed is False


def test_answer_evaluation_ignores_a_forbidden_phrase_negated_in_the_same_clause() -> None:
    result = evaluate_business_answer(
        "A worker performs a routine task; 未见正在发生碰撞。",
        required_concept_groups=(
            _required("person", ("worker",), ("no worker",)),
            _required("routine", ("routine",), ("not routine",)),
        ),
        forbidden_concept_groups=(
            _forbidden(
                "collision",
                ("正在发生碰撞",),
                ("未见正在发生碰撞",),
            ),
        ),
        minimum_coverage=1.0,
    )

    assert result.forbidden_matches == ()
    assert result.passed is True


def test_answer_evaluation_uses_ascii_whole_word_boundaries() -> None:
    result = evaluate_business_answer(
        "Personal equipment is visible, but the area is otherwise unclear.",
        (_required("person", ("person",), ("no person",)),),
        (),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ()
    assert result.passed is False


def test_answer_evaluation_rejects_negated_concepts_in_the_same_clauses() -> None:
    result = evaluate_business_answer(
        "There is no person and no forklift; they are not near each other.",
        (
            _required("person", ("person",), ("no person",)),
            _required("forklift", ("forklift",), ("no forklift",)),
            _required("proximity", ("near",), ("not near",)),
        ),
        (),
        minimum_coverage=0.8,
    )

    assert result.coverage == 0.0
    assert result.missed_group_ids == ("person", "forklift", "proximity")
    assert result.passed is False


def test_answer_evaluation_allows_later_positive_evidence_in_a_new_clause() -> None:
    result = evaluate_business_answer(
        "Initially no person is visible; a person then enters the aisle.",
        (_required("person", ("person",), ("no person",)),),
        (),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ("person",)
    assert result.passed is True


def test_answer_evaluation_matches_explicit_cjk_phrases_with_clause_negation() -> None:
    result = evaluate_business_answer(
        "起初没有人员；随后一名人员进入叉车附近。",
        (
            _required("person", ("人员",), ("没有人员",)),
            _required("forklift", ("叉车",), ("没有叉车",)),
            _required("proximity", ("附近",), ("并不靠近",)),
        ),
        (),
        minimum_coverage=1.0,
    )

    assert result.matched_group_ids == ("person", "forklift", "proximity")
    assert result.passed is True


def test_answer_evaluation_reports_forbidden_group_once_for_any_alternative() -> None:
    result = evaluate_business_answer(
        "A collision is occurring and a worker has been struck.",
        (_required("person", ("worker",), ("no worker",)),),
        (_forbidden("collision", ("collision is occurring", "worker has been struck")),),
        minimum_coverage=1.0,
    )

    assert result.forbidden_matches == ("collision",)
    assert result.passed is False


def test_answer_evaluation_applies_word_boundaries_to_forbidden_groups() -> None:
    result = evaluate_business_answer(
        "The operation is collisionless and one worker remains visible.",
        (_required("person", ("worker",), ("no worker",)),),
        (_forbidden("collision", ("collision",)),),
        minimum_coverage=1.0,
    )

    assert result.forbidden_matches == ()
    assert result.passed is True


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
    assert result.matched_job_id == "job-1"
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


def test_search_evaluation_requires_stable_job_and_segment_identity() -> None:
    anchor = datetime(2026, 7, 28, tzinfo=UTC)
    result = evaluate_business_search(
        SearchOutput(
            data=[
                _result(
                    asset_id="expected-asset",
                    start=anchor,
                    end=anchor + timedelta(seconds=10),
                    segment_id="",
                    job_id="",
                )
            ]
        ),
        expected_asset_id="expected-asset",
        expected_start=anchor,
        expected_end=anchor + timedelta(seconds=10),
        top_k=5,
        tolerance_sec=5.0,
    )

    assert result.asset_found is True
    assert result.temporal_match is True
    assert result.matched_rank == 1
    assert result.matched_job_id is None
    assert result.matched_segment_id is None
    assert result.passed is False


def test_search_evaluation_does_not_accept_sensor_id_as_asset_identity() -> None:
    anchor = datetime(2026, 7, 28, tzinfo=UTC)
    candidate = _result(asset_id="expected-asset", start=anchor, end=anchor + timedelta(seconds=10))
    candidate.asset_id = None

    result = evaluate_business_search(
        SearchOutput(data=[candidate]),
        expected_asset_id="expected-asset",
        expected_start=anchor,
        expected_end=anchor + timedelta(seconds=10),
        top_k=5,
        tolerance_sec=5.0,
    )

    assert result.asset_found is False
    assert result.passed is False


def test_release_attempts_require_two_passes_and_zero_forbidden_conclusions() -> None:
    groups = (_required("forklift", ("forklift",), ("no forklift",)),)
    attempts = (
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("unclear scene", groups, (), minimum_coverage=0.8),
    )

    result = evaluate_business_attempts(attempts, required_passes=2)

    assert result.passed is True
    assert result.pass_count == 2


def test_release_attempts_fail_if_any_attempt_contains_forbidden_conclusion() -> None:
    groups = (_required("forklift", ("forklift",), ("no forklift",)),)
    attempts = (
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer("forklift", groups, (), minimum_coverage=0.8),
        evaluate_business_answer(
            "forklift collision",
            groups,
            (_forbidden("collision", ("collision",)),),
            minimum_coverage=0.8,
        ),
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
        case.forbidden_concept_groups,
        minimum_coverage=manifest.profiles["release"].minimum_concept_coverage,
    )

    assert result.passed is True
    assert result.matched_group_ids == ("multiple_people", "close_range", "collaboration")


def test_formal_routine_case_accepts_no_clear_incident_as_positive_evidence() -> None:
    manifest = load_business_manifest(Path("tests/fixtures/business_video_baseline/manifest.yaml"))
    case = next(item for item in manifest.cases if item.case_id == "ordinary-worker-activity")

    result = evaluate_business_answer(
        "A surveyor is working on a routine task, and no clear incident is visible.",
        case.required_concept_groups,
        case.forbidden_concept_groups,
        minimum_coverage=manifest.profiles["release"].minimum_concept_coverage,
    )

    assert result.passed is True
    assert result.matched_group_ids == ("person", "work", "routine")
