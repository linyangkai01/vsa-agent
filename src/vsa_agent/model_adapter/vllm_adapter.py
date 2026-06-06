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
            temperature=0,
        )

    async def invoke(self, messages):
        return await self.llm.ainvoke(messages)

    async def astream(self, messages):
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
