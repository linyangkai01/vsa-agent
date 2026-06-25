import httpx
from langchain_openai import ChatOpenAI

from vsa_agent.config import get_config
from vsa_agent.model_adapter.base import BaseModelAdapter


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
        self.llm = ChatOpenAI(
            model=model_name or dev.llm_model,
            base_url=base_url or dev.base_url,
            api_key=resolved_api_key if resolved_api_key else None,
            temperature=0,
            max_retries=0,
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )

    async def invoke(self, messages):
        return await self._invoke_with_retry(
            lambda: self.llm.ainvoke(messages)
        )

    async def astream(self, messages):
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    def bind_tools(self, tools: list[dict]) -> None:
        """Bind tool definitions so the LLM can call them."""
        self.llm = self.llm.bind_tools(tools)
