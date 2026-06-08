"""Tests for Task 15 — EmbedSearchResultItem, EmbedSearchOutput, QueryInput, embed functions."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.tools.embed_search import EmbedSearchResultItem
from vsa_agent.tools.embed_search import EmbedSearchOutput
from vsa_agent.tools.embed_search import QueryInput
from vsa_agent.tools.embed_search import _generate_query_embedding
from vsa_agent.tools.embed_search import _process_search_hit


# ===== EmbedSearchResultItem Tests =====


class TestEmbedSearchResultItem:
    """Test the EmbedSearchResultItem Pydantic model."""

    def test_all_fields(self):
        item = EmbedSearchResultItem(
            video_name="camera1.mp4",
            description="Test video",
            start_time="2025-01-01T10:00:00Z",
            end_time="2025-01-01T10:01:00Z",
            sensor_id="sensor-1",
            screenshot_url="http://example.com/img.jpg",
            similarity_score=0.85,
        )
        assert item.video_name == "camera1.mp4"
        assert item.similarity_score == pytest.approx(0.85)
        assert item.sensor_id == "sensor-1"

    def test_defaults(self):
        item = EmbedSearchResultItem()
        assert item.video_name == ""
        assert item.similarity_score == 0.0
        assert item.screenshot_url == ""

    def test_to_search_result(self):
        """Should be convertible to SearchResult."""
        item = EmbedSearchResultItem(
            video_name="v.mp4", description="desc",
            start_time="2025-01-01T00:00:00Z", end_time="2025-01-01T00:01:00Z",
            sensor_id="s1", screenshot_url="", similarity_score=0.5,
        )
        from vsa_agent.tools.search import SearchResult
        sr = SearchResult(
            video_name=item.video_name,
            description=item.description,
            start_time=item.start_time,
            end_time=item.end_time,
            sensor_id=item.sensor_id,
            screenshot_url=item.screenshot_url,
            similarity=item.similarity_score,
        )
        assert sr.video_name == "v.mp4"
        assert sr.similarity == 0.5


# ===== EmbedSearchOutput Tests =====


class TestEmbedSearchOutput:
    """Test the EmbedSearchOutput container model."""

    def test_default_empty(self):
        output = EmbedSearchOutput()
        assert output.query_embedding == []
        assert output.results == []

    def test_with_results(self):
        item = EmbedSearchResultItem(video_name="v.mp4")
        output = EmbedSearchOutput(
            query_embedding=[0.1, 0.2, 0.3],
            results=[item],
        )
        assert len(output.results) == 1
        assert output.results[0].video_name == "v.mp4"


# ===== QueryInput Tests =====


class TestQueryInput:
    """Test the QueryInput Pydantic model."""

    def test_minimal_input(self):
        inp = QueryInput(source_type="video_file")
        assert inp.source_type == "video_file"
        assert inp.id == ""
        assert inp.params == {}
        assert inp.exclude_videos == []

    def test_with_params(self):
        inp = QueryInput(
            params={"query": "person walking", "top_k": "5"},
            source_type="rtsp",
        )
        assert inp.params["query"] == "person walking"
        assert inp.source_type == "rtsp"

    def test_with_exclude_videos(self):
        inp = QueryInput(
            source_type="video_file",
            exclude_videos=[{"sensor_id": "s1", "start_timestamp": "t1"}],
        )
        assert len(inp.exclude_videos) == 1


# ===== Embedding Generation Tests =====


class TestGenerateQueryEmbedding:
    """Test _generate_query_embedding (mock)."""

    def test_text_embedding(self):
        inp = QueryInput(params={"query": "person walking"}, source_type="video_file")
        result = asyncio.run(_generate_query_embedding(inp, embed_client=None))
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(v, float) for v in result)

    def test_empty_query_returns_empty(self):
        inp = QueryInput(params={}, source_type="video_file")
        result = asyncio.run(_generate_query_embedding(inp, embed_client=None))
        assert result == []


# ===== Process Search Hit Tests =====


class TestProcessSearchHit:
    """Test _process_search_hit (mock)."""

    def test_converts_hit_to_result(self):
        hit = {
            "_score": 0.85,
            "_source": {
                "sensor": {
                    "id": "sensor-1",
                    "description": "Front gate camera",
                },
                "timestamp": "2025-01-01T10:00:00Z",
                "end": "2025-01-01T10:01:00Z",
            },
        }
        result = asyncio.run(_process_search_hit(hit))
        assert result is not None
        assert result.sensor_id == "sensor-1"
        assert result.similarity_score == pytest.approx(0.7)
        assert result.video_name == "sensor-1"

    def test_low_score_filtered(self):
        """Results below min_cosine_similarity should be filtered."""
        hit = {"_score": 0.3, "_source": {}}
        result = asyncio.run(_process_search_hit(hit, min_cosine_similarity=0.5))
        assert result is None
