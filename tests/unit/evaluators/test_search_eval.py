from vsa_agent.evaluators.data_models import ExpectedSearchHit
from vsa_agent.evaluators.search_eval import evaluate_search_output
from vsa_agent.tools.search import SearchOutput, SearchResult


def test_evaluate_search_output_scores_top_hit_and_hit_coverage():
    actual = SearchOutput(
        data=[
            SearchResult(
                video_name="cam-01.mp4",
                description="person enters loading area",
                start_time="2026-06-19T10:00:00",
                end_time="2026-06-19T10:00:10",
                sensor_id="cam-01",
                screenshot_url="",
                similarity=0.91,
                object_ids=["obj-1"],
            )
        ]
    )

    result = evaluate_search_output(
        actual,
        expected_hits=[
            ExpectedSearchHit(
                video_name="cam-01.mp4",
                description_terms=["person", "loading area"],
                sensor_id="cam-01",
            ),
        ],
    )

    assert result.evaluator_name == "search"
    assert result.score == 1.0
    assert result.passed is True
