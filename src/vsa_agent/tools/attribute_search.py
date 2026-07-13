"""Attribute search tool for object-level visual matching."""

import logging
from typing import Any

from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput, SearchResult

logger = logging.getLogger(__name__)


class AttributeSearchInput(BaseModel):
    """Input for attribute-based search."""

    query: str | list[str] = Field(
        ...,
        description="Attribute query or list of queries (e.g., 'person with red hat' or ['person', 'red hat'])",
    )
    source_type: str = Field(
        default="video_file",
        description="Type of video source: 'video_file' for uploaded videos, 'rtsp' for live/camera streams.",
    )
    timestamp_start: str | None = Field(default=None, description="Start time filter")
    timestamp_end: str | None = Field(default=None, description="End time filter")
    video_sources: list[str] | None = Field(default=None, description="Filter by video source names")
    top_k: int = Field(default=1, description="Number of results to return")
    min_similarity: float = Field(default=0.3, description="Minimum cosine similarity threshold")
    fuse_multi_attribute: bool = Field(
        default=True,
        description=(
            "If True, keep only videos matched across attributes. If False, append matches from each attribute."
        ),
    )
    exclude_videos: list[dict[str, str]] = Field(default_factory=list, description="Videos to exclude")


class AttributeSearchMetadata(BaseModel):
    """Metadata for attribute search result."""

    sensor_id: str = Field(..., description="Sensor/camera ID")
    object_id: str = Field(..., description="Object ID")
    object_type: str = Field(default="", description="Object type")
    frame_timestamp: str = Field(default="", description="Best frame timestamp")
    start_time: str | None = Field(default=None, description="Start time")
    end_time: str | None = Field(default=None, description="End time")
    bbox: dict | None = Field(default=None, description="Bounding box")
    behavior_score: float = Field(default=0.0, description="Behavior-level similarity")
    frame_score: float | None = Field(default=None, description="Frame-level similarity")
    video_name: str | None = Field(default=None, description="Video name")


class AttributeSearchResult(BaseModel):
    """Single attribute search result with metadata."""

    screenshot_url: str | None = Field(default=None, description="Screenshot URL")
    metadata: AttributeSearchMetadata = Field(..., description="Search result metadata")


def _build_behavior_query(query_text: str, search_input: AttributeSearchInput) -> dict[str, Any]:
    """Build a minimal ES query for behavior index lookup."""
    must_clauses: list[dict[str, Any]] = [{"match": {"object_type": query_text}}]

    if search_input.video_sources:
        should_clauses = [{"term": {"sensor_id.keyword": v}} for v in search_input.video_sources]
        should_clauses.extend({"wildcard": {"sensor_id.keyword": f"*{v}*"}} for v in search_input.video_sources)
        must_clauses.append({"bool": {"should": should_clauses, "minimum_should_match": 1}})

    if search_input.timestamp_start or search_input.timestamp_end:
        range_clause: dict[str, Any] = {"range": {"timestamp": {}}}
        if search_input.timestamp_start:
            range_clause["range"]["timestamp"]["gte"] = search_input.timestamp_start
        if search_input.timestamp_end:
            range_clause["range"]["timestamp"]["lte"] = search_input.timestamp_end
        must_clauses.append(range_clause)

    return {
        "size": search_input.top_k,
        "_source": True,
        "query": {"bool": {"must": must_clauses}},
        "sort": [{"_score": {"order": "desc"}}],
    }


def _build_frame_lookup_query(sensor_id: str, object_id: str, frame_timestamp: str) -> dict[str, Any]:
    """Build a minimal ES query for frame-level enrichment."""
    return {
        "size": 1,
        "_source": True,
        "query": {
            "bool": {
                "must": [
                    {"term": {"sensor_id.keyword": sensor_id}},
                    {"term": {"object_id.keyword": str(object_id)}},
                    {"term": {"timestamp.keyword": frame_timestamp}},
                ]
            }
        },
    }


async def _perform_frame_lookups(
    results: list[AttributeSearchResult],
    es_client: AsyncElasticsearch | None,
    frames_index: str | None,
) -> list[AttributeSearchResult]:
    """Enrich attribute matches with frame-level bbox/frame score when available."""
    if es_client is None or not frames_index:
        return results

    enriched: list[AttributeSearchResult] = []
    for result in results:
        metadata = result.metadata
        if not (metadata.sensor_id and metadata.object_id and metadata.frame_timestamp):
            enriched.append(result)
            continue

        try:
            response = await es_client.search(
                index=frames_index,
                body=_build_frame_lookup_query(metadata.sensor_id, metadata.object_id, metadata.frame_timestamp),
            )
            hits = response.get("hits", {}).get("hits", [])
            if hits:
                frame_source = hits[0].get("_source", {})
                metadata = metadata.model_copy(
                    update={
                        "bbox": frame_source.get("bbox", metadata.bbox),
                        "frame_score": frame_source.get("score", frame_source.get("frame_score", metadata.frame_score)),
                        "frame_timestamp": frame_source.get("timestamp", metadata.frame_timestamp),
                    }
                )
                result = result.model_copy(update={"metadata": metadata})
        except Exception as exc:
            logger.debug("Frame lookup failed for %s/%s: %s", metadata.sensor_id, metadata.object_id, exc)

        enriched.append(result)

    return enriched


def _deduplicate_by_object(results: list[AttributeSearchResult]) -> list[AttributeSearchResult]:
    """Deduplicate by `(sensor_id, object_id)`, keeping the highest score."""
    merged: dict[tuple[str, str], AttributeSearchResult] = {}
    for result in results:
        key = (result.metadata.sensor_id, result.metadata.object_id)
        score = (
            result.metadata.frame_score if result.metadata.frame_score is not None else result.metadata.behavior_score
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = result
            continue
        existing_score = (
            existing.metadata.frame_score
            if existing.metadata.frame_score is not None
            else existing.metadata.behavior_score
        )
        if score > existing_score:
            merged[key] = result
    return list(merged.values())


def _group_by_video(results: list[AttributeSearchResult]) -> dict[str, list[AttributeSearchResult]]:
    grouped: dict[str, list[AttributeSearchResult]] = {}
    for result in results:
        video_name = result.metadata.video_name or result.metadata.sensor_id
        grouped.setdefault(video_name, []).append(result)
    return grouped


def _fuse_multi_attribute(
    attributes: list[str],
    attr_results_by_query: dict[str, list[AttributeSearchResult]],
) -> list[AttributeSearchResult]:
    """Keep only videos that have at least one hit for every queried attribute."""
    if not attributes or not attr_results_by_query:
        return []
    matched_videos_by_query: list[set[str]] = []
    for attribute in attributes:
        results = attr_results_by_query.get(attribute, [])
        matched_videos_by_query.append({r.metadata.video_name or r.metadata.sensor_id for r in results})
    if not matched_videos_by_query:
        return []
    allowed_videos = set.intersection(*matched_videos_by_query)
    fused: list[AttributeSearchResult] = []
    for attribute in attributes:
        for result in attr_results_by_query.get(attribute, []):
            video_name = result.metadata.video_name or result.metadata.sensor_id
            if video_name in allowed_videos:
                fused.append(result)
    return fused


def _append_multi_attribute(
    attributes: list[str],
    attr_results_by_query: dict[str, list[AttributeSearchResult]],
) -> list[AttributeSearchResult]:
    """Return the union of all matched videos/results."""
    appended: list[AttributeSearchResult] = []
    for attribute in attributes:
        appended.extend(attr_results_by_query.get(attribute, []))
    return appended


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
                start_time=search_input.timestamp_start,
                end_time=search_input.timestamp_end,
                behavior_score=0.5 + seed * 0.005,
                video_name=f"camera_{seed % 5}.mp4",
            ),
        )
    ]


async def search_single_attribute(
    query_text: str,
    search_input: AttributeSearchInput | None = None,
    es_client: AsyncElasticsearch | None = None,
    index: str = "mdx-behavior-2026-01-06",
    top_k: int = 5,
    frames_index: str | None = None,
) -> list[AttributeSearchResult]:
    """Search for one attribute. Uses ES when available, otherwise falls back to mock."""
    if search_input is None:
        search_input = AttributeSearchInput(query=query_text, top_k=top_k)

    close_client = False
    if es_client is None:
        from vsa_agent.config import get_config

        search_config = get_config().search
        if not search_config.enabled or not search_config.es_endpoint:
            return await _mock_attribute_search(query_text, search_input)
        es_client = AsyncElasticsearch(search_config.es_endpoint)
        close_client = True

    try:
        response = await es_client.search(index=index, body=_build_behavior_query(query_text, search_input))
        hits = response.get("hits", {}).get("hits", [])

        results: list[AttributeSearchResult] = []
        for hit in hits:
            source = hit.get("_source", {})
            behavior_score = float(hit.get("_score", 0.0))
            if behavior_score < search_input.min_similarity:
                continue

            sensor_id = source.get("sensor_id", "")
            object_id = str(source.get("object_id", str(hash(query_text) % 10000)))
            object_type = source.get("object_type", query_text)
            frame_timestamp = source.get("timestamp", "")

            # Exclude exact sensor matches from previous critic rejections.
            if any(sensor_id == item.get("sensor_id", "") for item in search_input.exclude_videos):
                continue

            results.append(
                AttributeSearchResult(
                    screenshot_url="",
                    metadata=AttributeSearchMetadata(
                        sensor_id=sensor_id,
                        object_id=object_id,
                        object_type=object_type,
                        frame_timestamp=frame_timestamp,
                        start_time=source.get("timestamp", search_input.timestamp_start),
                        end_time=source.get("end", search_input.timestamp_end),
                        behavior_score=behavior_score,
                        video_name=source.get("video_name", sensor_id),
                    ),
                )
            )

        return await _perform_frame_lookups(results, es_client, frames_index)
    except Exception as exc:
        logger.warning("ES attribute search failed, using mock: %s", exc)
        return await _mock_attribute_search(query_text, search_input)
    finally:
        if close_client:
            await es_client.close()


async def search_by_attributes(
    query_text: str,
    search_input: AttributeSearchInput | None = None,
    allow_mock_fallback: bool = True,
) -> list[AttributeSearchResult]:
    """Search by one attribute. Tries ES first, optionally falls back to mock."""
    if search_input is None:
        search_input = AttributeSearchInput(query=query_text)

    es_client: AsyncElasticsearch | None = None
    try:
        from vsa_agent.config import get_config

        search_config = get_config().search
        if not search_config.enabled or not search_config.es_endpoint:
            if allow_mock_fallback:
                return await _mock_attribute_search(query_text, search_input)
            return []
        es_client = AsyncElasticsearch(search_config.es_endpoint)
        index_exists = await es_client.indices.exists(index=search_config.behavior_index)
        if index_exists:
            return await search_single_attribute(
                query_text,
                search_input,
                es_client,
                search_config.behavior_index,
                search_input.top_k,
                search_config.frames_index,
            )
    except Exception as exc:
        logger.warning("ES search_by_attributes failed: %s", exc)
    finally:
        if es_client is not None:
            await es_client.close()

    if allow_mock_fallback:
        return await _mock_attribute_search(query_text, search_input)
    return []


async def search_attributes(
    search_input: AttributeSearchInput,
    allow_mock_fallback: bool = True,
) -> list[SearchResult]:
    """Search multiple attributes and merge according to `fuse_multi_attribute`."""
    queries = search_input.query if isinstance(search_input.query, list) else [search_input.query]
    per_query_results: dict[str, list[AttributeSearchResult]] = {}
    for query in queries:
        per_query_results[query] = _deduplicate_by_object(
            await search_by_attributes(query, search_input, allow_mock_fallback=allow_mock_fallback)
        )

    merged_results = (
        _fuse_multi_attribute(queries, per_query_results)
        if search_input.fuse_multi_attribute
        else _append_multi_attribute(queries, per_query_results)
    )

    search_results: list[SearchResult] = []
    for result in _deduplicate_by_object(merged_results):
        metadata = result.metadata
        score = metadata.frame_score if metadata.frame_score is not None else metadata.behavior_score
        search_results.append(
            SearchResult(
                video_name=metadata.video_name or metadata.sensor_id or "unknown",
                description=metadata.object_type or f"Match for {metadata.object_id}",
                start_time=metadata.start_time or metadata.frame_timestamp or "",
                end_time=metadata.end_time or metadata.frame_timestamp or "",
                sensor_id=metadata.sensor_id,
                screenshot_url=result.screenshot_url or "",
                similarity=float(score),
                object_ids=[str(metadata.object_id)],
            )
        )

    search_results.sort(key=lambda item: item.similarity, reverse=True)
    return search_results[: search_input.top_k]


def _deduplicate_by_video_name(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate SearchResults by video_name, keeping the highest similarity."""
    merged: dict[str, SearchResult] = {}
    for result in results:
        if result.video_name not in merged or result.similarity > merged[result.video_name].similarity:
            merged[result.video_name] = result
    return sorted(merged.values(), key=lambda item: item.similarity, reverse=True)


@register_tool(
    "attribute_search",
    description="Attribute-based search: find video segments matching specific visual attributes.",
)
async def attribute_search_tool(attributes: list[str], store=None, top_k: int = 5) -> SearchOutput:
    """Search for video segments matching visual attribute descriptions."""
    if not attributes:
        raise ValueError("At least one attribute is required")

    # ES-first path for current project use.
    try:
        search_input = AttributeSearchInput(query=attributes, top_k=top_k, fuse_multi_attribute=False)
        results = await search_attributes(search_input, allow_mock_fallback=False)
        if results:
            return SearchOutput(data=results[:top_k])
    except Exception as exc:
        logger.warning("ES attribute search path failed, falling back to store: %s", exc)

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
        deduped.sort(key=lambda item: item.similarity, reverse=True)
        return SearchOutput(data=deduped[:top_k])
    except Exception as exc:
        logger.error("Attribute search failed: %s", exc)
        return SearchOutput(data=[])
