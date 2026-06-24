from vsa_agent.evaluators.data_models import ExpectedReportSection
from vsa_agent.evaluators.report_eval import evaluate_report_markdown


def test_evaluate_report_markdown_scores_required_sections_and_terms():
    markdown = "# Report\n\n## Summary\nperson near forklift\n\n## Timeline\n- event"

    result = evaluate_report_markdown(
        markdown,
        expected_sections=[
            ExpectedReportSection(title="Summary", required_terms=["person"]),
            ExpectedReportSection(title="Timeline", required_terms=["event"]),
        ],
        required_terms=["forklift"],
    )

    assert result.evaluator_name == "report"
    assert result.score == 1.0
    assert result.passed is True
