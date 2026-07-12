import os
import shutil
import subprocess
from pathlib import Path

import pytest

from vsa_agent.config import AppConfig
from vsa_agent.config import resolve_runtime_config


def _assert_key_guard_precedes_config_resolution(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    guard = 'if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then'

    assert guard in text
    assert text.index(guard) < text.index(
        'conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config doctor'
    )


def test_dashscope_runners_check_key_before_config_resolution():
    _assert_key_guard_precedes_config_resolution(
        Path("scripts/run_live_acceptance_dashscope.sh")
    )
    _assert_key_guard_precedes_config_resolution(
        Path("scripts/run_live_top_agent_video_dashscope.sh")
    )


def test_dashscope_live_config_defines_non_secret_llm_and_vlm_defaults(monkeypatch):
    monkeypatch.setenv("VSA_PROFILE", "dashscope_remote")
    config = AppConfig.from_yaml("config.yaml")

    runtime = resolve_runtime_config(config)
    assert runtime.active_profile == "dashscope_remote"
    assert runtime.llm.backend == "dashscope"
    assert runtime.vlm.backend == "dashscope"
    assert runtime.llm.model == "qwen3.7-plus"
    assert runtime.vlm.model == "qwen3-vl-flash-2025-10-15"


def test_dashscope_runner_exists_and_is_executable_text():
    script = Path("scripts/run_live_acceptance_dashscope.sh")

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" in text
    assert "LIVE_API_KEY=\"$(" in text
    assert "DASHSCOPE_LLM_MODEL" not in text
    assert "DASHSCOPE_VLM_MODEL" not in text
    assert "VSA_LIVE_TRACE_PATH" in text
    assert "artifacts/live-traces/dashscope-live-acceptance.jsonl" in text
    assert "config.yaml" in text
    assert "config_live_dashscope.yaml" not in text
    assert "VSA_PROFILE" in text
    assert "LIVE_API_MODEL" in text
    assert "config doctor" in text
    assert "config print" in text
    assert "resolve_runtime_config" in text
    assert "tests/acceptance/test_evaluator_live_api.py" in text


def test_dashscope_top_agent_video_runner_exists_and_configures_live_env():
    script = Path("scripts/run_live_top_agent_video_dashscope.sh")

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" in text
    assert "OPENAI_API_KEY=\"$(" in text
    assert "VSA_CONFIG" in text
    assert "config.yaml" in text
    assert "config_live_dashscope.yaml" not in text
    assert "VSA_PROFILE" in text
    assert "config doctor" in text
    assert "config print" in text
    assert "OPENAI_API_KEY" in text
    assert "python -m vsa_agent.live_video_acceptance" in text
    assert "VSA_LIVE_VIDEO_MODE" in text
    assert "--mode" in text
    assert b"\r\n" not in script.read_bytes()


def test_dashscope_runner_uses_lf_line_endings_for_bash():
    script = Path("scripts/run_live_acceptance_dashscope.sh")

    assert b"\r\n" not in script.read_bytes()


def test_gitattributes_keeps_shell_scripts_lf():
    attrs = Path(".gitattributes").read_text(encoding="utf-8")

    assert "*.sh text eol=lf" in attrs
    assert ".env* text eol=lf" in attrs


def test_dashscope_env_files_are_not_part_of_project_config():
    assert not Path(".env.dashscope.video.example").exists()
    assert not Path(".env.dashscope.video").exists()


def test_dashscope_live_config_owns_video_runtime_defaults():
    config = AppConfig.from_yaml("config.yaml")

    assert config.runtime.video_path == "/data/project/lyk/video/1597042367-1-192.mp4"
    assert config.runtime.trace_dir == "artifacts/live-video-runs"
    assert config.runtime.qa_query


def test_dashscope_runner_fails_before_pytest_without_api_key():
    if shutil.which("bash") is None:
        pytest.skip("bash is not available on this platform")

    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    env["VSA_LOCAL_CONFIG"] = ""
    result = subprocess.run(
        ["bash", "scripts/run_live_acceptance_dashscope.sh"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "DASHSCOPE_API_KEY" in result.stderr
    assert "config.local.yaml" in result.stderr
    assert "pytest" not in result.stdout


def test_dashscope_top_agent_video_runner_fails_without_api_key():
    if shutil.which("bash") is None:
        pytest.skip("bash is not available on this platform")

    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    env["VSA_LOCAL_CONFIG"] = ""
    result = subprocess.run(
        ["bash", "scripts/run_live_top_agent_video_dashscope.sh", "video.mp4"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "DASHSCOPE_API_KEY" in result.stderr
    assert "config.local.yaml" in result.stderr
    assert "vsa_agent.live_video_acceptance" not in result.stdout


def test_dashscope_top_agent_video_runner_does_not_manage_env_files():
    script = Path("scripts/run_live_top_agent_video_dashscope.sh")
    text = script.read_text(encoding="utf-8")

    assert ".env.dashscope.video" not in text
    assert "source .env" not in text
    assert "sed -i" not in text
    assert "carriage return" not in text.lower()
