"""Core search orchestrator with data models — three-path routing for video search.

Data models (DecomposedQuery, SearchResult, SearchOutput) live here
matching the NVIDIA original structure where they are defined in tools/search.py.

Design Pattern: #13 Three-Path Search Strategy.
"""

import logging

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool

logger = logging.getLogger(__name__)

# ===== Data Models =====
# These match the NVIDIA original where DecomposedQuery/SearchResult/SearchOutput
# are defined directly in tools/search.py (~1400 lines).


class DecomposedQuery(BaseModel):
    """Structured search parameters extracted from a natural language query."""

    query: str = Field(default="", description="The main search description")
    video_sources: list[str] = Field(default_factory=list, description="List of video source names")
    source_type: str = Field(default="video_file", description="rtsp or video_file")
    timestamp_start: str | None = Field(default=None, description="Start timestamp ISO format")
    timestamp_end: str | None = Field(default=None, description="End timestamp ISO format")
    attributes: list[str] = Field(default_factory=list, description="Person/object attributes to filter by")
    has_action: bool | None = Field(default=None, description="True if query contains an action/event/activity")
    top_k: int | None = Field(default=None, description="Number of results to return")
    min_cosine_similarity: float | None = Field(default=None, description="Minimum similarity threshold")


class SearchResult(BaseModel):
    """A single search result item matching the query."""

    video_name: str = Field(..., description="Name of the video file")
    description: str = Field(..., description="Description of the video content")
    start_time: str = Field(..., description="Start time ISO timestamp")
    end_time: str = Field(..., description="End time ISO timestamp")
    sensor_id: str = Field(..., description="Sensor identifier")
    screenshot_url: str = Field(default="", description="URL to screenshot")
    similarity: float = Field(..., description="Cosine similarity score (0.0-1.0)")
    object_ids: list[str] = Field(default_factory=list, description="Tracked object IDs")


class SearchOutput(BaseModel):
    """Container for a list of search results."""

    data: list[SearchResult] = Field(default_factory=list, description="List of search results matching the query")


# ===== Registered Tool =====


@register_tool(
    "search",
    description="Core video search with three-path routing: "
                "embed-only, attribute-only, or fusion (embed + attribute rerank). "
                "Accepts optional decomposed query parameters for path selection.",
)
async def search_tool(
    query: str,
    embed_store=None,
    attr_store=None,
    decomposed_attributes: list[str] | None = None,
    decomposed_has_action: bool | None = None,
    top_k: int = 10,
) -> SearchOutput:
    """Execute video search with automatic path selection.

    Routes through one of three paths:
    - Path 1: attribute-only (has_action=False, attributes present)
    - Path 2: embed-only (no attributes)
    - Path 3: fusion (has_action=True + attributes -> embed + rerank)
    """
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

    if embed_store is None:
        from vsa_agent.tools.vector_store import get_default_embed_store
        embed_store = get_default_embed_store()
    if attr_store is None:
        from vsa_agent.tools.vector_store import get_default_attr_store
        attr_store = get_default_attr_store()

    attributes = decomposed_attributes or []
    has_action = decomposed_has_action

    if has_action is False and attributes:
        logger.info("Path 1: attribute-only search")
        try:
            return await attr_store.search_by_attributes(attributes=attributes, top_k=top_k)
        except Exception as e:
            logger.error("Attribute-only search failed: %s", e)
            return SearchOutput(data=[])

    if not attributes:
        logger.info("Path 2: embed-only search")
        try:
            return await embed_store.search(query=query, top_k=top_k)
        except Exception as e:
            logger.error("Embed-only search failed: %s", e)
            return SearchOutput(data=[])

    logger.info("Path 3: fusion search (embed + attribute rerank)")
    embed_results: list[SearchResult] = []
    attr_results: list[SearchResult] = []

    try:
        embed_output = await embed_store.search(query=query, top_k=top_k)
        embed_results = list(embed_output.data) if hasattr(embed_output, "data") else []
    except Exception as e:
        logger.error("Embed search in fusion failed: %s", e)

    try:
        attr_output = await attr_store.search_by_attributes(attributes=attributes, top_k=top_k)
        attr_results = list(attr_output.data) if hasattr(attr_output, "data") else []
    except Exception as e:
        logger.error("Attribute search in fusion failed: %s", e)

    merged: dict[str, SearchResult] = {}
    for r in embed_results + attr_results:
        if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
            merged[r.video_name] = r

    combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
    return SearchOutput(data=combined[:top_k])
