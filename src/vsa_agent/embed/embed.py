"""EmbedClient abstract base class.

Mirrors NVIDIA EmbedClient pattern for video/text embedding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence


class EmbedClient(ABC):
    """Abstract base class for embedding clients.

    Provides a unified interface for generating embeddings
    from video frames, text queries, or both.
    """

    @abstractmethod
    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for the given inputs.

        Args:
            inputs: List of text strings or serialized frame data.

        Returns:
            List of embedding vectors, one per input.
        """
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Generate an embedding for a single query string.

        Args:
            query: The search query text.

        Returns:
            A single embedding vector.
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...
