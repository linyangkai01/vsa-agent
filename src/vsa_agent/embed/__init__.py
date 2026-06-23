"""Embedding clients for vsa-agent."""

from vsa_agent.embed.cosmos_embed import CosmosEmbedClient
from vsa_agent.embed.embed import EmbedClient
from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

__all__ = [
    "CosmosEmbedClient",
    "EmbedClient",
    "RTVICVEmbedClient",
]
