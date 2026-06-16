"""Acceptance tests for Phase 4 offline tools flow."""

import pytest

from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult


@pytest.mark.anyio
async def test_phase4_offline_flow_from_understanding_to_geolocation_summary():
    from vsa_agent.tools.geolocation import enrich_incidents_with_location
    from vsa_agent.tools.geolocation import summarize_geolocation
    from vsa_agent.tools.incidents import understanding_to_incidents

    result = UnderstandingResult(
        query="find intrusion",
        source_type="video_file",
        summary_text="person enters restricted area",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="event-1",
                label="intrusion",
                description="person enters restricted area",
                start_timestamp="00:00:05",
                end_timestamp="00:00:12",
                evidence=[EvidenceRef(source_type="video_file", video_path="video.mp4")],
            )
        ],
    )

    incidents = understanding_to_incidents(result)
    enriched = enrich_incidents_with_location(
        incidents,
        default_location_name="Warehouse A",
        default_zone="loading_dock",
    )
    summary = summarize_geolocation(enriched)

    assert "Warehouse A" in summary
    assert "loading_dock" in summary
    assert "1" in summary


@pytest.mark.anyio
async def test_phase4_caption_wrappers_share_same_core_path(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool
    from vsa_agent.tools.video_detailed_caption import video_detailed_caption_tool
    from vsa_agent.tools.video_skim_caption import video_skim_caption_tool

    calls = []

    async def fake_analyze_video(**kwargs):
        calls.append(kwargs)
        return type("Result", (), {"summary_text": "caption", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)

    base_text = await video_caption_tool(video_path="video.mp4", user_prompt="describe")
    detailed_text = await video_detailed_caption_tool(video_path="video.mp4", user_prompt="describe")
    skim_text = await video_skim_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert base_text == "caption"
    assert detailed_text == "caption"
    assert skim_text == "caption"
    assert len(calls) == 3
    assert calls[0]["query"] == "describe"
    assert "详细" in calls[1]["query"]
    assert "简要" in calls[2]["query"]

