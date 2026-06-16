"""Tests for agents/search_agent.py."""
from vsa_agent.agents.search_agent import SearchAgentInput, SearchAgentConfig
from vsa_agent.tools.search import SearchOutput

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
