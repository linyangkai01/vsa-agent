# Live API Validation

This document explains how to run the evaluator regression entry and the opt-in live API validation entry.

## Purpose

- `tests/acceptance/test_evaluator_regression.py`
  Runs stable offline evaluator regression from fixtures.
- `tests/acceptance/test_evaluator_live_api.py`
  Runs opt-in live model validation for summary generation and search query decomposition.

## Required Environment

Live API validation can run in two ways:

- Default OpenAI path: set `OPENAI_API_KEY`
- Provider override path: set `LIVE_API_KEY`, and optionally `LIVE_API_BASE_URL` and `LIVE_API_MODEL`

Optional:

- `VSA_CONFIG`
  Override config path if you want to point at a non-default test config.

## Commands

Offline regression only:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py -q
```

Live API validation only:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
$env:OPENAI_API_KEY='sk-...'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py -q
```

DashScope-compatible live API validation:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
$env:LIVE_API_KEY='your-dashscope-key'
$env:LIVE_API_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:LIVE_API_MODEL='qwen-plus'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py -q
```

Ubuntu DashScope one-command runner:

```bash
export DASHSCOPE_API_KEY="your-dashscope-key"
# Optional model overrides:
export DASHSCOPE_LLM_MODEL="qwen-plus"
export DASHSCOPE_VLM_MODEL="qwen3-vl-plus"
bash scripts/run_live_acceptance_dashscope.sh
```

The runner uses `config_live_dashscope.yaml`, maps `DASHSCOPE_API_KEY` into `LIVE_API_KEY`,
maps `DASHSCOPE_LLM_MODEL` into `LIVE_API_MODEL`, and runs
`tests/acceptance/test_evaluator_live_api.py`. Only `DASHSCOPE_API_KEY` is required; the LLM
and VLM model variables have script defaults.

Combined acceptance validation:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py tests/acceptance/test_evaluator_live_api.py -q
```

## Expected Results

- Without `LIVE_API_KEY` or `OPENAI_API_KEY`, live API tests should `skip` rather than fail.
- With `OPENAI_API_KEY`, live API tests should execute real model calls against the default OpenAI path.
- With `LIVE_API_KEY`, live API tests should prefer the `LIVE_API_*` provider override values.
- Offline regression should remain stable regardless of live API availability.

## What Live API Tests Validate

Summary path:

- real model-generated summary text
- evaluator score against expected summary terms

Search path:

- real `decompose_query()` participation through `search_agent`
- returned `text_answer`
- `decomposed_query`
- `decomposed_attributes`
- `decomposed_has_action`
- evaluator score for the controlled search hit

## Diagnosing Failures

The live search acceptance test emits diagnostics in assertion failures. Look for:

- `text_answer`
- `decomposed_query`
- `decomposed_attributes`
- `decomposed_has_action`
- `eval_score`

If the live test fails, compare those fields against the intended query semantics before changing thresholds or fixtures.
