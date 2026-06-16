"""Tests for tools/search.py."""
from vsa_agent.tools.search import (
    DecomposedQuery, SearchResult, SearchOutput, SearchConfig, SearchInput,
    _apply_weighted_linear_fusion, _apply_rrf_fusion,
)

class TestDecomposedQuery:
    def test_defaults(self):
        dq = DecomposedQuery()
        assert dq.query == ""
        assert dq.source_type == "video_file"

    def test_with_values(self):
        dq = DecomposedQuery(query="person walking", has_action=True, top_k=5)
        assert dq.query == "person walking"
        assert dq.has_action is True

class TestSearchResult:
    def test_required_fields(self):
        sr = SearchResult(video_name="test.mp4", description="d", start_time="t1", end_time="t2", sensor_id="s1", similarity=0.85)
        assert sr.video_name == "test.mp4"
        assert sr.similarity == 0.85

class TestSearchOutput:
    def test_defaults(self):
        so = SearchOutput()
        assert so.data == []

class TestSearchConfig:
    def test_defaults(self):
        cfg = SearchConfig()
        assert cfg.fusion_method == "rrf"

class TestSearchInput:
    def test_required_fields(self):
        si = SearchInput(query="test query")
        assert si.query == "test query"

class TestFusionFunctions:
    def test_weighted_linear_fusion(self):
        from vsa_agent.tools.search import SearchResult
        video_data = [
            {"embed_result": SearchResult(video_name="v1", description="d1", start_time="t1", end_time="t2", sensor_id="s1", similarity=0.8), "embed_score": 0.8, "normalised_attribute_score": 0.6, "screenshot_url": "", "object_ids": []},
            {"embed_result": SearchResult(video_name="v2", description="d2", start_time="t3", end_time="t4", sensor_id="s2", similarity=0.5), "embed_score": 0.5, "normalised_attribute_score": 0.9, "screenshot_url": "", "object_ids": []},
        ]
        results = _apply_weighted_linear_fusion(video_data, w_embed=0.4, w_attribute=0.6)
        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        # v1: 0.8*0.4 + 0.6*0.6 = 0.68, v2: 0.5*0.4 + 0.9*0.6 = 0.74
        # Sorted by fusion_score descending, so v2 should be first
        assert results[0].video_name == "v2"
        assert results[1].video_name == "v1"

    def test_rrf_fusion(self):
        from vsa_agent.tools.search import SearchResult
        video_data = [
            {"embed_result": SearchResult(video_name="v1", description="d1", start_time="t1", end_time="t2", sensor_id="s1", similarity=0.9), "embed_score": 0.9, "normalised_attribute_score": 0.5, "screenshot_url": "", "object_ids": []},
            {"embed_result": SearchResult(video_name="v2", description="d2", start_time="t3", end_time="t4", sensor_id="s2", similarity=0.6), "embed_score": 0.6, "normalised_attribute_score": 0.8, "screenshot_url": "", "object_ids": []},
        ]
        results = _apply_rrf_fusion(video_data, rrf_k=60, rrf_w=0.5)
        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
