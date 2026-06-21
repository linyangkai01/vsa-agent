"""Tests for tools/search.py."""

import pytest

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


def test_should_apply_critic_requires_enable_flag_request_flag_and_agent():
    from vsa_agent.tools.search import should_apply_critic

    assert should_apply_critic(enable_critic=True, use_critic=True, critic_agent=object()) is True
    assert should_apply_critic(enable_critic=False, use_critic=True, critic_agent=object()) is False
    assert should_apply_critic(enable_critic=True, use_critic=False, critic_agent=object()) is False
    assert should_apply_critic(enable_critic=True, use_critic=True, critic_agent=None) is False


@pytest.mark.asyncio
async def test_execute_core_search_does_not_invoke_critic_when_use_critic_is_false():
    from vsa_agent.tools.search import execute_core_search

    critic_called = False

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-41.mp4",
                    description="worker enters dock",
                    start_time="2026-06-19T15:00:00",
                    end_time="2026-06-19T15:00:05",
                    sensor_id="cam-41",
                    similarity=0.86,
                )
            ]
        )

    async def fake_critic_agent(_critic_input):
        nonlocal critic_called
        critic_called = True
        return None

    updates = []
    async for update in execute_core_search(
        search_input=SearchInput(query="worker enters dock", use_critic=False, agent_mode=False),
        embed_search=fake_embed_search,
        config=SearchConfig(enable_critic=True),
        critic_agent=fake_critic_agent,
    ):
        updates.append(update)

    assert critic_called is False
    assert isinstance(updates[-1], SearchOutput)
    assert updates[-1].data[0].video_name == "cam-41.mp4"


@pytest.mark.asyncio
async def test_execute_core_search_continues_when_critic_raises():
    from vsa_agent.tools.search import execute_core_search

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-51.mp4",
                    description="worker enters dock",
                    start_time="2026-06-19T16:00:00",
                    end_time="2026-06-19T16:00:05",
                    sensor_id="cam-51",
                    similarity=0.93,
                )
            ]
        )

    async def fake_critic_agent(_critic_input):
        raise RuntimeError("critic offline")

    updates = []
    async for update in execute_core_search(
        search_input=SearchInput(query="worker enters dock", use_critic=True, agent_mode=False),
        embed_search=fake_embed_search,
        config=SearchConfig(enable_critic=True),
        critic_agent=fake_critic_agent,
    ):
        updates.append(update)

    assert isinstance(updates[-1], SearchOutput)
    assert updates[-1].data[0].video_name == "cam-51.mp4"
