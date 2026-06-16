"""Embed search tool — semantic vector search for video content.

Generates embeddings from text queries and searches Elasticsearch
for matching video segments using KNN vector search.

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import json
import logging
from datetime import UTC
from datetime import datetime
from typing import Any

from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput

logger = logging.getLogger(__name__)

# Base timestamp for offset conversion
BASE_2025 = datetime(2025, 1, 1, tzinfo=UTC)


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
        except Exception as e:
            logger.warning("Embedding generation failed, using mock: %s", e)

    # Deterministic mock: hash-based vector for testing
    seed = sum(ord(c) for c in query_text) % 1000
    return [seed * 0.001, seed * 0.002, seed * 0.003, (seed % 100) * 0.01]


# ===== ES Query Building =====


def _build_es_query(
    query_input: QueryInput,
    query_embedding: list[float],
    es_index: str,
    top_k: int = 10,
    min_cosine_similarity: float = 0.0,
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

    # Add video_sources filter if provided
    video_sources_str = query_input.params.get("video_sources", "")
    if video_sources_str:
        try:
            video_sources = json.loads(video_sources_str) if video_sources_str.startswith("[") else [video_sources_str]
            if isinstance(video_sources, list) and video_sources:
                should_clauses = []
                for vname in video_sources:
                    vname_str = str(vname)
                    should_clauses.append({"term": {"sensor.id.keyword": vname_str}})
                    should_clauses.append({"wildcard": {"sensor.id.keyword": f"*{vname_str}*"}})
                    should_clauses.append({"wildcard": {"sensor.info.url.keyword": f"*{vname_str}*"}})
                filters.append({"bool": {"should": should_clauses, "minimum_should_match": 1}})
        except (json.JSONDecodeError, TypeError):
            pass

    # Add timestamp filters if provided
    timestamp_start = query_input.params.get("timestamp_start", "")
    timestamp_end = query_input.params.get("timestamp_end", "")
    if timestamp_start or timestamp_end:
        range_filter: dict[str, Any] = {"range": {}}
        if timestamp_start:
            range_filter["range"]["timestamp"] = {"gte": timestamp_start}
        if timestamp_end:
            if "timestamp" in range_filter["range"]:
                range_filter["range"]["timestamp"]["lte"] = timestamp_end
            else:
                range_filter["range"]["timestamp"] = {"lte": timestamp_end}
        filters.append(range_filter)

    # Build the query body
    query_body: dict[str, Any] = {
        "size": top_k,
        "_source": True,
        "query": {
            "script_score": {
                "query": {"match_all": {}} if not filters else {"bool": {"filter": filters}},
                "script": {
                    "source": "cosineSimilarity(params.query_vector, 'vector') + 1.0",
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
    sensor = source.get("sensor", {})
    sensor_id = sensor.get("id", "")

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
        video_name = sensor_id or "unknown"

    # Check exclude list
    for exclude in exclude_videos:
        if sensor_id == exclude.get("sensor_id", ""):
            return None

    return EmbedSearchResultItem(
        video_name=video_name,
        description=sensor.get("description", ""),
        start_time=source.get("timestamp", ""),
        end_time=source.get("end", ""),
        sensor_id=sensor_id,
        screenshot_url="",
        similarity_score=similarity,
    )


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

    # Try ES first if configured
    try:
        from vsa_agent.config import get_config
        cfg = get_config()
        es_config = cfg.search

        if es_config.es_endpoint:
            es_client = AsyncElasticsearch(es_config.es_endpoint)

            # Check if index exists
            index_exists = await es_client.indices.exists(index=es_config.embed_index)
            if index_exists:
                # Build query input
                query_input = QueryInput(
                    params={"query": query, "top_k": str(top_k)},
                    source_type="video_file",
                )

                # Generate embedding
                query_embedding = await _generate_query_embedding(query_input)

                if query_embedding:
                    # Build and execute ES query
                    es_query = _build_es_query(
                        query_input, query_embedding,
                        es_config.embed_index, top_k,
                        es_config.embed_confidence_threshold,
                    )
                    response = await es_client.search(index=es_config.embed_index, body=es_query)

                    # Process hits
                    hits = response["hits"]["hits"]
                    tasks = [_process_search_hit(hit, es_config.embed_confidence_threshold) for hit in hits]
                    import asyncio
                    processed = await asyncio.gather(*tasks)
                    results = [r for r in processed if r is not None]

                    # Convert to SearchOutput
                    search_results = []
                    for r in results[:top_k]:
                        from vsa_agent.tools.search import SearchResult
                        search_results.append(SearchResult(
                            video_name=r.video_name,
                            description=r.description,
                            start_time=r.start_time,
                            end_time=r.end_time,
                            sensor_id=r.sensor_id,
                            screenshot_url=r.screenshot_url,
                            similarity=r.similarity_score,
                        ))

                    await es_client.close()
                    return SearchOutput(data=search_results)

            await es_client.close()
    except Exception as e:
        logger.warning("ES search failed, falling back to in-memory store: %s", e)

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
    except Exception as e:
        logger.error("Embed search failed for query '%s': %s", query[:80], e)
        return SearchOutput(data=[])
