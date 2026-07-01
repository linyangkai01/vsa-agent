# recorded-video-business-flow

## Purpose

Define the open recorded-video business-flow baseline for `vsa-agent`.
This capability preserves the useful NVIDIA VSS recorded-video behaviors
without requiring NVIDIA runtime services.

## Requirements

### Requirement: Shared recorded-video validation

The system SHALL run a configured local video through shared-mode video understanding, QA output, report output, artifact writing, and run validation without requiring NVIDIA runtime services.

#### Scenario: Shared mode succeeds

- GIVEN `config.yaml` resolves an active profile and video path
- WHEN the user runs `bash scripts/run_live_top_agent_video_dashscope.sh`
- THEN the run writes `manifest.json`, `trace.jsonl`, `qa-final.txt`, and `report-final.txt`
- AND `conda run -n vsa-agent python -m vsa_agent validate-run <run_dir>` returns PASS

### Requirement: Graph recorded-video validation

The system SHALL run graph mode with TopAgent tool-call evidence while avoiding duplicate long-video VLM understanding for QA and report phases.

#### Scenario: Graph mode succeeds without repeated LVS

- GIVEN `VSA_LIVE_VIDEO_MODE=graph`
- WHEN the user runs `bash scripts/run_live_top_agent_video_dashscope.sh`
- THEN the trace includes `top_agent.agent.request`, `top_agent.agent.response`, `top_agent.tool.call`, `top_agent.tool.result`, and `top_agent.final`
- AND validator summary includes model call counts and token counts
- AND validator does not emit a repeated long-video understanding warning

### Requirement: Local archive search validation

The system SHALL validate a local archive search flow without Elasticsearch, NVIDIA Cosmos, or RTVI services.

#### Scenario: Local archive search returns deterministic result

- GIVEN a deterministic local archive fixture with at least one video metadata record
- WHEN `search_agent` receives a matching natural-language query
- THEN it returns a `SearchOutput` with at least one `SearchResult`
- AND the result contains video name, description, timestamps, sensor id, similarity, and object ids
