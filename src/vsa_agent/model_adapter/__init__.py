from vsa_agent.config import resolve_runtime_config
from vsa_agent.model_adapter.base import BaseModelAdapter


def create_model_adapter(
    model_name: str | None = None,
    *,
    role: str | None = None,
) -> BaseModelAdapter:
    """Create a model adapter from unified runtime config.

    `role` lets callers choose role-specific bindings such as llm or vlm. When
    omitted, the default runtime LLM binding is used.
    """
    role = role or "llm"
    if role:
        runtime = resolve_runtime_config()
        role_config = getattr(runtime, role)
        if role_config is None:
            raise ValueError(f"Runtime profile has no '{role}' role configured.")
        resolved_model = model_name or role_config.model
        if role_config.provider == "openai_compatible":
            from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

            return OpenAIModelAdapter(
                model_name=resolved_model,
                base_url=role_config.base_url,
                api_key=role_config.api_key,
            )
        if role_config.provider == "vllm":
            from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

            return VLLMModelAdapter(
                model_name=resolved_model,
                base_url=role_config.base_url,
                api_key=role_config.api_key,
            )
        raise ValueError(f"Unknown model provider for role '{role}': {role_config.provider}")
