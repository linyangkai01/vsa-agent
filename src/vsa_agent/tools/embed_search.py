"""Embed search tool — semantic vector search for video content.

Generates embeddings from text queries and searches an in-memory
vector store for matching video segments.

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import logging

from vsa_agent.registry import register_tool
from vsa_agent.tools.query_builders import SearchOutput

logger = logging.getLogger(__name__)


# ===== Registered Tool =====


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
