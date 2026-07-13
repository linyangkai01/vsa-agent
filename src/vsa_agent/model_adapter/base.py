from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from langchain_core.messages import BaseMessage
from openai import AuthenticationError, PermissionDeniedError

from vsa_agent.utils.retry import call_with_async_retry


class BaseModelAdapter(ABC):
    """Abstract base for LLM/VLM adapters."""

    retry_max_retries: int = 2
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    retry_exceptions: tuple[type[Exception], ...] = (Exception,)
    non_retry_exceptions: tuple[type[Exception], ...] = (AuthenticationError, PermissionDeniedError)

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

    async def _invoke_with_retry(self, func):
        """Run a single async model call through the shared retry contract."""
        return await call_with_async_retry(
            func,
            max_retries=self.retry_max_retries,
            delay=self.retry_delay,
            backoff=self.retry_backoff,
            exceptions=self.retry_exceptions,
            non_retry_exceptions=self.non_retry_exceptions,
        )
