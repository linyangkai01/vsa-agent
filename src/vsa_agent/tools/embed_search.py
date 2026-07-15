"""Embed search tool — semantic vector search for video content.

Generates embeddings from text queries and searches Elasticsearch
for matching video segments using KNN vector search.

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import json
import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, Field

from vsa_agent.config import SearchBackendConfig
from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput

logger = logging.getLogger(__name__)

# Base timestamp for offset conversion
BASE_2025 = datetime(2025, 1, 1, tzinfo=UTC)


class SearchDependencyError(RuntimeError):
    """A required production search dependency is unavailable."""


# ===== Data Models =====


class EmbedSearchResultItem(BaseModel):
    """A single embed search result with all fields extracted."""

    video_name: str = Field(default="", description="Video filename")
    description: str = Field(default="", description="Video/sensor description")
    start_time: str = Field(default="", description="Start time (ISO format)")
    end_time: str = Field(default="", description="End time (ISO format)")
    sensor_id: str = Field(default="", description="Sensor/stream UUID")
    screenshot_url: str = Field(default="", description="Screenshot URL")
    similarity_score: float = Field(default=0.0, description="Cosine similarity score")


class EmbedSearchOutput(BaseModel):
    """Output of embed search."""

    query_embedding: list[float] = Field(default_factory=list, description="Query embedding vector")
    results: list[EmbedSearchResultItem] = Field(default_factory=list, description="Search results")


class QueryInput(BaseModel):
    """Query input model for schema validation."""

    id: str = Field(default="", description="Query ID")
    params: dict[str, str] = Field(default_factory=dict, description="Query parameters")
    prompts: dict[str, str] = Field(default_factory=dict, description="Query prompts")
    response: str = Field(default="", description="Query response")
    embeddings: list[dict[str, Any]] = Field(default_factory=list, description="Query embeddings")
    source_type: str = Field(default="video_file", description="video_file or rtsp")
    exclude_videos: list[dict[str, str]] = Field(default_factory=list, description="Videos to exclude")


# ===== Embedding Generation =====


async def _generate_query_embedding(query_input: QueryInput, embed_client=None) -> list[float]:
    """Generate query embedding from text.

    Uses OpenAI-compatible embedding API if embed_client is provided.
    Falls back to deterministic mock vector for testing.
    """
    if query_input.embeddings:
        vector = query_input.embeddings[0].get("vector", [])
        if isinstance(vector, list):
            return [float(v) for v in vector]

    query_text = query_input.params.get("query", "")
    if not query_text:
        return []

    # If embed_client is provided, use it for real embeddings
    if embed_client is not None:
        try:
            return await embed_client.embed_query(query_text)
        except Exception as error:
            logger.warning("Embedding generation failed; mock fallback enabled error_type=%s", type(error).__name__)

    # Deterministic mock: hash-based vector for testing
    seed = sum(ord(c) for c in query_text) % 1000
    return [seed * 0.001, seed * 0.002, seed * 0.003, (seed % 100) * 0.01]


async def _embed_query(query_input: QueryInput, search_config: SearchBackendConfig) -> list[float]:
    """Generate a validated query vector under the explicit fallback policy."""
    if search_config.force_mock_embedding:
        if not search_config.allow_mock_fallback:
            raise SearchDependencyError("production search configuration is invalid")
        return await _generate_query_embedding(query_input)

    embed_client = _create_default_embed_client(allow_mock_fallback=search_config.allow_mock_fallback)
    if embed_client is None:
        if search_config.allow_mock_fallback:
            return await _generate_query_embedding(query_input)
        raise SearchDependencyError("production query embedding is unavailable")
    try:
        vector = await embed_client.embed_query(query_input.params.get("query", ""))
    except Exception:
        if search_config.allow_mock_fallback:
            return await _generate_query_embedding(query_input)
        raise SearchDependencyError("production query embedding is unavailable") from None
    if (
        not isinstance(vector, list | tuple)
        or not vector
        or any(type(value) is not float or not math.isfinite(value) for value in vector)
    ):
        raise SearchDependencyError("production query embedding is invalid")
    return list(vector)


# ===== ES Query Building =====


def _build_es_query(
    query_input: QueryInput,
    query_embedding: list[float],
    es_index: str,
    top_k: int = 10,
    min_cosine_similarity: float = 0.0,
    vector_field: str = "vector",
) -> dict[str, Any]:
    """Build Elasticsearch KNN search query.

    Args:
        query_input: The query input with filter parameters.
        query_embedding: The query embedding vector.
        es_index: Elasticsearch index name.
        top_k: Maximum results to return.
        min_cosine_similarity: Minimum cosine similarity threshold.

    Returns:
        ES search query body dict.
    """
    # Build filter conditions
    filters: list[dict[str, Any]] = []

    source_type = query_input.source_type
    if source_type in {"video_file", "recorded_video"}:
        filters.append({"term": {"source_type": "recorded_video"}})
    elif source_type:
        filters.append({"term": {"source_type": source_type}})

    # Add video_sources filter if provided
    video_sources_str = query_input.params.get("video_sources", "")
    if video_sources_str:
        try:
            video_sources = json.loads(video_sources_str) if video_sources_str.startswith("[") else [video_sources_str]
            if isinstance(video_sources, list) and video_sources:
                filters.append({"terms": {"video_name": [str(value) for value in video_sources]}})
        except (json.JSONDecodeError, TypeError):
            pass

    # Add timestamp filters if provided
    timestamp_start = query_input.params.get("timestamp_start", "")
    timestamp_end = query_input.params.get("timestamp_end", "")
    if timestamp_start:
        filters.append({"range": {"end_time": {"gte": timestamp_start}}})
    if timestamp_end:
        filters.append({"range": {"start_time": {"lte": timestamp_end}}})

    # Build the query body
    query_body: dict[str, Any] = {
        "size": top_k,
        "_source": [
            "asset_id",
            "video_id",
            "segment_id",
            "sensor_id",
            "source_type",
            "job_id",
            "job_attempt",
            "readiness",
            "pipeline_version",
            "video_name",
            "description",
            "start_time",
            "end_time",
            "screenshot_url",
        ],
        "query": {
            "script_score": {
                "query": {"match_all": {}} if not filters else {"bool": {"filter": filters}},
                "script": {
                    "source": f"cosineSimilarity(params.query_vector, '{vector_field}') + 1.0",
                    "params": {"query_vector": query_embedding},
                },
            }
        },
    }

    # Apply min_cosine_similarity as a post-filter
    if min_cosine_similarity > 0:
        # Convert cosine similarity threshold to script_score range
        query_body["query"]["script_score"]["min_score"] = min_cosine_similarity + 1.0

    return query_body


# ===== Result Processing =====


async def _process_search_hit(
    hit: dict,
    min_cosine_similarity: float = 0.0,
    exclude_videos: list[dict[str, str]] | None = None,
) -> EmbedSearchResultItem | None:
    """Process a single ES search hit into EmbedSearchResultItem.

    Handles nested KNN results, UUID extraction, and score conversion.

    Args:
        hit: Raw ES hit dict.
        min_cosine_similarity: Minimum cosine similarity threshold.
        exclude_videos: List of videos to exclude.

    Returns:
        EmbedSearchResultItem or None if filtered out.
    """
    if exclude_videos is None:
        exclude_videos = []

    # Extract score: ES returns cosineSimilarity + 1.0, convert back
    score = hit.get("_score", 0.0)
    similarity = round(score - 1.0, 4)
    if similarity < min_cosine_similarity:
        return None

    source = hit.get("_source", {})
    metadata = source.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    sensor = source.get("sensor", {})
    if not isinstance(sensor, dict):
        sensor = {}
    metadata_sensor = metadata.get("sensor", {})
    if not isinstance(metadata_sensor, dict):
        metadata_sensor = {}
    sensor_id = (
        source.get("sensor_id")
        or source.get("sensorId")
        or sensor.get("id")
        or source.get("camera_id")
        or metadata.get("sensor_id")
        or metadata.get("sensorId")
        or metadata_sensor.get("id")
        or metadata.get("camera_id")
        or ""
    )

    # Extract video_name
    video_name = ""
    inner_hits = hit.get("inner_hits", {})
    if inner_hits:
        for key, ih in inner_hits.items():
            ih_hits = ih.get("hits", {}).get("hits", [])
            if ih_hits:
                ih_source = ih_hits[0].get("_source", {})
                video_name = ih_source.get("video_name", ih_source.get("filename", ""))

    if not video_name:
        video_name = (
            source.get("video_name")
            or source.get("filename")
            or source.get("file_name")
            or source.get("videoPath")
            or source.get("video_path")
            or metadata.get("video_name")
            or metadata.get("filename")
            or metadata.get("file_name")
            or metadata.get("videoPath")
            or metadata.get("video_path")
            or ""
        )

    if not video_name:
        video_name = sensor_id or "unknown"

    # Check exclude list
    for exclude in exclude_videos:
        if sensor_id == exclude.get("sensor_id", ""):
            return None

    return EmbedSearchResultItem(
        video_name=video_name,
        description=(
            source.get("description")
            or source.get("caption")
            or source.get("summary")
            or source.get("text")
            or sensor.get("description", "")
            or metadata.get("description")
            or metadata.get("caption")
            or metadata.get("summary")
            or metadata.get("text")
            or metadata_sensor.get("description", "")
        ),
        start_time=(
            source.get("start_time")
            or source.get("timestamp")
            or source.get("start")
            or metadata.get("start_time")
            or metadata.get("timestamp")
            or metadata.get("start")
            or ""
        ),
        end_time=(
            source.get("end_time")
            or source.get("timestamp_end")
            or source.get("end")
            or metadata.get("end_time")
            or metadata.get("timestamp_end")
            or metadata.get("end")
            or ""
        ),
        sensor_id=sensor_id,
        screenshot_url=(
            source.get("screenshot_url")
            or source.get("thumbnail_url")
            or metadata.get("screenshot_url")
            or metadata.get("thumbnail_url")
            or ""
        ),
        similarity_score=similarity,
    )


def _create_es_client(search_config: SearchBackendConfig) -> AsyncElasticsearch:
    return AsyncElasticsearch(
        search_config.es_endpoint,
        request_timeout=search_config.request_timeout_sec,
        verify_certs=search_config.verify_certs,
    )


def _json_compatible_client(client: Any) -> Any:
    options = getattr(client, "options", None)
    if callable(options):
        return options(headers={"accept": "application/json", "content-type": "application/json"})
    return client


def _create_readiness_repository():
    from vsa_agent.config import get_config
    from vsa_agent.recorded_video.repository import JobRepository

    database_path = get_config().recorded_video.data_root / "recorded-video.sqlite3"
    if not database_path.is_file():
        raise SearchDependencyError("recorded-video readiness database is unavailable")
    return JobRepository(database_path)


def _readiness_identity(hit: Mapping[str, Any]) -> tuple[str, str, str, int] | None:
    source = hit.get("_source")
    readiness = source.get("readiness") if isinstance(source, Mapping) else None
    if not isinstance(readiness, Mapping) or set(readiness) != {
        "asset_id",
        "job_id",
        "pipeline_version",
        "attempt",
    }:
        return None
    asset_id = readiness.get("asset_id")
    job_id = readiness.get("job_id")
    pipeline_version = readiness.get("pipeline_version")
    attempt = readiness.get("attempt")
    if (
        not isinstance(asset_id, str)
        or not asset_id
        or not isinstance(job_id, str)
        or not job_id
        or not isinstance(pipeline_version, str)
        or not pipeline_version
        or type(attempt) is not int
        or attempt <= 0
    ):
        return None
    if (
        source.get("asset_id") != asset_id
        or source.get("job_id") != job_id
        or source.get("pipeline_version") != pipeline_version
        or source.get("job_attempt") != attempt
    ):
        return None
    return asset_id, job_id, pipeline_version, attempt


def _create_default_embed_client(*, allow_mock_fallback: bool = True):
    from vsa_agent.config import resolve_runtime_config
    from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

    runtime = resolve_runtime_config()
    embedding = runtime.embedding
    if embedding is None:
        return None
    return RTVICVEmbedClient(
        model=embedding.model,
        base_url=embedding.base_url,
        api_key=embedding.api_key,
        allow_mock_fallback=allow_mock_fallback,
    )


async def _search_real_es(
    query: str,
    top_k: int,
    search_config: SearchBackendConfig,
    *,
    readiness_repository=None,
    video_sources: list[str] | None = None,
    timestamp_start: str | None = None,
    timestamp_end: str | None = None,
    source_type: str = "video_file",
    min_cosine_similarity: float | None = None,
) -> SearchOutput | None:
    if not search_config.enabled or not search_config.es_endpoint:
        return None

    raw_es_client = _create_es_client(search_config)
    es_client = _json_compatible_client(raw_es_client)
    try:
        target_index = search_config.embed_index
        legacy_index = False
        index_exists = await es_client.indices.exists(index=target_index)
        if not index_exists and search_config.allow_mock_fallback:
            target_index = search_config.legacy_embed_index
            index_exists = await es_client.indices.exists(index=target_index)
            legacy_index = index_exists
        if not index_exists:
            if not search_config.allow_mock_fallback:
                raise SearchDependencyError("production search index is unavailable")
            return None

        query_input = QueryInput(
            params={
                "query": query,
                "top_k": str(top_k),
                "video_sources": json.dumps(video_sources or []),
                "timestamp_start": timestamp_start or "",
                "timestamp_end": timestamp_end or "",
            },
            source_type="" if legacy_index and source_type == "video_file" else source_type,
        )
        query_embedding = await _embed_query(query_input, search_config)
        if not query_embedding:
            raise SearchDependencyError("production query embedding is unavailable")

        threshold = max(
            search_config.embed_confidence_threshold,
            min_cosine_similarity or 0.0,
        )

        es_query = _build_es_query(
            query_input,
            query_embedding,
            target_index,
            top_k,
            threshold,
            vector_field=search_config.vector_field,
        )
        response = await es_client.search(index=target_index, body=es_query)
        hits = response.get("hits", {}).get("hits", [])

        repository = readiness_repository
        if repository is None:
            try:
                repository = _create_readiness_repository()
            except SearchDependencyError:
                if not search_config.allow_mock_fallback:
                    raise
        initialize = getattr(repository, "initialize", None)
        if callable(initialize):
            await initialize()

        ready_hits = []
        for hit in hits:
            if repository is None and search_config.allow_mock_fallback:
                ready_hits.append(hit)
                continue
            identity = _readiness_identity(hit) if isinstance(hit, Mapping) else None
            if identity is None:
                if search_config.allow_mock_fallback:
                    ready_hits.append(hit)
                continue
            try:
                ready = await repository.is_asset_search_ready(*identity)
            except Exception:
                raise SearchDependencyError("recorded-video readiness check is unavailable") from None
            if ready:
                ready_hits.append(hit)

        import asyncio

        processed = await asyncio.gather(*[_process_search_hit(hit, threshold) for hit in ready_hits])

        from vsa_agent.tools.search import SearchResult

        search_results = [
            SearchResult(
                video_name=item.video_name,
                description=item.description,
                start_time=item.start_time,
                end_time=item.end_time,
                sensor_id=item.sensor_id,
                screenshot_url=item.screenshot_url,
                similarity=item.similarity_score,
            )
            for item in processed
            if item is not None
        ]
        search_results.sort(key=lambda item: item.similarity, reverse=True)
        return SearchOutput(data=search_results[:top_k])
    except SearchDependencyError as error:
        if search_config is not None and not search_config.allow_mock_fallback:
            raise
        logger.warning(
            "ES search dependency failed; using explicit fallback profile error_type=%s", type(error).__name__
        )
    except Exception:
        if not search_config.allow_mock_fallback:
            raise SearchDependencyError("production search dependency is unavailable") from None
        raise
    finally:
        await raw_es_client.close()


# ===== Registered Tool =====


@register_tool(
    "embed_search",
    description="Semantic vector search: find video segments by text description "
    "using embedding similarity against Elasticsearch. Returns ranked SearchOutput.",
)
async def embed_search_tool(
    query: str,
    store=None,
    top_k: int = 10,
    video_sources: list[str] | None = None,
    timestamp_start: str | None = None,
    timestamp_end: str | None = None,
    source_type: str = "video_file",
    min_cosine_similarity: float | None = None,
) -> SearchOutput:
    """Search for videos matching a natural language description.

    Uses Elasticsearch KNN search with cosine similarity.
    Falls back to in-memory store if ES is not configured.

    Args:
        query: Natural language search description.
        store: Optional vector store for dependency injection (testing).
        top_k: Maximum number of results to return.

    Returns:
        SearchOutput with ranked matches.
    """
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

    # Try real ES first if configured.
    search_config = None
    try:
        from vsa_agent.config import get_config

        search_config = get_config().search
        if search_config.force_mock_embedding and not search_config.allow_mock_fallback:
            raise SearchDependencyError("production search configuration is invalid")
        es_output = await _search_real_es(
            query,
            top_k,
            search_config,
            video_sources=video_sources,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            source_type=source_type,
            min_cosine_similarity=min_cosine_similarity,
        )
        if es_output is not None:
            return es_output
    except SearchDependencyError:
        raise
    except Exception as error:
        if search_config is not None and not search_config.allow_mock_fallback:
            raise SearchDependencyError("production search dependency is unavailable") from None
        logger.warning("ES search failed; using explicit fallback profile error_type=%s", type(error).__name__)

    if search_config is not None and not search_config.allow_mock_fallback:
        raise SearchDependencyError("production search dependency is unavailable")

    # Fallback: in-memory store
    if store is None:
        from vsa_agent.tools.vector_store import get_default_store

        store = get_default_store()

    try:
        result = await store.search(query=query, top_k=top_k)
        if isinstance(result, SearchOutput):
            return result
        if hasattr(result, "data"):
            return SearchOutput(data=list(result.data))
        return SearchOutput(data=list(result) if isinstance(result, list) else [])
    except Exception as error:
        logger.error("Embed search fallback failed error_type=%s", type(error).__name__)
        return SearchOutput(data=[])
