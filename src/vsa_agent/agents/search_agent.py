"""Search Agent — three-path routing with query decomposition.

Orchestrates the search workflow: accepts a natural language query,
decomposes it via LLM, then routes through execute_search().

The data models (DecomposedQuery, SearchResult, SearchOutput) are
defined in tools/search.py, matching NVIDIA original structure.
This module defines SearchAgentInput — the agent-layer request model.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.tools.search import DecomposedQuery
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult

logger = logging.getLogger(__name__)

# ===== Agent Input Model =====


class SearchAgentInput(BaseModel):
    """Agent-layer input for search requests.

    Mirrors the NVIDIA SearchAgentInput pattern. This wraps the user-facing
    request parameters before query decomposition and search execution.
    """

    query: str = Field(description="Natural language search query")
    agent_mode: bool = Field(default=True, description="Enable LLM query decomposition")
    max_results: int = Field(default=5, description="Maximum number of results to return")
    top_k: int | None = Field(default=None, description="Override top_k for embed search")
    start_time: str | None = Field(default=None, description="Start time filter (ISO format)")
    end_time: str | None = Field(default=None, description="End time filter (ISO format)")


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
    """Resolve a search tool from the registry when callable is not injected."""
    from vsa_agent.registry import ToolRegistry
    fn = ToolRegistry.get(tool_name)
    if fn is None:
        raise RuntimeError(f"Search tool '{tool_name}' is not registered.")
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


# ===== Three-Path Routing =====


async def execute_search(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """Execute search with query decomposition and three-path routing.

    Decomposes the query via LLM, then routes through one of three paths.
    """
    if model_adapter is not None and search_input.agent_mode:
        decomposed = await decompose_query(search_input.query, model_adapter)
    else:
        decomposed = DecomposedQuery(query=search_input.query)

    has_attributes = bool(decomposed.attributes)
    has_action = decomposed.has_action

    if embed_search is None:
        embed_search = _resolve_search_callable("embed_search", query=decomposed.query)
    if attribute_search is None and has_attributes:
        attribute_search = _resolve_search_callable("attribute_search", attributes=decomposed.attributes)

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

    if has_action and has_attributes:
        logger.info("Path 3: fusion search")
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

    return SearchOutput(data=[])
