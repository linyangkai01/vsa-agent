from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class PromptsConfig(BaseModel):
    """All prompt strings consumed by agents and tools."""
    default_system: str = (
        "You are an industrial safety video analysis agent. "
        "Use tools to analyze videos and generate safety reports. "
        "Respond directly when no tools are needed."
    )
    safety_routine_inspection: str = (
        "你是工业安全巡检系统。检查视频中是否存在："
        "1. 未佩戴安全帽的人员\n"
        "2. 未穿防护服的人员\n"
        "3. 危险区域（标记为红区）的闯入行为\n"
        "对每个违规，记录：时间戳、违规类型、人员描述、位置"
    )
    safety_incident_investigation: str = (
        "你是工业安全调查系统。还原事件发生过程："
        "1. 识别事件发生前的异常行为\n"
        "2. 追踪涉事人员的行动轨迹\n"
        "3. 分析可能的触发因素\n"
        "按时间顺序描述完整事件链，标注每个阶段的关键证据"
    )
    vlm_format_instruction: str = (
        "DON'T MAKE UP ANYTHING THAT NOT FROM THE VIDEO. "
        "DON'T HALLUCINATE ANYTHING. "
        "Start and end each caption with the timestamp in pts format, "
        'for example, " <10.5> event_description <11.5> ".'
    )


class ModelDevConfig(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    vlm_model: str = "gpt-4o"


class ModelProdConfig(BaseModel):
    provider: str = "vllm"
    base_url: str = "http://localhost:8000/v1"
    llm_model: str = "Qwen3-VL-8B-Instruct"
    vlm_model: str = "Qwen3-VL-8B-Instruct"


class ModelConfig(BaseModel):
    mode: Literal["dev", "prod"] = "dev"
    dev: ModelDevConfig = ModelDevConfig()
    prod: ModelProdConfig = ModelProdConfig()


class ToolsConfig(BaseModel):
    """Which tool modules to import at startup."""
    enabled_modules: list[str] = Field(default_factory=lambda: ["vsa_agent.tools.echo_tool"])


class AgentConfig(BaseModel):
    max_iterations: int = 15
    planning_enabled: bool = True
    postprocessing_enabled: bool = True
    log_level: str = "INFO"
    max_history: int = 10


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AppConfig(BaseModel):
    model: ModelConfig = ModelConfig()
    tools: ToolsConfig = ToolsConfig()
    agent: AgentConfig = AgentConfig()
    server: ServerConfig = ServerConfig()
    prompts: PromptsConfig = PromptsConfig()

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "AppConfig":
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return cls(**data)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        import os
        config_path = os.environ.get("VSA_CONFIG", "config.yaml")
        _config = AppConfig.from_yaml(config_path)
    return _config
