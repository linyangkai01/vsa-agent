import httpx
from langchain_openai import ChatOpenAI

from vsa_agent.config import get_config
from vsa_agent.model_adapter.base import BaseModelAdapter
from vsa_agent.observability.live_trace import write_live_trace_event


class OpenAIModelAdapter(BaseModelAdapter):
    """Adapter using OpenAI API (dev mode)."""

    def __init__(
        self,
        model_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        config = get_config()
        dev = config.model.dev
        resolved_api_key = api_key if api_key is not None else dev.api_key
        self.model_name = model_name or dev.llm_model
        self.base_url = base_url or dev.base_url
        self.llm = ChatOpenAI(
            model=self.model_name,
            base_url=self.base_url,
            api_key=resolved_api_key if resolved_api_key else None,
            temperature=0,
            max_retries=0,
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )

    async def invoke(self, messages):
        write_live_trace_event(
            "model.invoke.request",
            {"adapter": "openai", "model": self.model_name, "base_url": self.base_url, "messages": messages},
        )
        try:
            response = await self._invoke_with_retry(lambda: self.llm.ainvoke(messages))
        except Exception as exc:
            write_live_trace_event(
                "model.invoke.error",
                {"adapter": "openai", "model": self.model_name, "error": str(exc)},
            )
            raise
        write_live_trace_event(
            "model.invoke.response",
            {"adapter": "openai", "model": self.model_name, "response": response},
        )
        return response

    async def astream(self, messages):
        write_live_trace_event(
            "model.astream.request",
            {"adapter": "openai", "model": self.model_name, "base_url": self.base_url, "messages": messages},
        )
        try:
            async for chunk in self.llm.astream(messages):
                if chunk.content:
                    write_live_trace_event(
                        "model.astream.chunk",
                        {"adapter": "openai", "model": self.model_name, "content": chunk.content},
                    )
                    yield chunk.content
        except Exception as exc:
            write_live_trace_event(
                "model.astream.error",
                {"adapter": "openai", "model": self.model_name, "error": str(exc)},
            )
            raise
        write_live_trace_event(
            "model.astream.done",
            {"adapter": "openai", "model": self.model_name},
        )

    def bind_tools(self, tools: list[dict]) -> None:
        """Bind tool definitions so the LLM can call them."""
        self.llm = self.llm.bind_tools(tools)
