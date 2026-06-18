from langchain_openai import ChatOpenAI

from vsa_agent.config import get_config
from vsa_agent.model_adapter.base import BaseModelAdapter


class OpenAIModelAdapter(BaseModelAdapter):
    """Adapter using OpenAI API (dev mode)."""

    def __init__(self, model_name: str | None = None):
        config = get_config()
        dev = config.model.dev
        self.llm = ChatOpenAI(
            model=model_name or dev.llm_model,
            base_url=dev.base_url,
            api_key=dev.api_key if dev.api_key else None,
            temperature=0,
            max_retries=0,
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
