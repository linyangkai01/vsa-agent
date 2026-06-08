"""Search Agent — orchestrates search workflow via three-path routing.

Accepts SearchAgentInput, calls tools/search.decompose_query(), then
routes through embed/attribute/fusion search paths.

Matches NVIDIA original where agents/search_agent.py imports
decompose_query + execute_core_search from tools/search.py.
"""

import logging

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.tools.search import DecomposedQuery
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult
from vsa_agent.tools.search import _resolve_search_callable
from vsa_agent.tools.search import decompose_query

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


# ===== Three-Path Routing =====


async def execute_search(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """Execute search with query decomposition and three-path routing.

    Decomposes the query via LLM (tools/search.decompose_query), then routes
    through one of three paths:
    - Path 1: attribute-only (has_action=False, attributes present)
    - Path 2: embed-only (no attributes)
    - Path 3: fusion (has_action=True, attributes present)
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
