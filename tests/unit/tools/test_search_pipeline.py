from types import SimpleNamespace

import pytest

from vsa_agent.tools.search import SearchOutput, SearchResult
from vsa_agent.tools.search_pipeline import (
    filter_rejected_sensors,
    normalize_search_results,
    rank_unique_results,
    select_fusion_results,
    select_search_route,
    should_apply_critic,
    trim_search_results,
)


def _result(video_name: str, similarity: float, sensor_id: str | None = None) -> SearchResult:
    return SearchResult(
        video_name=video_name,
        description=video_name,
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:00:05Z",
        sensor_id=sensor_id or video_name,
        similarity=similarity,
    )


@pytest.mark.parametrize(
    ("has_action", "attributes", "attribute_available", "expected"),
    [
        (None, [], True, "embed"),
        (False, ["blue jacket"], True, "attribute"),
        (None, ["blue jacket"], True, "attribute"),
        (True, ["running"], True, "fusion"),
        (False, ["blue jacket"], False, None),
    ],
)
def test_select_search_route_preserves_existing_matrix(has_action, attributes, attribute_available, expected):
    assert select_search_route(has_action, attributes, attribute_available=attribute_available) == expected


def test_normalize_search_results_supports_all_shapes_and_copies_lists():
    item = _result("video-a", 0.8)
    source_list = [item]

    normalized_list = normalize_search_results(source_list)
    assert normalized_list == source_list
    assert normalized_list is not source_list
    assert normalize_search_results(SearchOutput(data=[item])) == [item]
    assert normalize_search_results(SimpleNamespace(data=(item,))) == [item]
    assert normalize_search_results(None) == []
    assert normalize_search_results(object()) == []


def test_rank_unique_results_keeps_highest_similarity_and_does_not_mutate_input():
    original = [_result("video-a", 0.4), _result("video-b", 0.7), _result("video-a", 0.9)]

    ranked = rank_unique_results(original)

    assert [(item.video_name, item.similarity) for item in ranked] == [("video-a", 0.9), ("video-b", 0.7)]
    assert [item.similarity for item in original] == [0.4, 0.7, 0.9]


def test_select_fusion_results_falls_back_to_attributes_only_below_threshold():
    embed = [_result("embed", 0.19)]
    attribute = [_result("attribute", 0.8)]

    assert select_fusion_results(embed, attribute, confidence_threshold=0.2) == attribute
    assert select_fusion_results(embed, attribute, confidence_threshold=0.0) == rank_unique_results(embed + attribute)


def test_critic_filter_and_top_k_preserve_order():
    results = [_result("video-a", 0.9, "sensor-a"), _result("video-b", 0.8, "sensor-b")]
    rejected = [SimpleNamespace(sensor_id="sensor-a")]

    filtered = filter_rejected_sensors(results, rejected)

    assert [item.sensor_id for item in filtered] == ["sensor-b"]
    assert trim_search_results(results, 1) == [results[0]]
    assert trim_search_results(results, None) == results


def test_should_apply_critic_requires_all_conditions():
    assert should_apply_critic(enable_critic=True, use_critic=True, critic_agent=object()) is True
    assert should_apply_critic(enable_critic=False, use_critic=True, critic_agent=object()) is False
    assert should_apply_critic(enable_critic=True, use_critic=False, critic_agent=object()) is False
    assert should_apply_critic(enable_critic=True, use_critic=True, critic_agent=None) is False
