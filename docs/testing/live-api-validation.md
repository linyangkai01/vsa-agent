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
  Override config path only for unusual experiments. Normal development and tests use `config.yaml`.
- `VSA_PROFILE`
  Select the runtime profile inside `config.yaml`. The DashScope runners default to `dashscope_remote`.
- `VSA_LIVE_TRACE_PATH`
  Write opt-in JSONL replay logs for real model calls and search-tool orchestration.

## Commands

Offline regression only:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
$env:VSA_PROFILE='test'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py -q
```

During development close-out, use the `test` profile from `config.yaml` for business-flow
validation. This keeps development verification config-driven without extra `.env` files.

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
# put your key in ignored config.local.yaml, or export DASHSCOPE_API_KEY here
bash scripts/run_live_acceptance_dashscope.sh
```

During the current experiment stage, live validation uses Bailian/DashScope remote APIs by
default. The runner uses `config.yaml` as the single source of truth, checks it
with `python -m vsa_agent config doctor`, prints the redacted resolved config, maps
the resolved profile key into the live test key, and reads the LLM model/base URL from the active
`dashscope_remote` profile. Change model names in YAML, not in shell environment variables.

By default, the runner also writes replayable live trace logs to:

```bash
artifacts/live-traces/dashscope-live-acceptance.jsonl
```

Override the path when you want separate runs:

```bash
export VSA_LIVE_TRACE_PATH="artifacts/live-traces/dashscope-qwen-plus.jsonl"
bash scripts/run_live_acceptance_dashscope.sh
```

The trace is JSONL: one event per line. It records model request/response events and
search-agent events such as `search_agent.decompose_query`, `search_agent.embed_search`,
`search_agent.attribute_search`, and `search_agent.answer`. API keys and other secret-like
fields are redacted before writing.

## Real Video Validation Commands

Shared mode:

```bash
cd /data/project/lyk/vsa-agent
unset VSA_LIVE_VIDEO_MODE
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

Graph mode:

```bash
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

Validator PASS means required files, trace events, model/profile fields, and
flow statuses are present. It does not automatically mean the run was cheap or
high quality. Inspect `model_call_count`, `vlm_call_count`, `total_tokens`,
`lvs_completed_count`, and warnings.

## Real Video Acceptance

Run video QA and report-generation validation against a local video. Store the API
key in ignored `config.local.yaml` or export it in the shell:

```bash
# edit config.yaml when you want to change backend/model/video_path/QA query
# edit config.local.yaml when you want to store a local API key
bash scripts/run_live_top_agent_video_dashscope.sh
```

Before running the video flow, inspect the final resolved runtime configuration:

```bash
python -m vsa_agent config doctor --config config.yaml
python -m vsa_agent config print --config config.yaml
```

`config.yaml` is the single source of truth for video acceptance
backends, profiles, LLM/VLM model names, `runtime.video_path`, trace directory, and default
QA query. Keep secrets outside the repository by exporting them in the shell, for example
`DASHSCOPE_API_KEY`, or by storing them in ignored `config.local.yaml`. Optional
runner-only environment variables such as `VSA_CONDA_ENV` can also be exported in the
shell when needed.

With a custom QA query:

```bash
bash scripts/run_live_top_agent_video_dashscope.sh /path/to/video.mp4 \
  "Describe what happened in this video and identify any safety risks."
```

Outputs are written under `artifacts/live-video-runs/<run_id>/`, including
`manifest.json`, `trace.jsonl`, `qa-final.txt`, `report-final.txt`, optional
`report.md`, `frames/`, and `tool-results/`.

Current boundary: this runner uses one shared `video_understanding` pass and then
reuses the result for QA and `report_agent`. It validates DashScope connectivity,
LLM/VLM profile resolution, long-video chunking, artifacts, QA output, and report
generation.

To exercise the autonomous TopAgent graph path, set `VSA_LIVE_VIDEO_MODE=graph`:

```bash
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
```

Graph mode runs separate QA and report prompts through the TopAgent graph and writes
the same run directory shape. Inspect `trace.jsonl` for `top_agent.agent.request`,
`top_agent.agent.response`, `top_agent.tool.call`, `top_agent.tool.result`, and
`top_agent.final` events.

Validate a completed run directory:

```bash
python -m vsa_agent validate-run artifacts/live-video-runs/<run_id>
```

The validator reads `manifest.json` and `trace.jsonl`, checks required output files,
model/profile metadata, QA/report statuses, video-understanding evidence, and
mode-specific business-flow events. It exits `0` on pass and `1` on fail.

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

## Local Video Archive Search Smoke Test

After a live video run succeeds, ingest the latest run into the local archive:

```bash
cd /data/project/lyk/vsa-agent
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent archive ingest "$LATEST_RUN" --index artifacts/video-archive/index.jsonl
```

Search the local archive without calling a live model:

```bash
conda run -n vsa-agent python -m vsa_agent archive search "forklift safety risk" --index artifacts/video-archive/index.jsonl --top-k 5
```

This validates that real live-video artifacts can be persisted as searchable local evidence for later `search_agent` workflows.
