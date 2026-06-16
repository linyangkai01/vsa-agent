"""Tests for tools/embed_search.py."""
from vsa_agent.tools.embed_search import (
    EmbedSearchResultItem, EmbedSearchOutput, QueryInput,
    _generate_query_embedding, _process_search_hit,
)

class TestEmbedSearchResultItem:
    def test_defaults(self):
        item = EmbedSearchResultItem()
        assert item.video_name == ""
        assert item.similarity_score == 0.0

class TestEmbedSearchOutput:
    def test_defaults(self):
        out = EmbedSearchOutput()
        assert out.results == []

class TestQueryInput:
    def test_defaults(self):
        qi = QueryInput()
        assert qi.source_type == "video_file"

class TestGenerateQueryEmbedding:
    async def test_with_query_text(self):
        qi = QueryInput(params={"query": "test query"})
        result = await _generate_query_embedding(qi)
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_empty_query(self):
        qi = QueryInput(params={"query": ""})
        result = await _generate_query_embedding(qi)
        assert result == []

class TestProcessSearchHit:
    async def test_basic_hit(self):
        hit = {"_score": 1.9, "_source": {"sensor": {"id": "s1", "description": "cam1"}, "timestamp": "t1", "end": "t2"}}
        result = await _process_search_hit(hit)
        assert result is not None
        assert result.sensor_id == "s1"
        assert result.similarity_score == 0.9  # score=1.9 -> similarity = 1.9 - 1.0 = 0.9

    async def test_below_threshold(self):
        hit = {"_score": 0.1, "_source": {"sensor": {"id": "s1"}}}
        result = await _process_search_hit(hit, min_cosine_similarity=0.5)
        assert result is None
