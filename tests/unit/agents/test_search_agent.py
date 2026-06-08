"""Tests for the search agent — three-path routing and query decomposition."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.agents.search_agent import decompose_query
from vsa_agent.agents.search_agent import execute_search
from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.tools.search import DecomposedQuery
from vsa_agent.tools.search import SearchResult
from vsa_agent.tools.search import SearchOutput


# ===== Helpers =====


def _mock_llm_response(content: str):
    response = MagicMock()
    response.content = content
    adapter = MagicMock()
    adapter.invoke = AsyncMock(return_value=response)
    return adapter


def _mock_embed_tool(results=None):
    if results is None:
        results = [
            {"video_name": "camera1.mp4", "description": "Test video 1",
             "start_time": "2025-01-01T10:00:00Z", "end_time": "2025-01-01T10:01:00Z",
             "sensor_id": "s1", "screenshot_url": "", "similarity": 0.85},
        ]
    output = MagicMock()
    output.data = [SearchResult(**r) for r in results]
    return AsyncMock(return_value=output)


def _mock_attribute_tool(results=None):
    if results is None:
        results = [
            {"video_name": "camera2.mp4", "description": "Attribute match",
             "start_time": "2025-01-01T11:00:00Z", "end_time": "2025-01-01T11:01:00Z",
             "sensor_id": "s2", "screenshot_url": "", "similarity": 0.70},
        ]
    return AsyncMock(return_value=[SearchResult(**r) for r in results])


# ===== SearchAgentInput Tests =====


class TestSearchAgentInput:
    """Test the SearchAgentInput Pydantic model."""

    def test_minimal_input(self):
        inp = SearchAgentInput(query="find person")
        assert inp.query == "find person"
        assert inp.agent_mode is True
        assert inp.max_results == 5

    def test_full_input(self):
        inp = SearchAgentInput(
            query="find truck",
            agent_mode=False,
            max_results=10,
            top_k=20,
            start_time="2025-01-01T10:00:00Z",
            end_time="2025-01-01T12:00:00Z",
        )
        assert inp.max_results == 10
        assert inp.top_k == 20
        assert inp.start_time == "2025-01-01T10:00:00Z"

    def test_query_required(self):
        with pytest.raises(Exception):
            SearchAgentInput()


# ===== DecomposedQuery Tests =====


class TestDecomposedQuery:
    """Test the DecomposedQuery Pydantic model."""

    def test_defaults(self):
        q = DecomposedQuery(query="find person")
        assert q.query == "find person"
        assert q.attributes == []
        assert q.video_sources == []
        assert q.has_action is None

    def test_with_attributes(self):
        q = DecomposedQuery(
            query="person in red shirt walking",
            attributes=["person in red shirt"],
            has_action=True,
            top_k=10,
        )
        assert len(q.attributes) == 1
        assert q.has_action is True
        assert q.top_k == 10


# ===== SearchResult/Output Tests =====


class TestSearchResult:
    """Test the SearchResult Pydantic model."""

    def test_minimal_result(self):
        r = SearchResult(
            video_name="test.mp4", description="A test video",
            start_time="2025-01-01T00:00:00Z", end_time="2025-01-01T00:01:00Z",
            sensor_id="sensor-1", screenshot_url="http://example.com/img.jpg",
            similarity=0.95,
        )
        assert r.video_name == "test.mp4"
        assert r.similarity == pytest.approx(0.95)
        assert r.object_ids == []


class TestSearchOutput:
    """Test the SearchOutput container model."""

    def test_default_empty(self):
        output = SearchOutput()
        assert output.data == []

    def test_with_results(self):
        r = SearchResult(
            video_name="v.mp4", description="desc",
            start_time="2025-01-01T00:00:00Z", end_time="2025-01-01T00:01:00Z",
            sensor_id="s1", screenshot_url="", similarity=0.5,
        )
        output = SearchOutput(data=[r])
        assert len(output.data) == 1


# ===== Query Decomposition Tests =====


class TestDecomposeQuery:
    """Test decompose_query with mock LLM."""

    def test_decompose_query_parses_json(self):
        json_str = (
            chr(123) + '"query"' + chr(58) + ' "person walking", "attributes": ["person"], '
            + '"has_action": true, "top_k": 5' + chr(125)
        )
        adapter = _mock_llm_response(json_str)
        result = asyncio.run(decompose_query(user_query="find a person walking", model_adapter=adapter))
        assert result.query == "person walking"
        assert result.has_action is True
        assert result.top_k == 5

    def test_decompose_query_fallback_on_bad_json(self):
        adapter = _mock_llm_response("not valid json at all")
        result = asyncio.run(decompose_query(user_query="find something", model_adapter=adapter))
        assert result.query == "find something"
        assert result.has_action is None

    def test_decompose_query_handles_markdown_json(self):
        json_text = chr(123) + '"query"' + chr(58) + ' "red car", "has_action": false' + chr(125)
        adapter = _mock_llm_response(chr(96)*3 + "json" + chr(10) + json_text + chr(10) + chr(96)*3)
        result = asyncio.run(decompose_query(user_query="find red car", model_adapter=adapter))
        assert result.query == "red car"
        assert result.has_action is False


# ===== Three-Path Routing Tests =====


class TestExecuteSearch:
    """Test execute_search with mocked tools."""

    def test_embed_only_path(self):
        embed_tool = _mock_embed_tool()
        result = asyncio.run(execute_search(
            search_input=SearchAgentInput(query="person walking", agent_mode=False),
            embed_search=embed_tool,
        ))
        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        assert result.data[0].video_name == "camera1.mp4"

    def test_attribute_only_path(self):
        attr_tool = _mock_attribute_tool()
        decomposed = DecomposedQuery(query="red car", has_action=False, attributes=["red car"])
        attr_tool._results = [SearchResult(**{
            "video_name": "cam2.mp4", "description": "match",
            "start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-01T00:01:00Z",
            "sensor_id": "s2", "screenshot_url": "", "similarity": 0.7,
        })]
        an_attr_tool = AsyncMock(return_value=attr_tool._results)
        result = asyncio.run(execute_search(
            search_input=SearchAgentInput(query="red car", agent_mode=False),
            attribute_search=an_attr_tool,
        ))
        assert isinstance(result, SearchOutput)

    def test_fusion_path(self):
        embed_tool = _mock_embed_tool()
        attr_tool = _mock_attribute_tool()
        result = asyncio.run(execute_search(
            search_input=SearchAgentInput(query="person walking with blue jacket", agent_mode=False),
            embed_search=embed_tool,
            attribute_search=attr_tool,
        ))
        assert isinstance(result, SearchOutput)
        assert len(result.data) > 0

    def test_no_results_graceful(self):
        embed_tool = _mock_embed_tool([])
        result = asyncio.run(execute_search(
            search_input=SearchAgentInput(query="nothing matches this", agent_mode=False),
            embed_search=embed_tool,
        ))
        assert isinstance(result, SearchOutput)
        assert result.data == []
