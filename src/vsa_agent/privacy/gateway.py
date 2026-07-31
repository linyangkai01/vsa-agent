"""The sole typed boundary used by production remote-provider calls."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from vsa_agent.privacy.schemas import (
    RemoteSafeIngestEvent,
    RemoteSafeSearchQuery,
    canonical_embedding_text,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class GatewayObserver(Protocol):
    def __call__(self, operation: str, payload: Mapping[str, Any]) -> None: ...


class RemoteProviderGateway:
    """Serialize closed DTOs, emit value-free logs, then call injected transports."""

    def __init__(self, *, observer: GatewayObserver | None = None) -> None:
        self._observer = observer

    @staticmethod
    def serialize(payload: BaseModel) -> dict[str, Any]:
        if not isinstance(payload, BaseModel) or not type(payload).__name__.startswith("RemoteSafe"):
            raise TypeError("remote gateway accepts only RemoteSafe DTOs")
        serialized = payload.model_dump(mode="json")
        RemoteProviderGateway._validate_tree(serialized)
        return serialized

    async def embed_ingest(
        self,
        event: RemoteSafeIngestEvent,
        sender: Callable[[str], Awaitable[T]],
    ) -> T:
        serialized = self.serialize(event)
        self._observe("embedding.ingest", serialized)
        return await sender(canonical_embedding_text(event))

    async def embed_search(
        self,
        query: RemoteSafeSearchQuery,
        sender: Callable[[str], Awaitable[T]],
    ) -> T:
        serialized = self.serialize(query)
        self._observe("embedding.search", serialized)
        return await sender(query.query)

    async def decompose_search(self, query: RemoteSafeSearchQuery, model_adapter: Any) -> Any:
        serialized = self.serialize(query)
        self._observe("llm.search_decomposition", serialized)
        messages = [
            SystemMessage(
                content=(
                    "You are a search query analyzer. Return only JSON with query, attributes, has_action and top_k."
                )
            ),
            HumanMessage(content=f"Analyze this privacy-screened safety search query: {query.query}"),
        ]
        result = model_adapter.invoke(messages)
        return await result if inspect.isawaitable(result) else result

    async def invoke_agent(
        self,
        query: RemoteSafeSearchQuery,
        model_adapter: Any,
        *,
        system_prompt: str,
    ) -> Any:
        """Invoke the remote orchestrator with a screened query and no local history."""

        serialized = self.serialize(query)
        self._observe("llm.agent", serialized)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query.query),
        ]
        result = model_adapter.invoke(messages)
        return await result if inspect.isawaitable(result) else result

    def _observe(self, operation: str, serialized: Mapping[str, Any]) -> None:
        if self._observer is not None:
            self._observer(operation, serialized)
        keys = tuple(sorted(serialized))
        query = serialized.get("query")
        logger.info(
            "remote_gateway.request operation=%s schema=%s keys=%s query_length=%s",
            operation,
            serialized.get("policy_version", "unknown"),
            keys,
            len(query) if isinstance(query, str) else 0,
        )

    @staticmethod
    def _validate_tree(value: Any) -> None:
        if value is None or isinstance(value, str | int | float | bool):
            return
        if isinstance(value, list):
            for item in value:
                RemoteProviderGateway._validate_tree(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("remote DTO keys must be strings")
                RemoteProviderGateway._validate_tree(item)
            return
        raise TypeError(f"remote DTO contains unsupported value type: {type(value).__name__}")
