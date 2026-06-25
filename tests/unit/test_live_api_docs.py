from pathlib import Path


def test_live_api_validation_doc_mentions_required_env_and_commands():
    doc = Path("docs/testing/live-api-validation.md").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" in doc
    assert "LIVE_API_KEY" in doc
    assert "LIVE_API_BASE_URL" in doc
    assert "LIVE_API_MODEL" in doc
    assert "dashscope.aliyuncs.com/compatible-mode/v1" in doc
    assert "tests/acceptance/test_evaluator_regression.py" in doc
    assert "tests/acceptance/test_evaluator_live_api.py" in doc
    assert "skip" in doc.lower()
    assert "decomposed_query" in doc
