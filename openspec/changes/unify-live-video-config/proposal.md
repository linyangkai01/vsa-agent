## Why

The overall project goal is to build a self-owned `vsa-agent` that keeps the useful
business flow from NVIDIA's `video-search-and-summarization` blueprint while removing
NVIDIA runtime/service dependencies. The replacement stack should be open,
configurable, model-provider-neutral, and auditable.

The project reached the live-video validation stage, but runtime configuration was split across multiple YAML and shell environment files. This made model switching, DashScope testing, local secret handling, and Ubuntu replay harder than the business flow itself.

This change consolidates development and live-video validation around one committed `config.yaml`, one ignored local secret override, and replayable run artifacts.

## What Changes

- Consolidate runtime settings into `config.yaml`, including backend definitions, named profiles, model role bindings, runner defaults, tool registration, prompts, and video-understanding settings.
- Add `config.local.yaml` as the ignored machine-local override for API keys and other sensitive values.
- Remove redundant committed and local DashScope config files such as `config_live_dashscope.yaml`, `config_test.yaml`, and `.env.dashscope.video*`.
- Make DashScope live acceptance scripts read resolved runtime config instead of duplicating model names and keys in shell files.
- Preserve support for mixed providers through profile role bindings, for example remote DashScope LLM plus local vLLM/VLM.
- Keep live-video output inspectable through `manifest.json`, `trace.jsonl`, `qa-final.txt`, `report-final.txt`, `report.md`, `frames/`, and `tool-results/`.
- Document the current implementation truth: the stable live-video runner uses one shared video-understanding pass and then produces QA/report outputs; a fully autonomous TopAgent graph acceptance remains a follow-up task.
- Align the remaining Comet work with the de-NVIDIA objective: real-video runs must prove that the open replacement business flow is working, not just that isolated unit tests pass.

## Capabilities

### New Capabilities

- `live-video-runtime-config`: Defines the unified config-driven runtime, local secret override, DashScope runner behavior, live-video artifact contract, and remaining acceptance boundaries.

### Modified Capabilities

- None. There are no archived OpenSpec specs yet in this repository; this change creates the first repo-local capability contract for the current live-video validation work.

## Impact

- Affected configuration: `config.yaml`, `config.local.yaml` handling, `.gitignore`, `.gitattributes`.
- Affected runners: `scripts/run_live_acceptance_dashscope.sh`, `scripts/run_live_top_agent_video_dashscope.sh`, `src/vsa_agent/live_video_acceptance.py`.
- Affected runtime code: `src/vsa_agent/config.py`, model adapter creation, live trace helpers, video-understanding/report-agent trace integration.
- Affected docs/tests: live API validation docs, config docs, unit tests for config resolution, runner behavior, trace output, and line-ending safety.
- Affected project direction: future work should be evaluated against parity with the original NVIDIA-style business flow and the ability to run without NVIDIA-specific services.
