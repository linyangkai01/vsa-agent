"""Attribute search tool — object-level search by visual attributes.

Searches for video segments matching specific object/person descriptions
(e.g., "person with red jacket", "blue forklift").

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import logging

from vsa_agent.registry import register_tool
from vsa_agent.agents.search_agent import SearchOutput
from vsa_agent.agents.search_agent import SearchResult

logger = logging.getLogger(__name__)


# ===== Helpers =====


def _deduplicate_by_video_name(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate SearchResults by video_name, keeping the highest similarity.

    This mimics the NVIDIA original's deduplication behavior where
    multiple attribute hits on the same video are collapsed into the
    best-scoring result.
    """
    merged: dict[str, SearchResult] = {}
    for r in results:
        if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
            merged[r.video_name] = r
    return sorted(merged.values(), key=lambda x: x.similarity, reverse=True)


# ===== Registered Tool =====


@register_tool(
    "attribute_search",
    description="Attribute-based search: find video segments matching specific "
                "visual attributes (e.g., 'person in red jacket'). "
                "Returns deduplicated SearchOutput ranked by similarity.",
)
async def attribute_search_tool(
    attributes: list[str],
    store=None,
    top_k: int = 5,
) -> SearchOutput:
    """Search for video segments matching visual attribute descriptions.

    Args:
        attributes: List of attribute descriptions (e.g., ["person in red shirt"]).
        store: Optional vector store for dependency injection (testing).
               If None, uses a default in-memory store.
        top_k: Maximum results per attribute before deduplication.

    Returns:
        SearchOutput with deduplicated, ranked matches.
    """
    if not attributes:
        raise ValueError("At least one attribute is required for attribute search")

    if store is None:
        from vsa_agent.tools.vector_store import get_default_store
        store = get_default_store()

    try:
        result = await store.search_by_attributes(
            attributes=attributes,
            top_k=top_k,
        )

        if isinstance(result, SearchOutput):
            results = result.data
        elif hasattr(result, "data"):
            results = list(result.data)
        else:
            results = list(result) if isinstance(result, list) else []

        # Deduplicate by video_name (best score wins)
        deduped = _deduplicate_by_video_name(results)

        # Sort by similarity descending
        deduped.sort(key=lambda x: x.similarity, reverse=True)

        return SearchOutput(data=deduped[:top_k])
    except Exception as e:
        logger.error("Attribute search failed for attributes %s: %s", attributes, e)
        return SearchOutput(data=[])
