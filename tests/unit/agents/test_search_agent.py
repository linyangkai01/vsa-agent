"""Tests for agents/search_agent.py."""

import pytest

from vsa_agent.agents.search_agent import SearchAgentConfig
from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult
from vsa_agent.video_analytics.nvschema import Incident


class TestSearchAgentInput:
    def test_defaults(self):
        inp = SearchAgentInput(query="test query")
        assert inp.query == "test query"
        assert inp.agent_mode is True
        assert inp.max_results == 5

    def test_with_values(self):
        inp = SearchAgentInput(query="person walking", agent_mode=False, max_results=10, source_type="rtsp")
        assert inp.agent_mode is False
        assert inp.source_type == "rtsp"


class TestSearchAgentConfig:
    def test_defaults(self):
        cfg = SearchAgentConfig()
        assert cfg.embed_search_tool == "embed_search"


def test_to_incidents_output_delegates_to_incident_serializer(monkeypatch):
    from vsa_agent.agents.search_agent import _to_incidents_output

    called = {}

    def fake_search_output_to_incidents(output):
        called["search_output"] = output
        return []

    def fake_incidents_to_tagged_json(incidents):
        called["incidents"] = incidents
        return "<incidents>\n{\"incidents\": []}\n</incidents>"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        fake_search_output_to_incidents,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.incidents_to_tagged_json",
        fake_incidents_to_tagged_json,
        raising=False,
    )

    text = _to_incidents_output(SearchOutput(data=[]))

    assert text.startswith("<incidents>")
    assert "search_output" in called
    assert called["incidents"] == []


@pytest.mark.asyncio
async def test_execute_search_agent_flow_builds_incidents_text_and_metadata(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow

    called = {"incidents": False, "summary": False}
    incident = Incident(
        id="search-incident-1",
        timestamp_sec=0.0,
        duration_sec=0.0,
        description="worker approaches gate",
        severity="medium",
        category="search_hit",
        confidence=0.83,
        metadata={"sensor_id": "cam-03"},
    )

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-03.mp4",
                    description="worker approaches gate",
                    start_time="2026-06-19T10:10:00",
                    end_time="2026-06-19T10:10:05",
                    sensor_id="cam-03",
                    screenshot_url="",
                    similarity=0.83,
                    object_ids=[],
                )
            ]
        )

    def fake_search_output_to_incidents(output):
        called["incidents"] = True
        assert output.data[0].description == "worker approaches gate"
        return [incident]

    async def fake_summarize_search_incidents(incidents, query):
        called["summary"] = True
        assert incidents == [incident]
        assert query == "worker approaches gate"
        return "worker approaches gate"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        fake_search_output_to_incidents,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="worker approaches gate", use_critic=False),
        embed_search=fake_embed_search,
    )

    assert result.search_output.data[0].description == "worker approaches gate"
    assert result.incidents == [incident]
    assert result.text_answer == "worker approaches gate"
    assert result.metadata == {
        "critic_requested": False,
        "critic_applied": False,
        "critic_error": None,
    }
    assert called["incidents"] is True
    assert called["summary"] is True


@pytest.mark.asyncio
async def test_execute_search_keeps_returning_search_output():
    from vsa_agent.agents.search_agent import execute_search

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-05.mp4",
                    description="forklift enters aisle",
                    start_time="2026-06-19T11:00:00",
                    end_time="2026-06-19T11:00:06",
                    sensor_id="cam-05",
                    screenshot_url="",
                    similarity=0.91,
                    object_ids=[],
                )
            ]
        )

    result = await execute_search(
        SearchAgentInput(query="forklift enters aisle"),
        embed_search=fake_embed_search,
    )

    assert isinstance(result, SearchOutput)
    assert result.data[0].description == "forklift enters aisle"
