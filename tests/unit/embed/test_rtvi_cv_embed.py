"""Tests for embed/rtvi_cv_embed.py."""

import pytest


class TestRTVICVEmbedClient:
    def test_initialization(self):
        from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

        client = RTVICVEmbedClient(
            model="text-embedding-3-small",
            base_url="https://example.com/v1",
            api_key="test-key",
        )

        assert client is not None
        assert client.dimension == 1536

    @pytest.mark.asyncio
    async def test_embed_query_uses_openai_compatible_client(self, monkeypatch):
        from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

        class FakeEmbeddingsAPI:
            async def create(self, *, model, input):
                assert model == "test-embed-model"
                assert input == ["test query"]
                return type(
                    "Response",
                    (),
                    {"data": [type("Item", (), {"embedding": [0.1, 0.2, 0.3]})()]},
                )()

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.embeddings = FakeEmbeddingsAPI()

        monkeypatch.setattr("vsa_agent.embed.rtvi_cv_embed.AsyncOpenAI", FakeAsyncOpenAI)

        client = RTVICVEmbedClient(
            model="test-embed-model",
            base_url="https://example.com/v1",
            api_key="test-key",
        )

        result = await client.embed_query("test query")

        assert result == [0.1, 0.2, 0.3]
        assert client.dimension == 3

    @pytest.mark.asyncio
    async def test_embed_returns_vectors_for_multiple_inputs(self, monkeypatch):
        from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

        class FakeEmbeddingsAPI:
            async def create(self, *, model, input):
                assert input == ["alpha", "beta"]
                return type(
                    "Response",
                    (),
                    {
                        "data": [
                            type("Item", (), {"embedding": [0.1, 0.0]})(),
                            type("Item", (), {"embedding": [0.0, 0.1]})(),
                        ]
                    },
                )()

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.embeddings = FakeEmbeddingsAPI()

        monkeypatch.setattr("vsa_agent.embed.rtvi_cv_embed.AsyncOpenAI", FakeAsyncOpenAI)

        client = RTVICVEmbedClient(
            model="test-embed-model",
            base_url="https://example.com/v1",
            api_key="test-key",
        )

        result = await client.embed(["alpha", "beta"])

        assert result == [[0.1, 0.0], [0.0, 0.1]]
        assert client.dimension == 2

    @pytest.mark.asyncio
    async def test_embed_falls_back_to_mock_vectors_when_client_fails(self, monkeypatch):
        from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

        class FailingEmbeddingsAPI:
            async def create(self, *, model, input):
                raise RuntimeError("embedding backend unavailable")

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.embeddings = FailingEmbeddingsAPI()

        monkeypatch.setattr("vsa_agent.embed.rtvi_cv_embed.AsyncOpenAI", FakeAsyncOpenAI)

        client = RTVICVEmbedClient(
            model="test-embed-model",
            base_url="https://example.com/v1",
            api_key="test-key",
        )

        result = await client.embed(["alpha"])

        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) == client.dimension

    @pytest.mark.asyncio
    async def test_embed_returns_empty_for_empty_input(self):
        from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

        client = RTVICVEmbedClient(
            model="text-embedding-3-small",
            base_url="https://example.com/v1",
            api_key="test-key",
        )

        result = await client.embed([])

        assert result == []
