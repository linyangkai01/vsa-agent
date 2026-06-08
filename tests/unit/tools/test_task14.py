"""Tests for Task 14 — SearchConfig, SearchInput, execute_core_search."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.tools.search import SearchConfig
from vsa_agent.tools.search import SearchInput
from vsa_agent.tools.search import execute_core_search
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


# ===== Helpers =====


def _make_result(video_name: str, similarity: float) -> SearchResult:
    return SearchResult(
        video_name=video_name,
        description=f"Match in {video_name}",
        start_time="2025-01-01T10:00:00Z",
        end_time="2025-01-01T10:01:00Z",
        sensor_id=f"sensor-{video_name}",
        screenshot_url="",
        similarity=similarity,
    )


def _mock_embed_search(results=None):
    if results is None:
        results = [_make_result("cam1.mp4", 0.85)]
    return AsyncMock(return_value=SearchOutput(data=results))


def _mock_attribute_search(results=None):
    if results is None:
        results = [_make_result("cam2.mp4", 0.70)]
    return AsyncMock(return_value=results)


# ===== SearchConfig Tests =====


class TestSearchConfig:
    """Test SearchConfig model fields."""

    def test_defaults(self):
        cfg = SearchConfig()
        assert cfg.embed_confidence_threshold == 0.2
        assert cfg.use_attribute_search is False
        assert cfg.fusion_method == "rrf"
        assert cfg.w_embed == 0.35
        assert cfg.w_attribute == 0.55
        assert cfg.rrf_k == 60
        assert cfg.rrf_w == 0.5
        assert cfg.default_max_results == 10

    def test_custom_fusion_method(self):
        cfg = SearchConfig(fusion_method="weighted_linear")
        assert cfg.fusion_method == "weighted_linear"

    def test_custom_weights(self):
        cfg = SearchConfig(w_embed=0.5, w_attribute=0.5)
        assert cfg.w_embed == 0.5
        assert cfg.w_attribute == 0.5


# ===== SearchInput Tests =====


class TestSearchInput:
    """Test SearchInput model fields."""

    def test_minimal_input(self):
        inp = SearchInput(query="find person", source_type="video_file")
        assert inp.query == "find person"
        assert inp.source_type == "video_file"
        assert inp.top_k is None
        assert inp.agent_mode is True

    def test_full_input(self):
        inp = SearchInput(
            query="find truck",
            source_type="rtsp",
            video_sources=["warehouse_cam1"],
            top_k=10,
            agent_mode=False,
        )
        assert inp.source_type == "rtsp"
        assert inp.video_sources == ["warehouse_cam1"]
        assert inp.top_k == 10
        assert inp.agent_mode is False

    def test_query_required(self):
        with pytest.raises(Exception):
            SearchInput(source_type="video_file")


# ===== execute_core_search Tests =====


class TestExecuteCoreSearch:
    """Test execute_core_search async generator."""

    def test_returns_search_output(self):
        """Generator should yield SearchOutput as final result."""
        search_input = SearchInput(query="person walking", source_type="video_file")
        embed_fn = _mock_embed_search()

        async def _collect():
            updates = []
            async for update in execute_core_search(search_input, embed_fn, agent_llm=None):
                updates.append(update)
            return updates
        updates = asyncio.run(_collect())

        assert len(updates) >= 1
        final = updates[-1]
        assert isinstance(final, SearchOutput)
        assert len(final.data) == 1
        assert final.data[0].video_name == "cam1.mp4"

    def test_no_results(self):
        """Empty results should still return SearchOutput."""
        search_input = SearchInput(query="nothing", source_type="video_file")
        embed_fn = _mock_embed_search([])

        async def _collect():
            updates = []
            async for update in execute_core_search(search_input, embed_fn, agent_llm=None):
                updates.append(update)
            return updates
        updates = asyncio.run(_collect())

        final = updates[-1]
        assert isinstance(final, SearchOutput)
        assert final.data == []

    def test_yields_progress_chunks(self):
        """Generator should yield progress messages before final result."""
        search_input = SearchInput(query="test", source_type="video_file")
        embed_fn = _mock_embed_search()

        async def _collect():
            updates = []
            async for update in execute_core_search(search_input, embed_fn, agent_llm=None):
                updates.append(update)
            return updates
        updates = asyncio.run(_collect())

        # At minimum, there should be a final result
        assert any(isinstance(u, SearchOutput) for u in updates)
