# DashScope Live Acceptance Runner Design

**Date:** 2026-06-25

## Goal

Prepare a Ubuntu 22.04 one-command entry for running the real-model live acceptance tests against Alibaba Bailian/DashScope OpenAI-compatible APIs.

The runner must let the operator configure both text LLM and vision VLM model names, provide the API key through the shell environment, and run the existing live acceptance tests without editing repository files on the target machine.

## Scope

This design covers:

1. A DashScope-specific live validation config file
2. A Ubuntu `bash + conda` runner script
3. Documentation for one-command live acceptance execution
4. Environment variable conventions for both LLM and VLM model names

This design does not cover:

- Adding a new video/VLM smoke test
- Running local vLLM inference on the RTX 4090 D
- Installing NVIDIA drivers, CUDA, or system packages
- Storing API keys in tracked files
- Replacing the project default `config.yaml`

## Terms

The user requested two model configurations: LLM and VLM.

- `LLM` means the text/chat model used by the current live acceptance tests.
- `VLM` means the vision-language model used by video understanding paths.

If a future task needs local `vLLM` server setup, that should be a separate design because it has different runtime, GPU, and dependency requirements.

## Current Context

The repository already has:

- `config.yaml` with DashScope-compatible defaults:
  - `base_url: https://dashscope.aliyuncs.com/compatible-mode/v1`
  - `llm_model: qwen-plus`
  - `vlm_model: qwen3-vl-plus`
- `OpenAIModelAdapter` with runtime `model_name`, `base_url`, and `api_key` overrides
- `tests/acceptance/test_evaluator_live_api.py` reading:
  - `LIVE_API_KEY`
  - `LIVE_API_BASE_URL`
  - `LIVE_API_MODEL`
- `docs/testing/live-api-validation.md` documenting generic provider overrides

The missing piece is an operator-friendly Ubuntu runner that wires the DashScope key and model variables into the existing live acceptance entry.

## Design

### 1. DashScope Live Config

Create `config_live_dashscope.yaml`.

It should mirror the shape of `config.yaml`, keep `model.mode: dev`, and set:

```yaml
model:
  mode: dev
  dev:
    provider: openai_compatible
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ""
    llm_model: qwen-plus
    vlm_model: qwen3-vl-plus
```

The key must remain blank because secrets belong in environment variables.

The file should include the minimal app sections needed by `get_config()` and existing acceptance tests. It should not remove existing project-level defaults from `config.yaml`.

### 2. Environment Variable Contract

The runner uses these variables:

- `DASHSCOPE_API_KEY`: required API key
- `DASHSCOPE_LLM_MODEL`: optional text model override, default `qwen-plus`
- `DASHSCOPE_VLM_MODEL`: optional vision model override, default `qwen3-vl-plus`
- `DASHSCOPE_BASE_URL`: optional provider endpoint override, default `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `VSA_CONDA_ENV`: optional conda environment override, default `vsa-agent`

The runner maps these into the current live acceptance variables:

- `LIVE_API_KEY=$DASHSCOPE_API_KEY`
- `LIVE_API_BASE_URL=$DASHSCOPE_BASE_URL`
- `LIVE_API_MODEL=$DASHSCOPE_LLM_MODEL`
- `VSA_CONFIG=config_live_dashscope.yaml`

The VLM model is not consumed by the current live acceptance tests, but it is still present in `config_live_dashscope.yaml` and exported as `DASHSCOPE_VLM_MODEL` for later VLM test entry points. This keeps LLM/VLM runtime choices visible in the same command surface.

### 3. Ubuntu Runner Script

Create `scripts/run_live_acceptance_dashscope.sh`.

The script should:

1. Resolve the repository root from its own path
2. Require `DASHSCOPE_API_KEY`
3. Default `DASHSCOPE_LLM_MODEL`, `DASHSCOPE_VLM_MODEL`, `DASHSCOPE_BASE_URL`, and `VSA_CONDA_ENV`
4. Export `VSA_CONFIG`, `LIVE_API_KEY`, `LIVE_API_BASE_URL`, and `LIVE_API_MODEL`
5. Print a concise non-secret summary:
   - config path
   - conda environment
   - base URL
   - LLM model
   - VLM model
6. Run:

```bash
conda run -n "$VSA_CONDA_ENV" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs
```

The script should fail early with a clear message if:

- `conda` is not available
- `DASHSCOPE_API_KEY` is empty
- `config_live_dashscope.yaml` is missing

### 4. Documentation

Update `docs/testing/live-api-validation.md` with a dedicated Ubuntu/DashScope section:

```bash
export DASHSCOPE_API_KEY="..."
export DASHSCOPE_LLM_MODEL="qwen-plus"
export DASHSCOPE_VLM_MODEL="qwen3-vl-plus"
bash scripts/run_live_acceptance_dashscope.sh
```

Document that only `DASHSCOPE_API_KEY` is required and the model variables are optional defaults.

## Approaches Considered

### Approach A: Script-only environment overrides

Use no new config file and have the script export only `LIVE_API_*`.

Pros:

- Fewest files

Cons:

- VLM model configuration is less visible
- Harder to reuse for future VLM acceptance tests
- The runtime config used by `get_config()` remains implicit

### Approach B: Dedicated config plus script

Create a DashScope config file and a script that maps environment variables into the live acceptance entry.

Pros:

- Keeps API key out of tracked files
- Makes both LLM and VLM model defaults explicit
- Leaves the default project config untouched
- Works well on a separate Ubuntu 22.04 RTX 4090 D machine

Cons:

- Adds one extra config file

### Approach C: Full Ubuntu environment bootstrap

Add environment creation, dependency installation, and live test execution in one script.

Pros:

- More convenient on a completely fresh machine

Cons:

- Pulls setup, dependency installation, and live validation into one riskier workflow
- Exceeds the current goal of one-command model validation

## Decision

Use Approach B.

## Testing Strategy

Automated tests should cover the script without calling the real API:

- Running the script with no `DASHSCOPE_API_KEY` should fail before invoking `pytest`
- The docs test should mention:
  - `DASHSCOPE_API_KEY`
  - `DASHSCOPE_LLM_MODEL`
  - `DASHSCOPE_VLM_MODEL`
  - `scripts/run_live_acceptance_dashscope.sh`
  - `config_live_dashscope.yaml`

Manual live validation on Ubuntu:

```bash
export DASHSCOPE_API_KEY="..."
bash scripts/run_live_acceptance_dashscope.sh
```

Expected result:

- Live acceptance tests execute real model calls through DashScope
- The command prints no secret value
- If the account/model quota is unavailable, the failure should come from the provider response rather than local configuration

## Success Criteria

- A user can configure only `DASHSCOPE_API_KEY` and run one script
- The script exposes both LLM and VLM model names
- The repository does not store secrets
- Existing local tests remain green without requiring a real API key
- The change does not alter the default `config.yaml` behavior
