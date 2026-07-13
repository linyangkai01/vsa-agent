"""CosmosEmbedClient — embedding client using Cosmos / sentence-transformers.

Provides a concrete implementation of EmbedClient using
sentence-transformers for local embedding generation.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from vsa_agent.embed.embed import EmbedClient

logger = logging.getLogger(__name__)


class CosmosEmbedClient(EmbedClient):
    """Embedding client using sentence-transformers.

    Generates embeddings locally using a sentence-transformers model.
    Falls back to mock embeddings if the model is not available.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Initialize the CosmosEmbedClient.

        Args:
            model_name: Name of the sentence-transformers model to use.
        """
        self._model_name = model_name
        self._model = None
        self._dimension: int = 384  # all-MiniLM-L6-v2 default

    @property
    def dimension(self) -> int:
        return self._dimension

    async def _ensure_model(self) -> None:
        """Lazy-load the embedding model."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info("Loaded embedding model: %s (dim=%d)", self._model_name, self._dimension)
        except ImportError:
            logger.warning("sentence-transformers not installed, using mock embeddings")
        except Exception as e:
            logger.warning("Failed to load embedding model '%s': %s", self._model_name, e)

    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for the given text inputs.

        Args:
            inputs: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        await self._ensure_model()
        if self._model is None:
            return self._mock_embeddings(len(inputs))
        embeddings = self._model.encode(list(inputs), show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    async def embed_query(self, query: str) -> list[float]:
        """Generate an embedding for a single query string.

        Args:
            query: The search query text.

        Returns:
            A single embedding vector.
        """
        results = await self.embed([query])
        return results[0] if results else self._mock_embeddings(1)[0]

    def _mock_embeddings(self, count: int) -> list[list[float]]:
        """Generate mock embeddings for testing."""
        import hashlib
        import math

        embeddings = []
        for i in range(count):
            h = hashlib.md5(str(i).encode()).hexdigest()
            seed = int(h[:8], 16)
            vec = [math.sin(seed + j) for j in range(self._dimension)]
            norm = math.sqrt(sum(v * v for v in vec))
            embeddings.append([v / norm for v in vec])
        return embeddings
