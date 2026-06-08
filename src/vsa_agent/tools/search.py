"""Core search orchestrator — three-path routing for video search.

Combines embed_search and attribute_search through the three-path
routing strategy from search_agent.py.

Design Pattern: #13 Three-Path Search Strategy.
"""

import logging

from vsa_agent.registry import register_tool
from vsa_agent.agents.search_agent import SearchOutput
from vsa_agent.agents.search_agent import SearchResult

logger = logging.getLogger(__name__)


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
    - Path 3: fusion (has_action=True + attributes → embed + rerank)

    Args:
        query: Natural language search query.
        embed_store: Optional embed store for dependency injection.
        attr_store: Optional attribute store for dependency injection.
        decomposed_attributes: Pre-extracted attributes (from query decomposition).
        decomposed_has_action: Pre-extracted action flag.
        top_k: Maximum results to return.

    Returns:
        SearchOutput with ranked results.
    """
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

    # Resolve stores lazily
    if embed_store is None:
        from vsa_agent.tools.vector_store import get_default_embed_store
        embed_store = get_default_embed_store()

    if attr_store is None:
        from vsa_agent.tools.vector_store import get_default_attr_store
        attr_store = get_default_attr_store()

    attributes = decomposed_attributes or []
    has_action = decomposed_has_action

    # Path 1: Attribute-only (no action, attributes present)
    if has_action is False and attributes:
        logger.info("Path 1: attribute-only search")
        try:
            return await attr_store.search_by_attributes(
                attributes=attributes,
                top_k=top_k,
            )
        except Exception as e:
            logger.error("Attribute-only search failed: %s", e)
            return SearchOutput(data=[])

    # Path 2: Embed-only (no attributes)
    if not attributes:
        logger.info("Path 2: embed-only search")
        try:
            return await embed_store.search(query=query, top_k=top_k)
        except Exception as e:
            logger.error("Embed-only search failed: %s", e)
            return SearchOutput(data=[])

    # Path 3: Fusion (has_action=True + attributes present)
    logger.info("Path 3: fusion search (embed + attribute rerank)")
    embed_results: list[SearchResult] = []
    attr_results: list[SearchResult] = []

    try:
        embed_output = await embed_store.search(query=query, top_k=top_k)
        embed_results = list(embed_output.data) if hasattr(embed_output, "data") else []
    except Exception as e:
        logger.error("Embed search in fusion failed: %s", e)

    try:
        attr_output = await attr_store.search_by_attributes(
            attributes=attributes,
            top_k=top_k,
        )
        attr_results = list(attr_output.data) if hasattr(attr_output, "data") else []
    except Exception as e:
        logger.error("Attribute search in fusion failed: %s", e)

    # Merge: deduplicate by video_name, keeping best similarity
    merged: dict[str, SearchResult] = {}
    for r in embed_results + attr_results:
        if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
            merged[r.video_name] = r

    combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
    return SearchOutput(data=combined[:top_k])
