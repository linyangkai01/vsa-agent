"""Core search — data models, query decomposition, and three-path routing.

Matches the NVIDIA original structure where data models (DecomposedQuery,
SearchResult, SearchOutput), decompose_query(), and the core search
function all live inside tools/search.py (~1400 lines).

Design Pattern: #13 Three-Path Search Strategy.
"""

import json
import logging
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool

logger = logging.getLogger(__name__)

# ===== Data Models =====
# These match the NVIDIA original where DecomposedQuery/SearchResult/SearchOutput
# are defined directly in tools/search.py.


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


# ===== Configuration =====


class SearchConfig(BaseModel):
    """Configuration for the search tool. Mirrors NVIDIA SearchConfig fields."""

    embed_search_tool: str = Field(default="embed_search")
    attribute_search_tool: str | None = Field(default=None)
    embed_confidence_threshold: float = Field(default=0.2)
    agent_mode_llm: str | None = Field(default=None)
    use_attribute_search: bool = Field(default=False)
    default_max_results: int = Field(default=10)
    fusion_method: str = Field(default="rrf")
    w_embed: float = Field(default=0.35)
    w_attribute: float = Field(default=0.55)
    rrf_k: int = Field(default=60)
    rrf_w: float = Field(default=0.5)


class SearchInput(BaseModel):
    """Input for the search tool. Mirrors NVIDIA SearchInput fields."""

    model_config = {"extra": "forbid"}

    query: str = Field(..., description="Description of the item to search from")
    source_type: str = Field(default="video_file", description="rtsp or video_file")
    video_sources: list[str] | None = Field(default=None)
    description: str | None = Field(default=None)
    timestamp_start: str | None = Field(default=None)
    timestamp_end: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    agent_mode: bool = Field(default=True)


# ===== Core Search (async generator) =====


async def execute_core_search(
    search_input: SearchInput,
    embed_search,
    agent_llm=None,
    config: SearchConfig | None = None,
    attribute_search_fn=None,
):
    """Core search with three-path routing. Yields SearchOutput."""
    if config is None:
        config = SearchConfig()
    top_k = search_input.top_k if search_input.top_k is not None else config.default_max_results
    if search_input.agent_mode and agent_llm is not None:
        decomposed = await decompose_query(search_input.query, agent_llm)
        attributes = decomposed.attributes
        has_action = decomposed.has_action
    else:
        attributes = []
        has_action = None
    has_attributes = bool(attributes)
    if not has_action and has_attributes and attribute_search_fn is not None:
        logger.info("Path 1: attribute-only search")
        try:
            results = await attribute_search_fn()
            if isinstance(results, SearchOutput):
                yield results; return
            if isinstance(results, list):
                yield SearchOutput(data=results); return
        except Exception as e:
            logger.error("Attribute search failed: %s", e)
    if not has_attributes:
        logger.info("Path 2: embed-only search")
        try:
            results = await embed_search()
            if isinstance(results, SearchOutput):
                yield results; return
            if hasattr(results, "data"):
                yield SearchOutput(data=results.data); return
        except Exception as e:
            logger.error("Embed search failed: %s", e)
    if has_action and has_attributes:
        logger.info("Path 3: fusion search")
        embed_results = []
        attr_results = []
        try:
            r = await embed_search()
            embed_results = list(r.data) if hasattr(r, "data") else []
        except Exception as e:
            logger.error("Embed in fusion failed: %s", e)
        if attribute_search_fn is not None:
            try:
                r = await attribute_search_fn()
                if isinstance(r, SearchOutput):
                    attr_results = r.data
                elif isinstance(r, list):
                    attr_results = r
            except Exception as e:
                logger.error("Attribute in fusion failed: %s", e)
        merged = {}
        for r in embed_results + attr_results:
            if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
                merged[r.video_name] = r
        combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
        yield SearchOutput(data=combined[:top_k])
        return
    yield SearchOutput(data=[])


# ===== Constants =====

DECOMPOSITION_SYSTEM_PROMPT = (
    "You are a search query analyzer. Extract structured search parameters "
    "from natural language queries. Return ONLY valid JSON, no commentary."
)

DECOMPOSITION_USER_TEMPLATE = """Extract structured search parameters from this query.

Available fields:
- query: The main search description including actions AND attributes
- attributes: List of person/object descriptions only, not just "person"
- has_action: True if query mentions an action/event (walking, running, carrying, etc.). False if only visual attributes (what something LOOKS LIKE).
- top_k: Number of results (integer, only if explicitly mentioned like "top 5")
- video_sources: Video names mentioned (empty list if none)

Examples:
"person walking" -> {"query": "person walking", "attributes": ["person"], "has_action": true}
"red car" -> {"query": "red car", "has_action": false}
"find person in blue jacket running, top 3" -> {"query": "person in blue jacket running", "attributes": ["person in blue jacket"], "has_action": true, "top_k": 3}
"forklift in warehouse" -> {"query": "forklift in warehouse", "has_action": false}

User query: __USER_QUERY__"""


# ===== Query Decomposition =====
# Matches NVIDIA decompose_query() in tools/search.py (same function signature).


async def decompose_query(user_query: str, model_adapter) -> DecomposedQuery:
    """Decompose a natural language query into structured search parameters."""
    user_prompt = DECOMPOSITION_USER_TEMPLATE.replace("__USER_QUERY__", user_query)
    messages = [
        SystemMessage(content=DECOMPOSITION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    try:
        response = await model_adapter.invoke(messages)
        content = str(response.content) if response.content is not None else ""
        content = content.replace(chr(92) + "n", chr(10))
        text = content.strip()
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip() if end != -1 else text[start:].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip() if end != -1 else text[start:].strip()
        extracted = json.loads(text)
        return DecomposedQuery(
            query=extracted.get("query", user_query),
            video_sources=extracted.get("video_sources", []) or [],
            source_type=extracted.get("source_type", "video_file") or "video_file",
            timestamp_start=extracted.get("timestamp_start"),
            timestamp_end=extracted.get("timestamp_end"),
            attributes=extracted.get("attributes", []) or [],
            has_action=extracted.get("has_action"),
            top_k=extracted.get("top_k"),
            min_cosine_similarity=extracted.get("min_cosine_similarity"),
        )
    except Exception as e:
        logger.warning("Failed to decompose query, using raw input: %s", e)
        return DecomposedQuery(query=user_query)


# ===== Helper =====


def _resolve_search_callable(tool_name: str, **kwargs):
    """Resolve a search tool from the registry when callable is not injected."""
    from vsa_agent.registry import ToolRegistry
    fn = ToolRegistry.get(tool_name)
    if fn is None:
        raise RuntimeError(f"Search tool '{tool_name}' is not registered.")
    async def _callable():
        return await fn(**kwargs)
    return _callable


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
    """Execute video search with automatic path selection."""
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
