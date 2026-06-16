"""Tests for config.py."""
import os
import tempfile
import pytest
import yaml
from vsa_agent.config import AppConfig, ModelConfig, PromptsConfig, get_config

class TestAppConfig:
    def test_default_construction(self):
        cfg = AppConfig()
        assert cfg.model.mode == "dev"
        assert cfg.agent.max_iterations == 15
        assert cfg.server.port == 8000

    def test_from_yaml(self):
        data = {"model": {"mode": "prod", "prod": {"llm_model": "test-model"}}, "agent": {"max_iterations": 5}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            path = f.name
        try:
            cfg = AppConfig.from_yaml(path)
            assert cfg.model.mode == "prod"
        finally:
            os.unlink(path)

class TestModelConfig:
    def test_dev_defaults(self):
        cfg = ModelConfig()
        assert cfg.dev.llm_model == "gpt-4o"

class TestPromptsConfig:
    def test_defaults_empty(self):
        p = PromptsConfig()
        assert p.default_system == ""

class TestGetConfig:
    def test_returns_appconfig(self):
        cfg = get_config()
        assert isinstance(cfg, AppConfig)

    def test_main_config_enables_phase3_report_modules(self):
        cfg = AppConfig.from_yaml("config.yaml")
        assert "vsa_agent.tools.video_report_gen" in cfg.tools.enabled_modules
        assert "vsa_agent.agents.report_agent" in cfg.tools.enabled_modules

    def test_main_config_enables_multi_report_modules(self):
        cfg = AppConfig.from_yaml("config.yaml")
        assert "vsa_agent.tools.template_report_gen" in cfg.tools.enabled_modules
        assert "vsa_agent.tools.report_gen" in cfg.tools.enabled_modules
        assert "vsa_agent.agents.multi_report_agent" in cfg.tools.enabled_modules
