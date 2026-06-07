from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class ModelDevConfig(BaseModel):
    provider: str = 'openai_compatible'
    base_url: str = 'https://api.openai.com/v1'
    llm_model: str = 'gpt-4o'
    vlm_model: str = 'gpt-4o'


class ModelProdConfig(BaseModel):
    provider: str = 'vllm'
    base_url: str = 'http://localhost:8000/v1'
    llm_model: str = 'Qwen3-VL-8B-Instruct'
    vlm_model: str = 'Qwen3-VL-8B-Instruct'


class ModelConfig(BaseModel):
    mode: Literal['dev', 'prod'] = 'dev'
    dev: ModelDevConfig = ModelDevConfig()
    prod: ModelProdConfig = ModelProdConfig()


class AgentConfig(BaseModel):
    max_iterations: int = 15
    planning_enabled: bool = True
    postprocessing_enabled: bool = True


class ServerConfig(BaseModel):
    host: str = '0.0.0.0'
    port: int = 8000


class AppConfig(BaseModel):
    model: ModelConfig = ModelConfig()
    agent: AgentConfig = AgentConfig()
    server: ServerConfig = ServerConfig()

    @classmethod
    def from_yaml(cls, path: str | Path = 'config.yaml') -> 'AppConfig':
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        import os
        config_path = os.environ.get('VSA_CONFIG', 'config.yaml')
        _config = AppConfig.from_yaml(config_path)
    return _config
