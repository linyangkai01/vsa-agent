import os
import shutil
import subprocess
from pathlib import Path

import pytest

from vsa_agent.config import AppConfig


def test_dashscope_live_config_defines_non_secret_llm_and_vlm_defaults():
    config = AppConfig.from_yaml("config_live_dashscope.yaml")

    assert config.model.mode == "dev"
    assert config.model.dev.provider == "openai_compatible"
    assert config.model.dev.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model.dev.llm_model == "qwen-plus"
    assert config.model.dev.vlm_model == "qwen3-vl-plus"
    assert config.model.dev.api_key == ""
    assert Path("config.yaml").read_text(encoding="utf-8") != Path("config_live_dashscope.yaml").read_text(
        encoding="utf-8"
    )


def test_dashscope_runner_exists_and_is_executable_text():
    script = Path("scripts/run_live_acceptance_dashscope.sh")

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" in text
    assert "DASHSCOPE_LLM_MODEL" in text
    assert "DASHSCOPE_VLM_MODEL" in text
    assert "LIVE_API_MODEL" in text
    assert "tests/acceptance/test_evaluator_live_api.py" in text


def test_dashscope_runner_fails_before_pytest_without_api_key():
    if shutil.which("bash") is None:
        pytest.skip("bash is not available on this platform")

    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    result = subprocess.run(
        ["bash", "scripts/run_live_acceptance_dashscope.sh"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "DASHSCOPE_API_KEY is required" in result.stderr
    assert "pytest" not in result.stdout
