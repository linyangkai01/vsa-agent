"""Search Agent — three-path routing strategy for video search.

Accepts a natural language query, decomposes it via LLM into structured
parameters, then routes through one of three execution paths:

  Path 1: Attribute-only (has_action=False, attributes exist)
  Path 2: Embed-only (no attributes → pure semantic search)
  Path 3: Fusion (has_action=True, attributes exist → embed then attribute rerank)

Design Pattern: #13 Three-Path Search Strategy, #9 Domain Query Builders.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from vsa_agent.tools.query_builders import DecomposedQuery
from vsa_agent.tools.query_builders import SearchOutput
from vsa_agent.tools.query_builders import SearchResult

logger = logging.getLogger(__name__)

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
"person walking" → {{"query": "person walking", "attributes": ["person"], "has_action": true}}
"red car" → {{"query": "red car", "has_action": false}}
"find person in blue jacket running, top 3" → {{"query": "person in blue jacket running", "attributes": ["person in blue jacket"], "has_action": true, "top_k": 3}}
"forklift in warehouse" → {{"query": "forklift in warehouse", "has_action": false}}

User query: {user_query}"""


# ===== Query Decomposition =====


async def decompose_query(
    user_query: str,
    model_adapter,
) -> DecomposedQuery:
    """Decompose a natural language query into structured search parameters.

    Uses the LLM to extract attributes, action detection, and result count.

    Args:
        user_query: The natural language query from the user.
        model_adapter: Model adapter that supports .invoke(messages).

    Returns:
        DecomposedQuery with extracted structured parameters.
    """
    user_prompt = DECOMPOSITION_USER_TEMPLATE.format(user_query=user_query)

    messages = [
        SystemMessage(content=DECOMPOSITION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = await model_adapter.invoke(messages)
        content = str(response.content) if response.content is not None else ""

        # Handle markdown code-fenced JSON
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
    decomposed: DecomposedQuery,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """Execute search through the appropriate routing path.

    Routes through one of three paths based on decomposed query structure:

    Path 1: attribute_only — has_action=False and attributes are present
    Path 2: embed_only — no attributes provided
    Path 3: fusion — has_action=True and attributes are present

    Fusion combines embed results with attribute reranking for higher precision.

    Args:
        decomposed: Decomposed query with structured parameters.
        embed_search: Async callable for semantic embed search.
        attribute_search: Async callable for attribute/keyword search.

    Returns:
        SearchOutput containing the combined/ranked search results.
    """
    has_attributes = bool(decomposed.attributes)
    has_action = decomposed.has_action

    # Path 1: Attribute-only (no action, attributes present)
    if not has_action and has_attributes and attribute_search is not None:
        logger.info("Path 1: attribute-only search")
        try:
            results = await attribute_search()
            if isinstance(results, list):
                return SearchOutput(data=results)
            return SearchOutput(data=getattr(results, "data", []))
        except Exception as e:
            logger.error("Attribute search failed: %s", e)
            return SearchOutput(data=[])

    # Path 2: Embed-only (no attributes)
    if not has_attributes and embed_search is not None:
        logger.info("Path 2: embed-only search")
        try:
            results = await embed_search()
            if hasattr(results, "data"):
                return SearchOutput(data=results.data)
            return SearchOutput(data=results if isinstance(results, list) else [])
        except Exception as e:
            logger.error("Embed search failed: %s", e)
            return SearchOutput(data=[])

    # Path 3: Fusion (has_action + attributes)
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
                attr_results = list(r) if isinstance(r, list) else list(getattr(r, "data", []))
            except Exception as e:
                logger.error("Attribute search in fusion failed: %s", e)

        # Merge and deduplicate by video_name, preferring higher similarity
        merged: dict[str, SearchResult] = {}
        for r in embed_results + attr_results:
            if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
                merged[r.video_name] = r

        combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
        return SearchOutput(data=combined)

    # Fallback: embed search only
    if embed_search is not None:
        try:
            r = await embed_search()
            return SearchOutput(data=list(r.data) if hasattr(r, "data") else [])
        except Exception as e:
            logger.error("Fallback embed search failed: %s", e)

    return SearchOutput(data=[])
