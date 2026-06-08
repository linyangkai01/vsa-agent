"""Search Agent with three-path routing strategy.

Data models (DecomposedQuery, SearchResult, SearchOutput) are defined here
to match the NVIDIA original structure where they live in tools/search.py.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# ===== Data Models =====
# SIMPLIFIED: Moved here from query_builders.py to match NVIDIA original structure.
# In the NVIDIA original, these are defined directly in tools/search.py (~1400 lines).


class DecomposedQuery(BaseModel):
    query: str = Field(default="", description="The main search description")
    video_sources: list[str] = Field(default_factory=list)
    source_type: str = Field(default="video_file")
    timestamp_start: str | None = Field(default=None)
    timestamp_end: str | None = Field(default=None)
    attributes: list[str] = Field(default_factory=list)
    has_action: bool | None = Field(default=None)
    top_k: int | None = Field(default=None)
    min_cosine_similarity: float | None = Field(default=None)


class SearchResult(BaseModel):
    video_name: str = Field(...)
    description: str = Field(...)
    start_time: str = Field(...)
    end_time: str = Field(...)
    sensor_id: str = Field(...)
    screenshot_url: str = Field(default="")
    similarity: float = Field(...)
    object_ids: list[str] = Field(default_factory=list)


class SearchOutput(BaseModel):
    data: list[SearchResult] = Field(default_factory=list)


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


# ===== Helpers =====


def _resolve_search_callable(tool_name: str, **kwargs):
    """Resolve a search tool from the registry when callable is not injected.

    SIMPLIFIED: The NVIDIA original uses NAT Builder.get_function().
    vsa-agent uses direct ToolRegistry lookup.
    """
    from vsa_agent.registry import ToolRegistry
    fn = ToolRegistry.get(tool_name)
    if fn is None:
        raise RuntimeError(
            f"Search tool '{tool_name}' is not registered. "
            "Make sure it is in config.tools.enabled_modules."
        )
    async def _callable():
        return await fn(**kwargs)
    return _callable


# ===== Query Decomposition =====


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
        content = content.replace(chr(92) + "n", chr(10))  # normalize literal \n to newline
        text = content.strip()
        if "`json" in text:
            start = text.find("`json") + 7
            end = text.find("`", start)
            text = text[start:end].strip() if end != -1 else text[start:].strip()
        elif "`" in text:
            start = text.find("`") + 3
            end = text.find("`", start)
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


# ===== Three-Path Routing =====
# SIMPLIFIED: The NVIDIA original's execute_core_search() is an async generator
# with fusion_search_rerank() (RRF/weighted linear), embed_confidence_threshold
# fallback, critic agent verification loop, and SearchConfig (20+ fields).
# vsa-agent implements the core routing logic without these advanced features.


async def execute_search(
    decomposed: DecomposedQuery,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """Execute search through the appropriate routing path.

    Path 1: attribute_only ? has_action=False and attributes are present
    Path 2: embed_only ? no attributes provided
    Path 3: fusion ? has_action=True and attributes are present
    """
    has_attributes = bool(decomposed.attributes)
    has_action = decomposed.has_action

    if embed_search is None:
        embed_search = _resolve_search_callable("embed_search", query=decomposed.query)
    if attribute_search is None and has_attributes:
        attribute_search = _resolve_search_callable("attribute_search", attributes=decomposed.attributes)

    # Path 1: Attribute-only
    if not has_action and has_attributes and attribute_search is not None:
        logger.info("Path 1: attribute-only search")
        try:
            results = await attribute_search()
            if isinstance(results, SearchOutput):
                return results
            if isinstance(results, list):
                return SearchOutput(data=results)
            return SearchOutput(data=getattr(results, "data", []))
        except Exception as e:
            logger.error("Attribute search failed: %s", e)
            return SearchOutput(data=[])

    # Path 2: Embed-only
    if not has_attributes and embed_search is not None:
        logger.info("Path 2: embed-only search")
        try:
            results = await embed_search()
            if isinstance(results, SearchOutput):
                return results
            if hasattr(results, "data"):
                return SearchOutput(data=results.data)
            return SearchOutput(data=results if isinstance(results, list) else [])
        except Exception as e:
            logger.error("Embed search failed: %s", e)
            return SearchOutput(data=[])

    # Path 3: Fusion (simple dedup-by-video_name, not RRF/weighted linear)
    if has_action and has_attributes:
        logger.info("Path 3: fusion search (embed + attribute rerank)")
        embed_results: list[SearchResult] = []
        attr_results: list[SearchResult] = []
        if embed_search is not None:
            try:
                r = await embed_search()
                embed_results = list(r.data) if hasattr(r, "data") else list(r) if isinstance(r, list) else []
            except Exception as e:
                logger.error("Embed search in fusion failed: %s", e)
        if attribute_search is not None:
            try:
                r = await attribute_search()
                if isinstance(r, SearchOutput):
                    attr_results = r.data
                elif isinstance(r, list):
                    attr_results = r
                elif hasattr(r, "data"):
                    attr_results = r.data
            except Exception as e:
                logger.error("Attribute search in fusion failed: %s", e)
        merged: dict[str, SearchResult] = {}
        for r in embed_results + attr_results:
            if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
                merged[r.video_name] = r
        combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
        return SearchOutput(data=combined)

    if embed_search is not None:
        try:
            r = await embed_search()
            return SearchOutput(data=list(r.data) if hasattr(r, "data") else [])
        except Exception as e:
            logger.error("Fallback embed search failed: %s", e)
    return SearchOutput(data=[])
