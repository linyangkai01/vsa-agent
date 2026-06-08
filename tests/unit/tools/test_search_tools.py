"""Tests for the three search tools: embed_search, attribute_search, search."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.registry import ToolRegistry
from vsa_agent.tools.query_builders import SearchOutput
from vsa_agent.tools.query_builders import SearchResult


# ===== Helpers =====


def _make_result(video_name: str, similarity: float, description: str = "") -> SearchResult:
    return SearchResult(
        video_name=video_name,
        description=description or f"Match in {video_name}",
        start_time="2025-01-01T10:00:00Z",
        end_time="2025-01-01T10:01:00Z",
        sensor_id=f"sensor-{video_name}",
        screenshot_url="",
        similarity=similarity,
    )


def _mock_store(results: list[SearchResult] | None = None):
    """Create a mock vector store that returns the given results."""
    if results is None:
        results = [_make_result("camera1.mp4", 0.85)]
    store = MagicMock()
    store.search = AsyncMock(return_value=SearchOutput(data=results))
    store.search_by_attributes = AsyncMock(return_value=SearchOutput(data=results))
    return store


# ===== embed_search Tests =====


class TestEmbedSearch:
    """Test the embed_search registered tool."""

    def test_basic_search(self):
        fn = ToolRegistry.get("embed_search")
        assert fn is not None, "embed_search tool must be registered"

        store = _mock_store()
        result = asyncio.run(fn(
            query="person walking",
            store=store,
        ))

        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        assert result.data[0].video_name == "camera1.mp4"
        store.search.assert_called_once()

    def test_search_with_top_k(self):
        fn = ToolRegistry.get("embed_search")
        results = [_make_result(f"video{i}.mp4", 0.9 - i * 0.1) for i in range(3)]
        store = _mock_store(results)

        result = asyncio.run(fn(query="test", store=store, top_k=2))
        assert len(result.data) == 3  # store returns what it returns; top_k is a hint
        store.search.assert_called_once()

    def test_search_no_results(self):
        fn = ToolRegistry.get("embed_search")
        store = _mock_store([])

        result = asyncio.run(fn(query="nothing", store=store))
        assert result.data == []
        store.search.assert_called_once()

    def test_search_empty_query(self):
        """Empty query should raise ValueError."""
        fn = ToolRegistry.get("embed_search")
        store = _mock_store()
        with pytest.raises(ValueError, match="query"):
            asyncio.run(fn(query="", store=store))


# ===== attribute_search Tests =====


class TestAttributeSearch:
    """Test the attribute_search registered tool."""

    def test_basic_search(self):
        fn = ToolRegistry.get("attribute_search")
        assert fn is not None, "attribute_search tool must be registered"

        store = _mock_store()
        result = asyncio.run(fn(
            attributes=["person with red jacket"],
            store=store,
        ))

        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        store.search_by_attributes.assert_called_once()

    def test_multi_attribute_search(self):
        fn = ToolRegistry.get("attribute_search")
        store = _mock_store([_make_result("cam1.mp4", 0.75)])

        result = asyncio.run(fn(
            attributes=["red shirt", "blue pants", "hard hat"],
            store=store,
        ))

        assert isinstance(result, SearchOutput)
        store.search_by_attributes.assert_called_once()

    def test_empty_attributes(self):
        fn = ToolRegistry.get("attribute_search")
        store = _mock_store()
        with pytest.raises(ValueError, match="At least one attribute"):
            asyncio.run(fn(attributes=[], store=store))

    def test_deduplication(self):
        """Results with same video_name should be deduplicated (best similarity wins)."""
        fn = ToolRegistry.get("attribute_search")
        results = [
            _make_result("cam1.mp4", 0.5, "lower score"),
            _make_result("cam1.mp4", 0.9, "higher score"),
            _make_result("cam2.mp4", 0.7, "unique"),
        ]
        store = _mock_store(results)

        result = asyncio.run(fn(
            attributes=["person"],
            store=store,
        ))

        # cam1 should appear only once (best score 0.9)
        cam1_results = [r for r in result.data if r.video_name == "cam1.mp4"]
        assert len(cam1_results) == 1
        assert cam1_results[0].similarity == 0.9


# ===== core search Tests =====


class TestCoreSearch:
    """Test the search orchestrator tool (three-path routing)."""

    def test_embed_only_path(self):
        """No attributes → Path 2: embed-only."""
        fn = ToolRegistry.get("search")
        assert fn is not None, "search tool must be registered"

        embed_store = _mock_store()
        attr_store = _mock_store()

        result = asyncio.run(fn(
            query="person walking",
            embed_store=embed_store,
        ))

        assert isinstance(result, SearchOutput)
        assert len(result.data) == 1
        embed_store.search.assert_called_once()

    def test_attribute_only_path(self):
        """has_action=False + attributes → Path 1: attribute-only."""
        fn = ToolRegistry.get("search")
        embed_store = _mock_store()
        attr_store = _mock_store()

        result = asyncio.run(fn(
            query="red car",
            decomposed_has_action=False,
            decomposed_attributes=["red car"],
            attr_store=attr_store,
        ))

        assert isinstance(result, SearchOutput)
        attr_store.search_by_attributes.assert_called_once()

    def test_fusion_path(self):
        """has_action=True + attributes → Path 3: fusion."""
        fn = ToolRegistry.get("search")
        embed_results = [_make_result("cam1.mp4", 0.85)]
        attr_results = [_make_result("cam2.mp4", 0.70)]
        embed_store = _mock_store(embed_results)
        attr_store = _mock_store(attr_results)

        result = asyncio.run(fn(
            query="person carrying box",
            decomposed_attributes=["person"],
            embed_store=embed_store,
            attr_store=attr_store,
        ))

        assert isinstance(result, SearchOutput)
        # Fusion: results from both sources, merged
        assert len(result.data) >= 1
        embed_store.search.assert_called_once()
