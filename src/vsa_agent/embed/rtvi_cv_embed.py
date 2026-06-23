"""RTVI CV embedding client using an OpenAI-compatible embeddings API."""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Sequence

import httpx

from vsa_agent.embed.embed import EmbedClient

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None

logger = logging.getLogger(__name__)


class RTVICVEmbedClient(EmbedClient):
    """Embedding client backed by an OpenAI-compatible embeddings API."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        api_key: str | None = None,
        dimension: int = 1536,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._dimension = dimension
        self._client = None
        self._http_client: httpx.AsyncClient | None = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def _resolve_runtime_settings(self) -> tuple[str | None, str | None]:
        if self._base_url is not None or self._api_key is not None:
            return self._base_url, self._api_key

        from vsa_agent.config import get_config

        cfg = get_config().model
        runtime = cfg.dev if cfg.mode == "dev" else cfg.prod
        return runtime.base_url, runtime.api_key

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return

        if AsyncOpenAI is None:
            logger.warning("openai package is not installed, using mock embeddings")
            return

        base_url, api_key = self._resolve_runtime_settings()
        self._http_client = httpx.AsyncClient(trust_env=False)
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "",
            http_client=self._http_client,
        )

    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        items = list(inputs)
        if not items:
            return []

        await self._ensure_client()
        if self._client is None:
            return [self._mock_embedding(item) for item in items]

        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=items,
            )
            embeddings = [[float(value) for value in item.embedding] for item in response.data]
            if embeddings:
                self._dimension = len(embeddings[0])
            return embeddings
        except Exception as exc:
            logger.warning("RTVI CV embedding request failed, using mock embeddings: %s", exc)
            return [self._mock_embedding(item) for item in items]

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed([query])
        return results[0] if results else self._mock_embedding(query)

    def _mock_embedding(self, text: str) -> list[float]:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)
        vector = [math.sin(seed + offset) for offset in range(self._dimension)]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
