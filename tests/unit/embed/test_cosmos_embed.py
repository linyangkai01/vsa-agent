"""Tests for embed/cosmos_embed.py."""

from vsa_agent.embed.cosmos_embed import CosmosEmbedClient


class TestCosmosEmbedClient:
    def test_initialization(self):
        client = CosmosEmbedClient(model_name="all-MiniLM-L6-v2")
        assert client is not None

    async def test_embed_query_returns_vector(self):
        client = CosmosEmbedClient(model_name="all-MiniLM-L6-v2")
        result = await client.embed_query("test query")
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_embed_returns_vectors(self):
        client = CosmosEmbedClient(model_name="all-MiniLM-L6-v2")
        result = await client.embed(["test1", "test2"])
        assert isinstance(result, list)
        assert len(result) == 2

    async def test_empty_input(self):
        client = CosmosEmbedClient(model_name="all-MiniLM-L6-v2")
        result = await client.embed([])
        assert result == []
