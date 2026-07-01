## Context

The original reference project is `D:\WorkPlace\video-search-and-summarization-main`,
which comes from NVIDIA's video-search-and-summarization blueprint. This project is
not intended to wrap that stack. It is intended to replace the NVIDIA-dependent
runtime path with an owned Python agent stack based on LangChain/LangGraph,
OpenAI-compatible APIs, local vLLM-compatible services, and normal Python tools.

The project is now validating real video runs with Bailian/DashScope remote APIs. Earlier iterations used several config files and shell env files, which caused repeated setup drift on Ubuntu, CRLF issues in copied env files, and confusion over which LLM/VLM model was actually used.

The current implementation has already moved toward one committed `config.yaml` and an ignored `config.local.yaml`. The live-video runner no longer runs two independent autonomous TopAgent graph flows. Instead, it performs one shared video-understanding pass, reuses that result for QA, and injects it into the report agent. That is intentionally more stable and cheaper for long-video validation, but it should be documented separately from a future full TopAgent graph acceptance.

## Goals / Non-Goals

**Goals:**

- Make `config.yaml` the single committed business/runtime config for development and live validation.
- Keep secrets out of git through `config.local.yaml` and environment variables.
- Let a profile bind different providers per role, including mixed remote LLM and local vLLM/VLM.
- Make DashScope scripts config-driven and line-ending safe on Ubuntu.
- Preserve clear live-video artifacts for manual inspection and replay.
- Record the remaining development tasks honestly so the next session can continue without rediscovering the same context.
- Keep every live validation step tied to the de-NVIDIA replacement goal: video search/understanding, long-video handling, QA, report generation, and audit logs must work without NVIDIA services.

**Non-Goals:**

- Do not store API keys in committed files.
- Do not reintroduce `.env.dashscope.video` or provider-specific committed YAML files.
- Do not build UI tooling.
- Do not automate local vLLM server startup in this change.
- Do not claim the current live-video runner validates full autonomous TopAgent graph tool selection.
- Do not attempt full feature parity with the NVIDIA blueprint in this config change; parity should be advanced through later, smaller Comet changes.

## Decisions

1. Use `config.yaml` plus optional `config.local.yaml`.

   Alternative considered: keep `config_live_dashscope.yaml`, `config_test.yaml`, and `.env.dashscope.video`. That kept experiments isolated but made the project brittle and hard to copy to Ubuntu. A single committed config plus ignored local override gives one source of truth while keeping secrets local.

2. Model runtime is profile-driven, not hard-coded in shell.

   `backends` define providers and endpoint/key sources. `profiles` bind roles such as `llm` and `vlm` to backends and model names. This supports DashScope-only experiments now and mixed remote/local providers later.

3. DashScope runners resolve config before execution.

   The scripts run `python -m vsa_agent config doctor` and `config print` before live calls. This catches missing keys and model/profile mistakes before expensive live requests and prints redacted resolved config for debugging.

4. Current live-video acceptance favors stable shared understanding.

   The runner calls video understanding once, then derives QA and report outputs from the shared result. This reduces duplicate VLM calls and confirms long-video chunking, VLM integration, report generation, manifest writing, and trace/artifact capture. It does not yet prove that the reasoning model autonomously chooses TopAgent tools in a full graph.

5. Full TopAgent graph acceptance stays as a follow-up capability.

   The code already has TopAgent trace events and tests, but the one-command live-video runner currently bypasses the graph for stability. A later runner or mode should execute the graph and require `top_agent.agent.request`, `top_agent.tool.call`, `top_agent.tool.result`, and `top_agent.final` events in the live trace.

6. Run validation should become the milestone gate.

   Manual log reading was useful during development, but the project needs a repeatable way to prove that the replacement business flow actually happened. A run-directory validator should become the next Comet task so each Ubuntu live run can be judged automatically against manifest fields, trace events, model/profile selection, long-video chunking, tool calls, and output artifacts.

## Risks / Trade-offs

- Current live-video runner name includes `top_agent`, but the implementation is direct/shared-understanding based. Mitigation: document this clearly and add a follow-up task for a graph-mode runner or rename once user-facing workflow stabilizes.
- DashScope model availability and quota can differ by model name and API endpoint. Mitigation: config doctor/print exposes the resolved model names and base URLs before execution.
- Local `config.local.yaml` can hide environment mistakes. Mitigation: keep redacted config print and explicit missing-key diagnostics.
- Long-video validation can be slow and expensive. Mitigation: shared video understanding avoids duplicate VLM passes; chunk settings remain in `config.yaml`.
- Replacing the NVIDIA blueprint can drift into unrelated feature work. Mitigation: each Comet change should state which part of the original business flow it replaces or validates.

## Migration Plan

1. Keep `config.yaml` committed as the only main runtime config.
2. Keep `config.local.yaml` ignored and use it only for secrets/machine overrides.
3. Remove references to `.env.dashscope.video*`, `config_live_dashscope.yaml`, and `config_test.yaml` from current docs and tests.
4. Run unit verification for config, DashScope runners, live video runner, and trace logging.
5. On Ubuntu, run `bash scripts/run_live_top_agent_video_dashscope.sh` after setting a valid DashScope key in env or `config.local.yaml`.

## Open Questions

- Should the current script be renamed from `run_live_top_agent_video_dashscope.sh` to a less misleading name, or should it gain a `graph` mode while preserving the current command?
- Should full TopAgent graph acceptance be mandatory before the next project milestone, or treated as an optional deeper acceptance after the stable shared-understanding flow?
- Should report quality improvements be addressed next, or deferred until the full business-flow validation is trustworthy?
- Which original NVIDIA Blueprint capabilities are required for the first "owned vsa-agent" milestone, and which can be explicitly deferred?
