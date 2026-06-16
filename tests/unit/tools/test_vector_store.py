"""Tests for tools/vector_store.py."""
from vsa_agent.tools.vector_store import InMemoryVectorStore, get_default_embed_store, get_default_attr_store

class TestInMemoryVectorStore:
    async def test_search_returns_empty(self):
        store = InMemoryVectorStore()
        result = await store.search(query="test", top_k=10)
        assert result.data == []

    async def test_search_by_attributes_returns_empty(self):
        store = InMemoryVectorStore()
        result = await store.search_by_attributes(attributes=["person"], top_k=5)
        assert result.data == []

class TestDefaultStores:
    def test_get_default_embed_store(self):
        assert isinstance(get_default_embed_store(), InMemoryVectorStore)
    def test_get_default_attr_store(self):
        assert isinstance(get_default_attr_store(), InMemoryVectorStore)
