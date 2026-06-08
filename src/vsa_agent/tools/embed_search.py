"""Embed search tool — semantic vector search for video content.

Generates embeddings from text queries and searches an in-memory
vector store for matching video segments.

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import logging

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput

logger = logging.getLogger(__name__)


# ===== Registered Tool =====


from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# ===== Data Models =====


class EmbedSearchResultItem(BaseModel):
    """A single embed search result. Mirrors NVIDIA EmbedSearchResultItem."""

    video_name: str = Field(default="", description="Video filename")
    description: str = Field(default="", description="Video/sensor description")
    start_time: str = Field(default="", description="Start time (ISO format)")
    end_time: str = Field(default="", description="End time (ISO format)")
    sensor_id: str = Field(default="", description="Sensor/stream UUID")
    screenshot_url: str = Field(default="", description="Screenshot URL")
    similarity_score: float = Field(default=0.0, description="Cosine similarity score")


class EmbedSearchOutput(BaseModel):
    """Output of embed search. Mirrors NVIDIA EmbedSearchOutput."""

    query_embedding: list[float] = Field(default_factory=list)
    results: list[EmbedSearchResultItem] = Field(default_factory=list)


class QueryInput(BaseModel):
    """Query input model. Mirrors NVIDIA QueryInput."""

    id: str = Field(default="", description="Query ID")
    params: dict[str, str] = Field(default_factory=dict, description="Query parameters")
    prompts: dict[str, str] = Field(default_factory=dict, description="Query prompts")
    response: str = Field(default="", description="Query response")
    embeddings: list[dict] = Field(default_factory=list, description="Query embeddings")
    source_type: str = Field(default="video_file", description="video_file or rtsp")
    exclude_videos: list[dict[str, str]] = Field(default_factory=list, description="Videos to exclude")


# ===== Embedding Generation =====


async def _generate_query_embedding(query_input: QueryInput, embed_client=None) -> list[float]:
    """Generate query embedding from text. Mock implementation.

    NVIDIA original calls CosmosEmbedClient for real embeddings.
    Returns a deterministic mock vector for now.
    """
    query_text = query_input.params.get("query", "")
    if not query_text:
        return []
    # Deterministic mock: hash-based vector for testing
    seed = sum(ord(c) for c in query_text) % 1000
    return [seed * 0.001, seed * 0.002, seed * 0.003, (seed % 100) * 0.01]


# ===== Result Processing =====


async def _process_search_hit(
    hit: dict,
    min_cosine_similarity: float = 0.0,
    exclude_videos: list[dict[str, str]] | None = None,
) -> EmbedSearchResultItem | None:
    """Process a single search hit into EmbedSearchResultItem. Mock implementation.

    NVIDIA original processes Elasticsearch hits with nested KNN results,
    UUID extraction, screenshot URL building, and ES score conversion.
    """
    if exclude_videos is None:
        exclude_videos = []

    score = hit.get("_score", 0.0)
    # Convert ES normalized score to cosine: 2 * score - 1
    similarity = round(2 * score - 1, 2)
    if similarity < min_cosine_similarity:
        return None

    source = hit.get("_source", {})
    sensor = source.get("sensor", {})
    sensor_id = sensor.get("id", "")

    return EmbedSearchResultItem(
        video_name=sensor_id or "unknown",
        description=sensor.get("description", ""),
        start_time=source.get("timestamp", ""),
        end_time=source.get("end", ""),
        sensor_id=sensor_id,
        screenshot_url="",
        similarity_score=similarity,
    )


@register_tool(
    "embed_search",
    description="Semantic vector search: find video segments by text description "
                "using embedding similarity. Returns ranked SearchOutput.",
)
async def embed_search_tool(
    query: str,
    store=None,
    top_k: int = 10,
) -> SearchOutput:
    """Search for videos matching a natural language description.

    Args:
        query: Natural language search description.
        store: Optional vector store for dependency injection (testing).
               If None, uses a default in-memory store.
        top_k: Maximum number of results to return.

    Returns:
        SearchOutput with ranked matches.
    """
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

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
