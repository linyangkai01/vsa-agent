import httpx
from langchain_openai import ChatOpenAI

from vsa_agent.config import get_config
from vsa_agent.model_adapter.base import BaseModelAdapter


class VLLMModelAdapter(BaseModelAdapter):
    '''Adapter using local vLLM (prod mode). Same OpenAI-compatible API, different base URL.'''

    def __init__(self, model_name: str | None = None):
        config = get_config()
        prod = config.model.prod
        self.llm = ChatOpenAI(
            model=model_name or prod.llm_model,
            base_url=prod.base_url,
            api_key=prod.api_key if prod.api_key else None,
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
