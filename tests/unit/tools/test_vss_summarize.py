"""Tests for tools/vss_summarize.py."""

import pytest

from vsa_agent.data_models.understanding import SummaryResult
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


@pytest.mark.anyio
async def test_summarize_understanding_result_returns_summary_result():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person walking",
        chunks=[],
        events=[],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert isinstance(summary, SummaryResult)
    assert summary.structured_output.query == "what happened"
    assert summary.text_output == "person walking"


@pytest.mark.anyio
async def test_summarize_uses_model_adapter_when_provided():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    calls = []

    class FakeAdapter:
        async def invoke(self, messages):
            calls.append(messages)
            return type("Response", (), {"content": "LLM summary about forklift activity"})()

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="e1",
                label="walking",
                description="person walking near forklift",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
            )
        ],
    )
    summary = await summarize_understanding_result(
        result,
        "what happened",
        model_adapter=FakeAdapter(),
    )

    assert summary.text_output == "LLM summary about forklift activity"
    assert calls
    prompt_text = calls[0][1].content
    assert "Structured summary" in prompt_text


@pytest.mark.anyio
async def test_summarize_uses_default_text_when_summary_missing():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert summary.text_output == "No notable events detected."


@pytest.mark.anyio
async def test_summarize_prefers_risk_digest_for_long_video_result():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="identify safety risks",
        source_type="video_file",
        summary_text="raw long video text",
        chunks=[],
        events=[],
        metadata={
            "chunk_count": 3,
            "risk_digest": [
                {
                    "category": "Fire / hot work",
                    "chunk_index": 2,
                    "start_timestamp": "00:00:30",
                    "end_timestamp": "00:01:00",
                    "evidence": "Welding operation produces smoke and sparks.",
                },
                {
                    "category": "Slip / trip / housekeeping",
                    "chunk_index": 3,
                    "start_timestamp": "00:01:00",
                    "end_timestamp": "00:01:30",
                    "evidence": "Wet debris-covered ground near hydraulic breaker.",
                },
            ],
        },
    )

    summary = await summarize_understanding_result(result, "identify safety risks")

    assert summary.text_output.startswith("Risk digest by chunk:")
    assert "Chunk 2 [00:00:30 - 00:01:00] Fire / hot work" in summary.text_output
    assert "Welding operation produces smoke and sparks" in summary.text_output
    assert "raw long video text" not in summary.text_output


@pytest.mark.anyio
async def test_summarize_renders_structured_risk_digest_grounding_fields():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="identify safety risks",
        source_type="video_file",
        summary_text="raw long video text",
        chunks=[],
        events=[],
        metadata={
            "risk_digest": [
                {
                    "category": "Fire / hot work",
                    "chunk_index": 2,
                    "time_range": {"start": "00:00:30", "end": "00:01:00"},
                    "evidence": "Welding sparks are visible and one worker lacks a face shield.",
                    "evidence_type": "observed",
                    "inference": False,
                },
                {
                    "category": "Machine guarding / pinch points",
                    "chunk_index": 5,
                    "time_range": {"start": "00:02:00", "end": "00:02:30"},
                    "evidence": "Check guarding around the rebar bending machine pinch points.",
                    "evidence_type": "inferred_or_recommended",
                    "inference": True,
                },
            ],
        },
    )

    summary = await summarize_understanding_result(result, "identify safety risks")

    assert "[observed]" in summary.text_output
    assert "[inferred_or_recommended]" in summary.text_output
    assert "Only state direct observations as facts" in summary.text_output
    assert "Chunk 2 [00:00:30 - 00:01:00] Fire / hot work" in summary.text_output


@pytest.mark.anyio
async def test_summarize_model_adapter_receives_risk_digest_when_available():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    calls = []

    class FakeAdapter:
        async def invoke(self, messages):
            calls.append(messages)
            return type("Response", (), {"content": "digest summary"})()

    result = UnderstandingResult(
        query="identify safety risks",
        source_type="video_file",
        summary_text="raw long video text",
        chunks=[],
        events=[],
        metadata={
            "risk_digest": [
                {
                    "category": "PPE / visibility",
                    "chunk_index": 1,
                    "evidence": "Safety vests are not clearly visible.",
                }
            ],
        },
    )

    summary = await summarize_understanding_result(result, "identify safety risks", model_adapter=FakeAdapter())

    assert summary.text_output == "digest summary"
    assert "Risk digest by chunk" in calls[0][1].content
    assert "Safety vests are not clearly visible" in calls[0][1].content


@pytest.mark.anyio
async def test_summarize_uses_event_descriptions_when_summary_text_missing():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="e1",
                label="walking",
                description="person walking near forklift",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
            ),
            DetectedEvent(
                event_id="e2",
                label="turning",
                description="forklift turns left",
                start_timestamp="00:00:09",
                end_timestamp="00:00:12",
            ),
        ],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert "person walking near forklift" in summary.text_output
    assert "forklift turns left" in summary.text_output


@pytest.mark.anyio
async def test_summarize_includes_event_timestamps_in_text_output():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="e1",
                label="walking",
                description="person walking near forklift",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
            )
        ],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert "00:00:05" in summary.text_output
    assert "00:00:09" in summary.text_output


@pytest.mark.anyio
async def test_summarize_merges_adjacent_duplicate_event_descriptions():
    from vsa_agent.tools.vss_summarize import summarize_understanding_result

    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="e1",
                label="walking",
                description="person walking near forklift",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
            ),
            DetectedEvent(
                event_id="e2",
                label="walking",
                description="person walking near forklift",
                start_timestamp="00:00:09",
                end_timestamp="00:00:12",
            ),
        ],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert summary.text_output.count("person walking near forklift") == 1
    assert "00:00:05" in summary.text_output
    assert "00:00:12" in summary.text_output


@pytest.mark.anyio
async def test_summarize_search_incidents_returns_fallback_for_empty_results():
    from vsa_agent.tools.vss_summarize import summarize_search_incidents

    summary = await summarize_search_incidents([], "person in loading area")

    assert summary == "No matching videos found."


@pytest.mark.anyio
async def test_summarize_search_incidents_returns_stable_text_output():
    from vsa_agent.tools.incidents import search_output_to_incidents
    from vsa_agent.tools.vss_summarize import summarize_search_incidents

    incidents = search_output_to_incidents(
        SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-04.mp4",
                    description="person crosses lane",
                    start_time="2026-06-19T10:20:00",
                    end_time="2026-06-19T10:20:07",
                    sensor_id="cam-04",
                    similarity=0.79,
                ),
                SearchResult(
                    video_name="cam-02.mp4",
                    description="forklift stops near dock",
                    start_time="2026-06-19T10:21:10",
                    end_time="2026-06-19T10:21:16",
                    sensor_id="cam-02",
                    similarity=0.75,
                ),
            ]
        )
    )

    summary = await summarize_search_incidents(incidents, "loading area activity")

    assert summary == (
        "[2026-06-19T10:20:00 - 2026-06-19T10:20:07] person crosses lane\n"
        "[2026-06-19T10:21:10 - 2026-06-19T10:21:16] forklift stops near dock"
    )
