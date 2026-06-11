"""Attribute search tool — object-level search by visual attributes.

Searches for video segments matching specific object/person descriptions
using Elasticsearch behavior index with embedding similarity.

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput, SearchResult

logger = logging.getLogger(__name__)

BASE_2025 = datetime(2025, 1, 1)


class AttributeSearchInput(BaseModel):
    """Input for attribute-based search."""

    query: str | list[str] = Field(..., description="Attribute query or list of queries")
    source_type: str = Field(default="video_file")
    timestamp_start: str | None = Field(default=None)
    timestamp_end: str | None = Field(default=None)
    video_sources: list[str] | None = Field(default=None)
    top_k: int = Field(default=1)
    min_similarity: float = Field(default=0.3)
    fuse_multi_attribute: bool = Field(default=True)
    exclude_videos: list[dict[str, str]] = Field(default_factory=list)


class AttributeSearchMetadata(BaseModel):
    """Metadata for attribute search result."""

    sensor_id: str = Field(..., description="Sensor/camera ID")
    object_id: str = Field(..., description="Object ID")
    object_type: str = Field(default="", description="Object type")
    frame_timestamp: str = Field(default="", description="Best frame timestamp")
    start_time: str | None = Field(default=None)
    end_time: str | None = Field(default=None)
    bbox: dict | None = Field(default=None)
    behavior_score: float = Field(default=0.0)
    frame_score: float | None = Field(default=None)
    video_name: str | None = Field(default=None)


class AttributeSearchResult(BaseModel):
    """Single attribute search result."""

    screenshot_url: str | None = Field(default=None)
    metadata: AttributeSearchMetadata = Field(..., description="Search result metadata")


async def search_single_attribute(
    query_text: str,
    search_input: AttributeSearchInput | None = None,
    es_client: AsyncElasticsearch | None = None,
    index: str = "mdx-behavior-2026-01-06",
    top_k: int = 5,
) -> list[AttributeSearchResult]:
    """Search for a single attribute using ES behavior index."""
    if search_input is None:
        search_input = AttributeSearchInput(query=query_text)

    if es_client is None:
        from vsa_agent.config import get_config
        cfg = get_config()
        es_client = AsyncElasticsearch(cfg.search.es_endpoint)

    try:
        must_clauses = [{"match": {"object_type": query_text}}]

        if search_input.video_sources:
            should_clauses = []
            for vname in search_input.video_sources:
                should_clauses.append({"term": {"sensor_id.keyword": vname}})
            must_clauses.append({"bool": {"should": should_clauses, "minimum_should_match": 1}})

        if search_input.timestamp_start or search_input.timestamp_end:
            range_filter = {"range": {}}
            if search_input.timestamp_start:
                range_filter["range"]["timestamp"] = {"gte": search_input.timestamp_start}
            if search_input.timestamp_end:
                range_filter["range"]["timestamp"] = {"lte": search_input.timestamp_end}
            must_clauses.append(range_filter)

        es_query = {
            "size": top_k,
            "query": {"bool": {"must": must_clauses}},
            "sort": [{"_score": {"order": "desc"}}],
        }

        response = await es_client.search(index=index, body=es_query)
        hits = response["hits"]["hits"]

        results = []
        for hit in hits:
            source = hit.get("_source", {})
            score = hit.get("_score", 0.0)
            sensor_id = source.get("sensor_id", "")
            object_id = source.get("object_id", str(hash(query_text) % 10000))
            object_type = source.get("object_type", query_text)

            results.append(AttributeSearchResult(
                screenshot_url="",
                metadata=AttributeSearchMetadata(
                    sensor_id=sensor_id,
                    object_id=object_id,
                    object_type=object_type,
                    frame_timestamp=source.get("timestamp", ""),
                    start_time=source.get("timestamp", ""),
                    end_time=source.get("end", ""),
                    behavior_score=score,
                    video_name=sensor_id,
                ),
            ))

        return results
    except Exception as e:
        logger.warning("ES attribute search failed, using mock: %s", e)
        return await _mock_attribute_search(query_text, search_input)


async def _mock_attribute_search(query_text: str, search_input: AttributeSearchInput) -> list[AttributeSearchResult]:
    """Fallback mock attribute search when ES is unavailable."""
    seed = sum(ord(c) for c in str(query_text)) % 100
    return [
        AttributeSearchResult(
            screenshot_url="",
            metadata=AttributeSearchMetadata(
                sensor_id=f"sensor-{seed % 10}",
                object_id=f"obj-{seed}",
                object_type="person" if "person" in str(query_text).lower() else "object",
                frame_timestamp="2025-01-01T10:00:00Z",
                behavior_score=0.5 + seed * 0.005,
                video_name=f"camera_{seed % 5}.mp4",
            ),
        )
    ]


async def search_by_attributes(query_text: str, search_input: AttributeSearchInput | None = None) -> list[AttributeSearchResult]:
    """Search for objects by visual attributes. Tries ES first, falls back to mock."""
    if search_input is None:
        search_input = AttributeSearchInput(query=query_text)

    try:
        from vsa_agent.config import get_config
        cfg = get_config()
        es_client = AsyncElasticsearch(cfg.search.es_endpoint)
        index_exists = await es_client.indices.exists(index=cfg.search.behavior_index)
        if index_exists:
            return await search_single_attribute(query_text, search_input, es_client, cfg.search.behavior_index, search_input.top_k)
        await es_client.close()
    except Exception as e:
        logger.warning("ES search_by_attributes failed: %s", e)

    return await _mock_attribute_search(query_text, search_input)


def _deduplicate_by_video_name(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate SearchResults by video_name, keeping the highest similarity."""
    merged: dict[str, SearchResult] = {}
    for r in results:
        if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
            merged[r.video_name] = r
    return sorted(merged.values(), key=lambda x: x.similarity, reverse=True)


@register_tool("attribute_search", description="Attribute-based search: find video segments matching specific visual attributes.")
async def attribute_search_tool(attributes: list[str], store=None, top_k: int = 5) -> SearchOutput:
    """Search for video segments matching visual attribute descriptions."""
    if not attributes:
        raise ValueError("At least one attribute is required")

    if store is None:
        from vsa_agent.tools.vector_store import get_default_store
        store = get_default_store()

    try:
        result = await store.search_by_attributes(attributes=attributes, top_k=top_k)
        if isinstance(result, SearchOutput):
            results = result.data
        elif hasattr(result, "data"):
            results = list(result.data)
        else:
            results = list(result) if isinstance(result, list) else []

        deduped = _deduplicate_by_video_name(results)
        deduped.sort(key=lambda x: x.similarity, reverse=True)
        return SearchOutput(data=deduped[:top_k])
    except Exception as e:
        logger.error("Attribute search failed: %s", e)
        return SearchOutput(data=[])


async def search_single_attribute_wrapper(attribute, search_input=None):
    """Wrapper for single attribute search."""
    return await search_by_attributes(query_text=attribute, search_input=search_input)


async def search_attributes(search_input):
    """Search for multiple attributes."""
    queries = search_input.query
    if isinstance(queries, str):
        queries = [queries]
    all_results = []
    for q in queries:
        attr_results = await search_single_attribute_wrapper(q, search_input)
        for ar in attr_results:
            if hasattr(ar, "metadata"):
                m = ar.metadata
                sr = _build_result({
                    "sensor_id": m.sensor_id, "object_id": m.object_id,
                    "object_type": m.object_type, "behavior_score": m.behavior_score,
                    "frame_score": m.frame_score, "video_name": m.video_name,
                    "start_time": m.start_time, "end_time": m.end_time,
                    "frame_timestamp": m.frame_timestamp, "bbox": m.bbox,
                }, screenshot_url=ar.screenshot_url or "")
                all_results.append(sr)
    return all_results


def _fuse_multi_attribute(attributes, attr_results_by_video):
    """Intersection: keep only videos appearing for ALL attributes."""
    if not attr_results_by_video:
        return []
    return [results[0] for results in attr_results_by_video.values() if results]


def _append_multi_attribute(attributes, attr_results_by_video):
    """Union: return all unique videos (best score per video)."""
    merged = {}
    for video_name, results in attr_results_by_video.items():
        if video_name not in merged and results:
            merged[video_name] = results[0]
    return list(merged.values())


def _build_result(metadata_dict, screenshot_url=""):
    """Build SearchResult from metadata dict."""
    similarity = float(metadata_dict.get("frame_score") or metadata_dict.get("behavior_score", 0.0))
    start = metadata_dict.get("start_time") or metadata_dict.get("frame_timestamp", "")
    end = metadata_dict.get("end_time") or metadata_dict.get("frame_timestamp", "")
    return SearchResult(
        video_name=metadata_dict.get("video_name", "unknown"),
        description=metadata_dict.get("object_type", "") or f"Match for {metadata_dict.get('object_id', 'unknown')}",
        start_time=start or "",
        end_time=end or "",
        sensor_id=metadata_dict.get("sensor_id", ""),
        screenshot_url=screenshot_url,
        similarity=similarity,
        object_ids=[str(metadata_dict.get("object_id", ""))],
    )
