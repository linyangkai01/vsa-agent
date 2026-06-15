"""Tests for tools/vss_summarize.py."""

import pytest

from vsa_agent.data_models.understanding import SummaryResult
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult


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
