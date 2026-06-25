# DashScope Live Acceptance Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Ubuntu `bash + conda` entry that runs the real-model live acceptance tests through DashScope after the operator exports an API key.

**Architecture:** Keep the runtime setup explicit and local to live validation. A dedicated `config_live_dashscope.yaml` carries non-secret LLM/VLM defaults, while `scripts/run_live_acceptance_dashscope.sh` maps `DASHSCOPE_*` environment variables into the existing `LIVE_API_*` acceptance-test interface. Tests validate the runner and docs without calling the real provider.

**Tech Stack:** Python 3.12, pytest, Bash, conda, DashScope OpenAI-compatible API

## Global Constraints

- Do not add a new video/VLM smoke test.
- Do not run local vLLM inference on the RTX 4090 D.
- Do not install NVIDIA drivers, CUDA, or system packages.
- Do not store API keys in tracked files.
- Do not replace the project default `config.yaml`.

---

## File Structure

**Create**
- `config_live_dashscope.yaml`
  - DashScope-specific non-secret live validation config with both LLM and VLM model defaults.
- `scripts/run_live_acceptance_dashscope.sh`
  - Ubuntu `bash + conda` entry for live acceptance tests.
- `tests/unit/test_dashscope_live_runner.py`
  - Local tests for config presence and script early-failure behavior.

**Modify**
- `docs/testing/live-api-validation.md`
  - Add the one-command Ubuntu DashScope runner instructions.
- `tests/unit/test_live_api_docs.py`
  - Lock the new documentation surface.

### Task 1: Add DashScope live config and runner test

**Files:**
- Create: `config_live_dashscope.yaml`
- Create: `tests/unit/test_dashscope_live_runner.py`

**Interfaces:**
- Consumes: `vsa_agent.config.AppConfig.from_yaml(path)`
- Produces: a parseable `config_live_dashscope.yaml` containing:
  - `model.mode == "dev"`
  - `model.dev.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"`
  - `model.dev.llm_model == "qwen-plus"`
  - `model.dev.vlm_model == "qwen3-vl-plus"`
  - `model.dev.api_key == ""`

- [ ] **Step 1: Write the failing config test**

```python
from pathlib import Path

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
```

- [ ] **Step 2: Run the config test to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_dashscope_live_runner.py -q`
Expected: FAIL because `config_live_dashscope.yaml` does not exist

- [ ] **Step 3: Create the minimal DashScope config**

```yaml
model:
  mode: dev
  dev:
    provider: openai_compatible
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ""
    llm_model: qwen-plus
    vlm_model: qwen3-vl-plus
  prod:
    provider: vllm
    base_url: http://localhost:8000/v1
    api_key: ""
    llm_model: Qwen3-VL-8B-Instruct
    vlm_model: Qwen3-VL-8B-Instruct
agent:
  max_iterations: 15
tools:
  enabled_modules:
    - vsa_agent.tools.echo_tool
server:
  host: 0.0.0.0
  port: 8000
prompts:
  default_system: "DashScope live acceptance validation."
  safety_routine_inspection: "Check industrial safety issues."
  safety_incident_investigation: "Reconstruct the incident timeline."
  vlm_format_instruction: "Do not invent details that are not present in the input."
```

- [ ] **Step 4: Re-run the config test**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_dashscope_live_runner.py -q`
Expected: PASS

### Task 2: Add Ubuntu DashScope runner script

**Files:**
- Modify: `tests/unit/test_dashscope_live_runner.py`
- Create: `scripts/run_live_acceptance_dashscope.sh`

**Interfaces:**
- Consumes: environment variables `DASHSCOPE_API_KEY`, `DASHSCOPE_LLM_MODEL`, `DASHSCOPE_VLM_MODEL`, `DASHSCOPE_BASE_URL`, `VSA_CONDA_ENV`
- Produces: script behavior:
  - fails before pytest when `DASHSCOPE_API_KEY` is absent
  - exports `VSA_CONFIG`, `LIVE_API_KEY`, `LIVE_API_BASE_URL`, `LIVE_API_MODEL`
  - runs `conda run -n "$VSA_CONDA_ENV" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs`

- [ ] **Step 1: Write the failing script tests**

```python
import os
import subprocess
from pathlib import Path


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
```

- [ ] **Step 2: Run the script tests to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_dashscope_live_runner.py -q`
Expected: FAIL because `scripts/run_live_acceptance_dashscope.sh` does not exist

- [ ] **Step 3: Create the runner script**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${REPO_ROOT}/config_live_dashscope.yaml"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required but was not found on PATH" >&2
  exit 2
fi

if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "DASHSCOPE_API_KEY is required. Export it before running this script." >&2
  exit 2
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing config: ${CONFIG_PATH}" >&2
  exit 2
fi

export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
export DASHSCOPE_LLM_MODEL="${DASHSCOPE_LLM_MODEL:-qwen-plus}"
export DASHSCOPE_VLM_MODEL="${DASHSCOPE_VLM_MODEL:-qwen3-vl-plus}"
export VSA_CONDA_ENV="${VSA_CONDA_ENV:-vsa-agent}"

export VSA_CONFIG="${CONFIG_PATH}"
export LIVE_API_KEY="${DASHSCOPE_API_KEY}"
export LIVE_API_BASE_URL="${DASHSCOPE_BASE_URL}"
export LIVE_API_MODEL="${DASHSCOPE_LLM_MODEL}"

echo "Running DashScope live acceptance"
echo "  config: ${VSA_CONFIG}"
echo "  conda env: ${VSA_CONDA_ENV}"
echo "  base url: ${LIVE_API_BASE_URL}"
echo "  llm model: ${DASHSCOPE_LLM_MODEL}"
echo "  vlm model: ${DASHSCOPE_VLM_MODEL}"

cd "${REPO_ROOT}"
conda run -n "${VSA_CONDA_ENV}" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs
```

- [ ] **Step 4: Run the script tests**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_dashscope_live_runner.py -q`
Expected: PASS

### Task 3: Document one-command execution and run full verification

**Files:**
- Modify: `docs/testing/live-api-validation.md`
- Modify: `tests/unit/test_live_api_docs.py`

**Interfaces:**
- Consumes: `config_live_dashscope.yaml`, `scripts/run_live_acceptance_dashscope.sh`
- Produces: docs that tell the operator to run:
  - `export DASHSCOPE_API_KEY="..."`
  - `bash scripts/run_live_acceptance_dashscope.sh`

- [ ] **Step 1: Write the failing doc assertions**

```python
    assert "DASHSCOPE_API_KEY" in doc
    assert "DASHSCOPE_LLM_MODEL" in doc
    assert "DASHSCOPE_VLM_MODEL" in doc
    assert "config_live_dashscope.yaml" in doc
    assert "scripts/run_live_acceptance_dashscope.sh" in doc
```

- [ ] **Step 2: Run the doc test to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_live_api_docs.py -q`
Expected: FAIL because the docs do not yet mention the new runner

- [ ] **Step 3: Update the live API validation docs**

Add a Ubuntu DashScope section:

```markdown
Ubuntu DashScope one-command runner:

```bash
export DASHSCOPE_API_KEY="your-dashscope-key"
# Optional model overrides:
export DASHSCOPE_LLM_MODEL="qwen-plus"
export DASHSCOPE_VLM_MODEL="qwen3-vl-plus"
bash scripts/run_live_acceptance_dashscope.sh
```

The script uses `config_live_dashscope.yaml`, maps the key into `LIVE_API_KEY`, and runs `tests/acceptance/test_evaluator_live_api.py`.
```

- [ ] **Step 4: Run focused and full verification**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_dashscope_live_runner.py tests/unit/test_live_api_docs.py tests/acceptance/test_evaluator_live_api.py -q -rs`
Expected: PASS with live-call tests skipped when no key is configured

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests -q`
Expected: PASS with live-call tests skipped when no key is configured

## Self-Review

- Spec coverage: Task 1 creates the config, Task 2 creates the Ubuntu runner, Task 3 updates docs and verifies the suite.
- Placeholder scan: all paths, commands, model defaults, and environment variables are explicit.
- Type consistency: the environment variable names match the design and current live acceptance test interface.
