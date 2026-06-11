from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import BaseMessage


class BaseModelAdapter(ABC):
    """Abstract base for LLM/VLM adapters."""

    @abstractmethod
    async def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        """Send messages and return a single response."""
        ...

    @abstractmethod
    async def astream(self, messages: list[BaseMessage]) -> AsyncGenerator[str, None]:
        """Stream tokens from the model."""
        ...

    def bind_tools(self, tools: list[dict]) -> None:
        """Bind tool definitions to the model so it can call them.
        Default no-op; override in subclasses that support tool calling."""
        ...
