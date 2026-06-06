from vsa_agent.config import get_config
from vsa_agent.model_adapter.base import BaseModelAdapter
from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter
from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter


def create_model_adapter(model_name: str | None = None) -> BaseModelAdapter:
    '''Factory: returns the right adapter based on config mode.

    Design Pattern: Strategy pattern (#13). The mode (dev/prod) determines
    which implementation to use, but the caller only sees BaseModelAdapter.
    '''
    config = get_config()
    if config.model.mode == 'dev':
        return OpenAIModelAdapter(model_name=model_name)
    elif config.model.mode == 'prod':
        return VLLMModelAdapter(model_name=model_name)
    else:
        raise ValueError(f'Unknown model mode: {config.model.mode}')
