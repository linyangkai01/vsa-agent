"""Simple in-memory vector store for search tools.

Provides placeholder embed and attribute stores for development.
In production, these would be backed by Elasticsearch (see NVIDIA original).
"""

import hashlib
import logging

from vsa_agent.tools.search import SearchOutput

logger = logging.getLogger(__name__)


class InMemoryVectorStore:
    """In-memory vector store that always returns empty results.

    In production, swap this for an Elasticsearch-backed implementation.
    """

    async def search(self, query: str, top_k: int = 10) -> SearchOutput:
        """Search by text query (semantic embed search)."""
        logger.info(
            "InMemoryVectorStore.search: query_sha256=%s query_length=%d top_k=%d (empty store)",
            hashlib.sha256(query.encode()).hexdigest(),
            len(query),
            top_k,
        )
        return SearchOutput(data=[])

    async def search_by_attributes(self, attributes: list[str], top_k: int = 5) -> SearchOutput:
        """Search by visual attributes."""
        logger.info(
            "InMemoryVectorStore.search_by_attributes: attribute_count=%d top_k=%d (empty store)",
            len(attributes),
            top_k,
        )
        return SearchOutput(data=[])


_default_embed_store = InMemoryVectorStore()
_default_attr_store = InMemoryVectorStore()


def get_default_embed_store() -> InMemoryVectorStore:
    """Return the default in-memory embed store instance."""
    return _default_embed_store


def get_default_attr_store() -> InMemoryVectorStore:
    """Return the default in-memory attribute store instance."""
    return _default_attr_store


def get_default_store() -> InMemoryVectorStore:
    """Return a shared default in-memory store instance."""
    return _default_embed_store
