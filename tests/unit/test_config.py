import tempfile
from pathlib import Path
import pytest
from vsa_agent.config import AppConfig, ModelConfig


class TestModelConfig:
    def test_default_mode_is_dev(self):
        config = ModelConfig()
        assert config.mode == 'dev'

    def test_dev_config_defaults(self):
        config = ModelConfig()
        assert config.dev.llm_model == 'gpt-4o'
        assert config.dev.vlm_model == 'gpt-4o'

    def test_prod_config_defaults(self):
        config = ModelConfig()
        assert config.prod.llm_model == 'Qwen3-VL-8B-Instruct'


class TestAppConfig:
    def test_default_values(self):
        config = AppConfig()
        assert config.model.mode == 'dev'
        assert config.agent.max_iterations == 15

    def test_from_yaml(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("model:\n  mode: prod\nagent:\n  max_iterations: 20\n  planning_enabled: false\n")
            f.flush()
            config = AppConfig.from_yaml(f.name)
            Path(f.name).unlink()
        assert config.model.mode == 'prod'
        assert config.agent.max_iterations == 20
