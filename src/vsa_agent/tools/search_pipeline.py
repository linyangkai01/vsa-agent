"""Pure routing and result-selection rules for search orchestration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal

SearchRoute = Literal["attribute", "embed", "fusion"]


def select_search_route(
    has_action: bool | None,
    attributes: Sequence[str],
    *,
    attribute_available: bool,
) -> SearchRoute | None:
    has_attributes = bool(attributes)
    if not has_action and has_attributes and attribute_available:
        return "attribute"
    if not has_attributes:
        return "embed"
    if has_action and has_attributes:
        return "fusion"
    return None


def normalize_search_results(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    data = getattr(value, "data", None)
    if data is None:
        return []
    return list(data)


def max_similarity(results: Sequence[Any]) -> float | None:
    if not results:
        return None
    return max(result.similarity for result in results)


def rank_unique_results[ResultT](results: Iterable[ResultT]) -> list[ResultT]:
    merged: dict[str, ResultT] = {}
    for result in results:
        existing = merged.get(result.video_name)
        if existing is None or result.similarity > existing.similarity:
            merged[result.video_name] = result
    return sorted(merged.values(), key=lambda result: result.similarity, reverse=True)


def select_fusion_results[ResultT](
    embed_results: Sequence[ResultT],
    attribute_results: Sequence[ResultT],
    *,
    confidence_threshold: float,
) -> list[ResultT]:
    embed_score = max_similarity(embed_results)
    if embed_score is not None and confidence_threshold > 0 and embed_score < confidence_threshold:
        return list(attribute_results)
    return rank_unique_results([*embed_results, *attribute_results])


def filter_rejected_sensors[ResultT](results: Iterable[ResultT], rejected_video_infos: Iterable[Any]) -> list[ResultT]:
    rejected_sensor_ids = {info.sensor_id for info in rejected_video_infos}
    return [result for result in results if result.sensor_id not in rejected_sensor_ids]


def trim_search_results[ResultT](results: Sequence[ResultT], top_k: int | None) -> list[ResultT]:
    if top_k is None:
        return list(results)
    return list(results[:top_k])


def should_apply_critic(*, enable_critic: bool, use_critic: bool, critic_agent: Any) -> bool:
    return bool(enable_critic and use_critic and critic_agent is not None)


__all__ = [
    "filter_rejected_sensors",
    "max_similarity",
    "normalize_search_results",
    "rank_unique_results",
    "select_fusion_results",
    "select_search_route",
    "should_apply_critic",
    "trim_search_results",
]
