import os

import pytest

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.evaluators import ExpectedSearchHit
from vsa_agent.evaluators import evaluate_search_output
from vsa_agent.evaluators import evaluate_understanding_result


def should_run_live_api_validation() -> bool:
    return bool(resolve_live_api_settings()["api_key"])


def resolve_live_api_settings() -> dict[str, str | None]:
    live_model = (os.getenv("LIVE_API_MODEL") or "").strip() or None
    live_base_url = (os.getenv("LIVE_API_BASE_URL") or "").strip() or None
    live_api_key = (os.getenv("LIVE_API_KEY") or "").strip() or None
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
    return {
        "model_name": live_model,
        "base_url": live_base_url,
        "api_key": live_api_key or openai_api_key,
    }


def format_live_search_diagnostics(*, text_answer: str, metadata: dict, eval_score: float) -> str:
    return (
        f"text_answer={text_answer!r}\n"
        f"decomposed_query={metadata.get('decomposed_query')!r}\n"
        f"decomposed_attributes={metadata.get('decomposed_attributes')!r}\n"
        f"decomposed_has_action={metadata.get('decomposed_has_action')!r}\n"
        f"eval_score={eval_score:.3f}"
    )


def test_live_api_validation_skips_without_required_env(monkeypatch):
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert should_run_live_api_validation() is False


def test_resolve_live_api_settings_prefers_live_overrides(monkeypatch):
    monkeypatch.setenv("LIVE_API_MODEL", "qwen-plus")
    monkeypatch.setenv("LIVE_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LIVE_API_KEY", "live-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    settings = resolve_live_api_settings()

    assert settings["model_name"] == "qwen-plus"
    assert settings["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings["api_key"] == "live-key"


def test_resolve_live_api_settings_falls_back_to_openai_key(monkeypatch):
    monkeypatch.delenv("LIVE_API_MODEL", raising=False)
    monkeypatch.delenv("LIVE_API_BASE_URL", raising=False)
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    settings = resolve_live_api_settings()

    assert settings["model_name"] is None
    assert settings["base_url"] is None
    assert settings["api_key"] == "openai-key"


def test_format_live_search_diagnostics_includes_key_fields():
    text = format_live_search_diagnostics(
        text_answer="person near forklift",
        metadata={
            "decomposed_query": "person near forklift",
            "decomposed_attributes": ["person"],
            "decomposed_has_action": True,
        },
        eval_score=1.0,
    )

    assert "text_answer='person near forklift'" in text
    assert "decomposed_attributes=['person']" in text
    assert "eval_score=1.000" in text


@pytest.mark.anyio
async def test_live_api_understanding_quality():
    if not should_run_live_api_validation():
        pytest.skip("LIVE_API_KEY or OPENAI_API_KEY not configured for live API validation")

    from vsa_agent.tools.vss_summarize import summarize_understanding_result
    from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

    actual = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person walking near forklift in the loading area",
        chunks=[],
        events=[],
    )
    settings = resolve_live_api_settings()
    summary = await summarize_understanding_result(
        actual,
        "what happened",
        model_adapter=OpenAIModelAdapter(**settings),
    )
    result = evaluate_understanding_result(
        summary.structured_output.model_copy(update={"summary_text": summary.text_output}),
        expected_summary_terms=["person", "forklift"],
        expected_events=[],
    )

    assert summary.text_output
    assert result.score >= 1.0


@pytest.mark.anyio
async def test_live_api_search_agent_query_decomposition_quality():
    if not should_run_live_api_validation():
        pytest.skip("LIVE_API_KEY or OPENAI_API_KEY not configured for live API validation")

    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter
    from vsa_agent.tools.search import SearchOutput
    from vsa_agent.tools.search import SearchResult

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-live-01.mp4",
                    description="person walking near forklift in loading area",
                    start_time="2026-06-23T10:00:00",
                    end_time="2026-06-23T10:00:08",
                    sensor_id="cam-live-01",
                    screenshot_url="",
                    similarity=0.93,
                    object_ids=["obj-1"],
                )
            ]
        )

    settings = resolve_live_api_settings()
    result = await execute_search_agent_flow(
        SearchAgentInput(query="find a person walking near a forklift", use_critic=False),
        model_adapter=OpenAIModelAdapter(**settings),
        embed_search=fake_embed_search,
    )
    eval_result = evaluate_search_output(
        result.search_output,
        expected_hits=[
            ExpectedSearchHit(
                video_name="cam-live-01.mp4",
                description_terms=["person", "forklift"],
                sensor_id="cam-live-01",
            )
        ],
    )
    diagnostics = format_live_search_diagnostics(
        text_answer=result.text_answer,
        metadata=result.metadata,
        eval_score=eval_result.score,
    )

    assert "person" in result.text_answer.lower(), diagnostics
    assert "forklift" in result.text_answer.lower(), diagnostics
    assert result.metadata["decomposed_query"], diagnostics
    assert "person" in " ".join(result.metadata["decomposed_attributes"]).lower(), diagnostics
    assert result.metadata["decomposed_has_action"] is True, diagnostics
    assert eval_result.score >= 1.0, diagnostics
