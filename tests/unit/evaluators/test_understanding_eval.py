from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.evaluators.data_models import EvaluationResult
from vsa_agent.evaluators.data_models import ExpectedEvent
from vsa_agent.evaluators.data_models import MetricScore
from vsa_agent.evaluators.understanding_eval import evaluate_understanding_result


def test_evaluation_result_computes_pass_flag_from_metric_scores():
    result = EvaluationResult(
        evaluator_name="demo",
        score=0.75,
        metrics=[
            MetricScore(name="summary", score=1.0, passed=True),
            MetricScore(name="events", score=0.5, passed=False),
        ],
    )

    assert result.passed is False
    assert result.metrics[0].name == "summary"


def test_evaluate_understanding_result_scores_summary_and_event_coverage():
    actual = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person enters loading area and stops near forklift",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="event-1",
                label="loading area",
                description="person stops near forklift",
                start_timestamp="2026-06-19T10:00:00",
                end_timestamp="2026-06-19T10:00:10",
                evidence=[
                    EvidenceRef(
                        source_type="video_file",
                        video_path="clip.mp4",
                    )
                ],
            )
        ],
    )

    result = evaluate_understanding_result(
        actual,
        expected_summary_terms=["person", "forklift"],
        expected_events=[
            ExpectedEvent(label="loading area", description_terms=["stops"]),
        ],
    )

    assert result.evaluator_name == "understanding"
    assert result.score == 1.0
    assert {metric.name for metric in result.metrics} == {"summary_terms", "events"}
