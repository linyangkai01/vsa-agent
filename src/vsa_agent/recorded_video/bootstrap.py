"""Idempotent production Elasticsearch index bootstrap."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from elasticsearch import AsyncElasticsearch

from vsa_agent.config import AppConfig, resolve_runtime_config, validate_recorded_video_runtime
from vsa_agent.recorded_video.es_index import RecordedVideoIndex

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IndexBootstrapResult:
    alias: str
    index_name: str
    embedding_model: str
    embedding_dimensions: int
    created_alias: bool


async def bootstrap_recorded_video_index(
    config: AppConfig,
    *,
    client_factory: Callable[..., Any] = AsyncElasticsearch,
) -> IndexBootstrapResult:
    """Create or validate the exact versioned index behind the production alias."""
    diagnostics = validate_recorded_video_runtime(config)
    search = config.search
    if not config.recorded_video.enabled or not search.enabled or not search.es_endpoint.strip():
        raise ValueError("recorded-video index bootstrap dependencies are not ready")
    if not diagnostics.ok:
        messages = "; ".join(issue.message for issue in diagnostics.issues)
        raise ValueError(f"recorded-video provider configuration is invalid: {messages}")

    runtime = resolve_runtime_config(config)
    if runtime.embedding is None:
        raise ValueError("recorded-video embedding provider is not configured")

    client = client_factory(
        hosts=[search.es_endpoint],
        request_timeout=search.request_timeout_sec,
        verify_certs=search.verify_certs,
    )
    try:
        alias_response = await client.indices.exists_alias(name=search.embed_index)
        alias_existed = bool(getattr(alias_response, "body", alias_response))
        index = RecordedVideoIndex(client, alias=search.embed_index)
        index_name = await index.bootstrap(
            model=runtime.embedding.model,
            dims=search.embedding_dimensions,
        )
        result = IndexBootstrapResult(
            alias=search.embed_index,
            index_name=index_name,
            embedding_model=runtime.embedding.model,
            embedding_dimensions=search.embedding_dimensions,
            created_alias=not alias_existed,
        )
        LOGGER.info(
            "recorded_video.index.bootstrap alias=%s index=%s model=%s dims=%d created_alias=%s",
            result.alias,
            result.index_name,
            result.embedding_model,
            result.embedding_dimensions,
            result.created_alias,
        )
        return result
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            await close()


__all__ = ["IndexBootstrapResult", "bootstrap_recorded_video_index"]
