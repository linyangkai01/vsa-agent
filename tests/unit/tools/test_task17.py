"""Tests for Task 17 — SearchAgentConfig and presentation converters."""

import pytest

from vsa_agent.agents.search_agent import SearchAgentConfig
from vsa_agent.agents.search_agent import _to_search_results
from vsa_agent.agents.search_agent import _to_incidents_output
from vsa_agent.tools.search import SearchResult
from vsa_agent.tools.search import SearchOutput


class TestSearchAgentConfig:
    def test_defaults(self):
        cfg = SearchAgentConfig()
        assert cfg.default_max_results == 10
        assert cfg.use_attribute_search is False
        assert cfg.embed_confidence_threshold == 0.1

    def test_custom(self):
        cfg = SearchAgentConfig(default_max_results=20, enable_critic=True)
        assert cfg.default_max_results == 20
        assert cfg.enable_critic is True


class TestToSearchResults:
    def test_dict_to_search_result(self):
        raw = [{"video_name": "v.mp4", "similarity": 0.9}]
        results = _to_search_results(raw)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].video_name == "v.mp4"

    def test_preserves_search_result(self):
        sr = SearchResult(
            video_name="v.mp4", description="", start_time="", end_time="",
            sensor_id="s1", screenshot_url="", similarity=0.5,
        )
        results = _to_search_results([sr])
        assert results[0] is sr


class TestToIncidentsOutput:
    def test_formats_results(self):
        sr = SearchResult(
            video_name="cam1.mp4", description="Test", start_time="t1",
            end_time="t2", sensor_id="s1", screenshot_url="", similarity=0.9,
        )
        output = _to_incidents_output(SearchOutput(data=[sr]))
        assert "<incidents>" in output
        assert "cam1.mp4" in output
