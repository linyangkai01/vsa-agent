"""Tests for agents/search_agent.py."""
from vsa_agent.agents.search_agent import SearchAgentInput, SearchAgentConfig

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
