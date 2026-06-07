from vsa_agent.model_adapter.base import BaseModelAdapter


def create_model_adapter(model_name: str | None = None) -> BaseModelAdapter:
    '''Factory: returns OpenAIModelAdapter (dev) or VLLMModelAdapter (prod).

    Design Pattern: Strategy pattern (#13). Import only inside the function
    to avoid triggering ChatOpenAI initialization at module level.
    '''
    from vsa_agent.config import get_config
    config = get_config()

    if config.model.mode == 'dev':
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter
        return OpenAIModelAdapter(model_name=model_name)
    elif config.model.mode == 'prod':
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter
        return VLLMModelAdapter(model_name=model_name)
    else:
        raise ValueError(f'Unknown model mode: {config.model.mode}')
