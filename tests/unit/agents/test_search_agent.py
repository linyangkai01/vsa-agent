"""Tests for the search agent — three-path routing and query decomposition."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.agents.search_agent import DecomposedQuery
from vsa_agent.agents.search_agent import SearchResult
from vsa_agent.agents.search_agent import SearchOutput
from vsa_agent.agents.search_agent import decompose_query
from vsa_agent.agents.search_agent import execute_search


# ===== Helpers =====


def _mock_llm_response(content: str):
    """Create a mock LLM response with .content attribute."""
    response = MagicMock()
    response.content = content
    adapter = MagicMock()
    adapter.invoke = AsyncMock(return_value=response)
    return adapter


def _mock_embed_tool(results: list[dict] | None = None):
    """Create a mock embed search tool that returns SearchResults."""
    if results is None:
        results = [
            {"video_name": "camera1.mp4", "description": "Test video 1",
             "start_time": "2025-01-01T10:00:00Z", "end_time": "2025-01-01T10:01:00Z",
             "sensor_id": "s1", "screenshot_url": "", "similarity": 0.85},
        ]
    output = MagicMock()
    output.data = [SearchResult(**r) for r in results]
    return AsyncMock(return_value=output)


def _mock_attribute_tool(results: list[dict] | None = None):
    """Create a mock attribute search tool that returns SearchResults."""
    if results is None:
        results = [
            {"video_name": "camera2.mp4", "description": "Attribute match",
             "start_time": "2025-01-01T11:00:00Z", "end_time": "2025-01-01T11:01:00Z",
             "sensor_id": "s2", "screenshot_url": "", "similarity": 0.70},
        ]
    return AsyncMock(return_value=[SearchResult(**r) for r in results])


# ===== Data Model Tests =====


class TestDecomposedQuery:
    """Test the DecomposedQuery Pydantic model."""

    def test_defaults(self):
        q = DecomposedQuery(query="find person")
        assert q.query == "find person"
        assert q.attributes == []
        assert q.video_sources == []
        assert q.has_action is None
        assert q.top_k is None

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

    def test_no_action(self):
        q = DecomposedQuery(query="red car", has_action=False)
        assert q.has_action is False


class TestSearchResult:
    """Test the SearchResult Pydantic model."""

    def test_minimal_result(self):
        r = SearchResult(
            video_name="test.mp4",
            description="A test video",
            start_time="2025-01-01T00:00:00Z",
            end_time="2025-01-01T00:01:00Z",
            sensor_id="sensor-1",
            screenshot_url="http://example.com/img.jpg",
            similarity=0.95,
        )
        assert r.video_name == "test.mp4"
        assert r.similarity == pytest.approx(0.95)
        assert r.object_ids == []

    def test_result_serialization(self):
        r = SearchResult(
            video_name="v.mp4", description="desc",
            start_time="2025-01-01T00:00:00Z", end_time="2025-01-01T00:01:00Z",
            sensor_id="s1", screenshot_url="", similarity=0.5,
            object_ids=["obj1", "obj2"],
        )
        d = r.model_dump()
        assert d["object_ids"] == ["obj1", "obj2"]
        assert d["similarity"] == 0.5


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
            '{"query": "person walking", "attributes": ["person"], '
            '"has_action": true, "top_k": 5, "video_sources": []}'
        )
        adapter = _mock_llm_response(json_str)
        result = asyncio.run(decompose_query(
            user_query="find a person walking",
            model_adapter=adapter,
        ))
        assert result.query == "person walking"
        assert result.has_action is True
        assert result.top_k == 5
        adapter.invoke.assert_called_once()

    def test_decompose_query_fallback_on_bad_json(self):
        """Bad JSON should fall back to using the original query."""
        adapter = _mock_llm_response("not valid json at all")
        result = asyncio.run(decompose_query(
            user_query="find something",
            model_adapter=adapter,
        ))
        assert result.query == "find something"
        assert result.has_action is None

    def test_decompose_query_handles_markdown_json(self):
        """LLM often wraps JSON in markdown code blocks."""
        adapter = _mock_llm_response(
            '```json\n{"query": "red car", "has_action": false}\n```'
        )
        result = asyncio.run(decompose_query(
            user_query="find red car",
            model_adapter=adapter,
        ))
        assert result.query == "red car"
        assert result.has_action is False


# ===== Three-Path Routing Tests =====


class TestExecuteSearch:
    """Test execute_search with mocked tools."""

    def test_embed_only_path(self):
        """No attributes → Path 2: embed-only search."""
        decomposed = DecomposedQuery(query="person walking", has_action=True)
        embed_tool = _mock_embed_tool()

        result = asyncio.run(execute_search(
            decomposed=decomposed,
            embed_search=embed_tool,
        ))

        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        assert result.data[0].video_name == "camera1.mp4"
        embed_tool.assert_called_once()

    def test_attribute_only_path(self):
        """has_action=False with attributes → Path 1: attribute-only search."""
        decomposed = DecomposedQuery(
            query="red car", has_action=False,
            attributes=["red car"],
        )
        attr_tool = _mock_attribute_tool()

        result = asyncio.run(execute_search(
            decomposed=decomposed,
            attribute_search=attr_tool,
        ))

        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        assert result.data[0].video_name == "camera2.mp4"

    def test_fusion_path(self):
        """has_action=True with attributes → Path 3: embed + attribute rerank."""
        decomposed = DecomposedQuery(
            query="person walking with blue jacket",
            has_action=True,
            attributes=["person with blue jacket"],
        )
        embed_tool = _mock_embed_tool()
        attr_tool = _mock_attribute_tool()

        result = asyncio.run(execute_search(
            decomposed=decomposed,
            embed_search=embed_tool,
            attribute_search=attr_tool,
        ))

        assert isinstance(result, SearchOutput)
        # Fusion should combine/rerank results from both sources
        assert len(result.data) > 0
        embed_tool.assert_called_once()

    def test_no_results_graceful(self):
        """Empty search results should not crash."""
        decomposed = DecomposedQuery(query="nothing matches this")
        embed_tool = _mock_embed_tool([])

        result = asyncio.run(execute_search(
            decomposed=decomposed,
            embed_search=embed_tool,
        ))

        assert isinstance(result, SearchOutput)
        assert result.data == []
