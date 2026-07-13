"""Tests for config.py."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from vsa_agent.config import AppConfig, ModelConfig, PromptsConfig, get_config, reset_config_cache


class TestAppConfig:
    def test_default_construction(self):
        cfg = AppConfig()
        assert cfg.model.mode == "dev"
        assert cfg.agent.max_iterations == 15
        assert cfg.server.port == 8000
        assert cfg.recorded_video.enabled is False
        assert cfg.recorded_video.data_root == Path(".runtime/recorded-video")

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

    def test_main_config_enables_chart_modules(self):
        cfg = AppConfig.from_yaml("config.yaml")
        assert "vsa_agent.tools.chart_generator" in cfg.tools.enabled_modules
        assert "vsa_agent.tools.fov_counts_with_chart" in cfg.tools.enabled_modules

    def test_main_config_omits_legacy_model_block(self):
        cfg = AppConfig.from_yaml("config.yaml")
        raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
        assert "model" not in raw
        assert cfg.model.dev.api_key == ""

    def test_main_config_defines_test_profile(self):
        cfg = AppConfig.from_yaml("config.yaml")
        assert "test" in cfg.profiles
        assert cfg.profiles["test"].llm.model == "gpt-4o"
        assert cfg.profiles["test"].vlm.model == "gpt-4o"
        assert cfg.backends["test_openai"].api_key_required is False

    def test_gitignore_keeps_only_local_secret_config_ignored(self):
        ignore_text = Path(".gitignore").read_text(encoding="utf-8")
        lines = {line.strip() for line in ignore_text.splitlines()}

        assert "config.local.yaml" in lines
        assert "config.yaml" not in lines


class TestRuntimeConfig:
    def test_from_yaml_merges_local_secret_config_from_env_path(self, monkeypatch):
        from vsa_agent.config import resolve_runtime_config

        monkeypatch.chdir(Path.cwd())
        monkeypatch.setenv("VSA_PROFILE", "dashscope_remote")
        local_path = Path("config.local.test.yaml")
        monkeypatch.setenv("VSA_LOCAL_CONFIG", str(local_path))
        local_path.write_text(
            yaml.safe_dump({"backends": {"dashscope": {"api_key": "local-secret"}}}),
            encoding="utf-8",
        )
        try:
            cfg = AppConfig.from_yaml("config.yaml")
            runtime = resolve_runtime_config(cfg)
        finally:
            local_path.unlink(missing_ok=True)

        assert runtime.llm.api_key == "local-secret"
        assert runtime.vlm.api_key == "local-secret"
        assert runtime.model_dump_redacted()["llm"]["api_key"] == "<redacted>"

    def test_from_yaml_can_disable_local_secret_config(self, monkeypatch):
        from vsa_agent.config import resolve_runtime_config

        monkeypatch.setenv("VSA_LOCAL_CONFIG", "")
        cfg = AppConfig.from_yaml("config.yaml")
        runtime = resolve_runtime_config(cfg)

        assert runtime.llm.api_key is None

    def test_vsa_profile_env_overrides_active_profile(self, monkeypatch):
        from vsa_agent.config import resolve_runtime_config

        monkeypatch.setenv("VSA_PROFILE", "test")
        cfg = AppConfig.from_yaml("config.yaml")

        runtime = resolve_runtime_config(cfg)

        assert runtime.active_profile == "test"
        assert runtime.llm.backend == "test_openai"
        assert runtime.vlm.backend == "test_openai"

    def test_get_config_uses_single_repo_config_with_test_profile(self, monkeypatch):
        from vsa_agent.config import resolve_runtime_config

        monkeypatch.setenv("VSA_CONFIG", str(Path.cwd() / "config.yaml"))
        monkeypatch.setenv("VSA_PROFILE", "test")
        reset_config_cache()

        runtime = resolve_runtime_config(get_config())

        assert runtime.active_profile == "test"
        assert runtime.llm.model == "gpt-4o"

    def test_resolves_mixed_profile_roles_from_backends_and_env(self, monkeypatch):
        from vsa_agent.config import AppConfig, BackendConfig, ProfileConfig, RoleBindingConfig, resolve_runtime_config

        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-secret")
        monkeypatch.delenv("VSA_PROFILE", raising=False)
        cfg = AppConfig(
            active_profile="hybrid",
            backends={
                "dashscope": BackendConfig(
                    provider="openai_compatible",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key_env="DASHSCOPE_API_KEY",
                ),
                "local_vllm": BackendConfig(
                    provider="vllm",
                    base_url="http://localhost:8000/v1",
                    api_key_required=False,
                ),
            },
            profiles={
                "hybrid": ProfileConfig(
                    llm=RoleBindingConfig(backend="dashscope", model="qwen3.7-plus"),
                    vlm=RoleBindingConfig(backend="local_vllm", model="Qwen3-VL-8B-Instruct"),
                    embedding=RoleBindingConfig(backend="dashscope", model="text-embedding-v4"),
                )
            },
        )

        runtime = resolve_runtime_config(cfg)

        assert runtime.active_profile == "hybrid"
        assert runtime.llm.provider == "openai_compatible"
        assert runtime.llm.model == "qwen3.7-plus"
        assert runtime.llm.api_key == "dashscope-secret"
        assert runtime.vlm.provider == "vllm"
        assert runtime.vlm.model == "Qwen3-VL-8B-Instruct"
        assert runtime.vlm.api_key is None
        assert runtime.embedding.model == "text-embedding-v4"

    def test_runtime_config_redacts_secret_values(self, monkeypatch):
        from vsa_agent.config import AppConfig, BackendConfig, ProfileConfig, RoleBindingConfig, resolve_runtime_config

        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-secret")
        monkeypatch.delenv("VSA_PROFILE", raising=False)
        cfg = AppConfig(
            active_profile="dashscope",
            backends={
                "dashscope": BackendConfig(
                    provider="openai_compatible",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key_env="DASHSCOPE_API_KEY",
                )
            },
            profiles={
                "dashscope": ProfileConfig(
                    llm=RoleBindingConfig(backend="dashscope", model="qwen3.7-plus"),
                    vlm=RoleBindingConfig(backend="dashscope", model="qwen3-vl-flash-2025-10-15"),
                )
            },
        )

        redacted = resolve_runtime_config(cfg).model_dump_redacted()

        assert redacted["llm"]["api_key"] == "<redacted>"
        assert redacted["vlm"]["api_key"] == "<redacted>"
        assert redacted["llm"]["model"] == "qwen3.7-plus"

    def test_doctor_reports_missing_required_api_key(self, monkeypatch):
        from vsa_agent.config import AppConfig, BackendConfig, ProfileConfig, RoleBindingConfig, validate_runtime_config

        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("VSA_PROFILE", raising=False)
        cfg = AppConfig(
            active_profile="dashscope",
            backends={
                "dashscope": BackendConfig(
                    provider="openai_compatible",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key_env="DASHSCOPE_API_KEY",
                )
            },
            profiles={
                "dashscope": ProfileConfig(
                    llm=RoleBindingConfig(backend="dashscope", model="qwen3.7-plus"),
                    vlm=RoleBindingConfig(backend="dashscope", model="qwen3-vl-flash-2025-10-15"),
                )
            },
        )

        diagnostics = validate_runtime_config(cfg)

        assert diagnostics.ok is False
        assert any("DASHSCOPE_API_KEY" in issue.message for issue in diagnostics.issues)

    def test_config_print_cli_outputs_redacted_runtime_config(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-secret")
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        env["VSA_PROFILE"] = "dashscope_remote"
        result = subprocess.run(
            [sys.executable, "-m", "vsa_agent", "config", "print", "--config", "config.yaml"],
            cwd=Path.cwd(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert "dashscope-secret" not in result.stdout
        assert "active_profile" in result.stdout
        assert "llm" in result.stdout
        assert "vlm" in result.stdout

    def test_config_doctor_cli_reports_missing_key(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        config_path = tmp_path / "config.yaml"
        config_path.write_text(Path("config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "config.local.yaml").write_text(
            yaml.safe_dump({"backends": {"dashscope": {"api_key": "local-secret"}}}),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        env["VSA_PROFILE"] = "dashscope_remote"
        env.pop("DASHSCOPE_API_KEY", None)
        env["VSA_LOCAL_CONFIG"] = ""

        result = subprocess.run(
            [sys.executable, "-m", "vsa_agent", "config", "doctor", "--config", str(config_path)],
            cwd=Path.cwd(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 1
        assert "DASHSCOPE_API_KEY" in result.stdout
