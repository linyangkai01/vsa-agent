"""Tests for embed/embed.py."""
import pytest
from vsa_agent.embed.embed import EmbedClient

class TestEmbedClient:
    def test_abstract_class_cannot_instantiate(self):
        with pytest.raises(TypeError):
            EmbedClient()

    def test_concrete_implementation(self):
        class TestClient(EmbedClient):
            async def embed(self, inputs):
                return [[0.1, 0.2]]
            async def embed_query(self, query):
                return [0.1, 0.2]
            @property
            def dimension(self):
                return 2
        client = TestClient()
        assert client.dimension == 2
