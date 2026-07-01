# live-video-runtime-config

## Purpose

Define the unified runtime configuration baseline for live-video development
and validation. The goal is to keep committed configuration simple while
supporting local secrets, mixed model providers, DashScope live runs, and
inspectable run artifacts.

## Requirements

### Requirement: De-NVIDIA project direction is explicit

The system documentation SHALL state that `vsa-agent` is an owned replacement for the useful business flow of NVIDIA's video-search-and-summarization blueprint, without NVIDIA runtime/service lock-in.

#### Scenario: Developer reviews project purpose

- WHEN a developer reads the project overview or current status documentation
- THEN it explains that the project replaces NVIDIA-specific dependencies with open, configurable components while preserving video search, video understanding, safety QA, report generation, and observability goals

### Requirement: Unified committed runtime configuration

The system SHALL use `config.yaml` as the single committed business/runtime configuration for development and live-video validation.

#### Scenario: Default config resolves DashScope profile

- WHEN the user runs config resolution with the default active profile
- THEN the system resolves a DashScope LLM role and a DashScope VLM role from `config.yaml`

#### Scenario: Test profile is config-driven

- WHEN the user sets `VSA_PROFILE=test`
- THEN the system resolves the test profile from `config.yaml` without requiring a separate `config_test.yaml`

### Requirement: Local secrets stay out of git

The system SHALL load optional local sensitive overrides from ignored `config.local.yaml` or from environment variables.

#### Scenario: Local API key override

- WHEN `config.local.yaml` contains a DashScope backend API key
- THEN runtime resolution uses that key without writing it into committed config or redacted config output

#### Scenario: Disable local override

- WHEN `VSA_LOCAL_CONFIG` is set to an empty string
- THEN runtime config loading skips `config.local.yaml`

### Requirement: Mixed provider role binding

The system SHALL allow each runtime profile role to bind to a different backend.

#### Scenario: Remote LLM and local VLM

- WHEN a profile binds `llm` to the DashScope backend and `vlm` to the local vLLM backend
- THEN model adapter creation uses the role-specific provider, base URL, model name, and API key policy

### Requirement: DashScope runners are config-driven

DashScope shell runners SHALL read model names, endpoint values, profile selection, and key sources from resolved runtime config instead of provider-specific committed YAML or env files.

#### Scenario: Missing API key fails early

- WHEN no DashScope key is available from the environment or `config.local.yaml`
- THEN the runner exits before live model calls and reports that `DASHSCOPE_API_KEY` or `config.local.yaml` is required

#### Scenario: Line endings are Ubuntu-safe

- WHEN shell scripts are copied to Ubuntu
- THEN `.gitattributes` preserves LF line endings for `.sh`, `.yaml`, `.yml`, `.md`, `.py`, and `.env*` files

### Requirement: Live-video artifacts are inspectable

The live-video runner SHALL write a per-run output directory containing non-secret metadata, replay logs, final text outputs, and intermediate artifacts.

#### Scenario: Successful live-video run

- WHEN the live-video runner completes successfully
- THEN it writes `manifest.json`, `trace.jsonl`, `qa-final.txt`, `report-final.txt`, optional `report.md`, `frames/`, and `tool-results/`

#### Scenario: Long-video understanding is triggered

- WHEN the input video exceeds the configured long-video threshold
- THEN trace events and manifest metadata expose chunk count and chunk-processing results for inspection

### Requirement: Current acceptance boundary is explicit

The documentation SHALL distinguish the current shared video-understanding acceptance flow from future full autonomous TopAgent graph acceptance.

#### Scenario: User reviews current progress

- WHEN the user reads project progress documentation
- THEN it states that the current one-command live-video runner validates shared long-video VLM understanding plus QA/report output, not full TopAgent graph tool selection

### Requirement: Live run validation supports replacement confidence

The project SHALL define the next live-run validation step as automatically checking whether a run directory satisfies the intended replacement business flow.

#### Scenario: Validator is planned as next development task

- WHEN the user reviews the active Comet task list
- THEN the next incomplete implementation task is a run-directory validator that checks manifest status, trace events, model/profile selection, output files, and business-flow evidence
