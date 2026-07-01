# Project Status - 2026-06-30

## Current Stage

The unified live-video configuration change is now closed at the task level.
Comet review on 2026-06-30 reframed the next milestone around verified
replacement of the original NVIDIA VSS recorded-video business flow.

## Final Purpose

This project exists to build our own `vsa-agent` by removing the NVIDIA-specific
runtime dependencies from the original `D:\WorkPlace\video-search-and-summarization-main`
project while keeping the useful business capabilities.

The target is not just a demo. The target is an open, configurable industrial video
agent that can:

- search and analyze video evidence;
- understand short and long videos with replaceable VLM backends;
- answer safety questions from real video content;
- generate inspection/investigation reports;
- run with remote providers such as Bailian/DashScope during testing;
- later support mixed deployments such as local vLLM/VLM plus remote LLM;
- produce replayable logs and artifacts so every business-flow step can be audited.

Comet is now being introduced mid-project to organize the remaining work around this
goal. Superpowers already produced much of the implementation; Comet should now keep
new development tied to explicit specs, tasks, verification, and archive steps.

The current codebase has moved from many experiment-specific config files to a simpler runtime model:

- `config.yaml` is the single committed business/runtime config.
- `config.local.yaml` is the ignored local secret override for API keys and machine-specific values.
- `VSA_PROFILE` selects a profile such as `dashscope_remote`, `hybrid_dashscope_llm_local_vlm`, or `test`.
- DashScope live runners resolve config through `vsa_agent config doctor/print` before running.
- Shell/config/docs files are protected with LF line endings through `.gitattributes`.

## Completed Work

- Unified model/provider configuration around `backends`, `profiles`, and role bindings for `llm` and `vlm`.
- Preserved mixed-provider support, including remote DashScope LLM plus local vLLM/VLM.
- Removed redundant runtime files: `config_live_dashscope.yaml`, `config_test.yaml`, `.env.dashscope.video.example`, and `.env.dashscope.video`.
- Added ignored `config.local.yaml` loading with deep merge and `VSA_LOCAL_CONFIG` override/disable behavior.
- Added config CLI verification and redacted resolved config printing.
- Added live trace/artifact helpers with base64-safe JSONL serialization.
- Added trace instrumentation around model calls, search agent, TopAgent nodes, video understanding, long-video chunking, and report generation.
- Added manifest-level timing metrics for total runtime, video understanding, QA, report generation, graph QA/report flows, and a lightweight shared-mode model-call estimate.
- Added a real-video DashScope runner command: `bash scripts/run_live_top_agent_video_dashscope.sh`.
- Added live-video run outputs under `artifacts/live-video-runs/<run_id>/`: `manifest.json`, `trace.jsonl`, `qa-final.txt`, `report-final.txt`, optional `report.md`, `frames/`, and `tool-results/`.

## Latest Known Live-Run Result

The latest final Ubuntu close-out runs for `vss-business-flow-parity` were:

Shared mode:

`/data/project/lyk/vsa-agent/artifacts/live-video-runs/20260701-102534`

- `validate-run` returned PASS.
- `mode` was `shared`.
- `active_profile` was `dashscope_remote`.
- LLM model resolved to `qwen3.7-plus`.
- VLM model resolved to `qwen3-vl-flash-2025-10-15`.
- `qa_status` was `success`.
- `report_status` was `success`.
- `tool_error_count` was `0`.
- `lvs_completed_count` was `1`.
- `vlm_call_count` was `7`.
- `llm_call_count` was `0`.
- `model_call_count` was `7`.
- `total_tokens` was `55907`.
- `total_elapsed_sec` was `72.528`.

Graph mode:

`/data/project/lyk/vsa-agent/artifacts/live-video-runs/20260701-102652`

- `validate-run` returned PASS.
- `mode` was `graph`.
- `active_profile` was `dashscope_remote`.
- LLM model resolved to `qwen3.7-plus`.
- VLM model resolved to `qwen3-vl-flash-2025-10-15`.
- `qa_status` was `success`.
- `report_status` was `success`.
- `tool_error_count` was `0`.
- `lvs_completed_count` was `1`.
- `vlm_call_count` was `7`.
- `llm_call_count` was `4`.
- `model_call_count` was `11`.
- `total_tokens` was `86911`.
- `total_elapsed_sec` was `119.709`.
- Repeated LVS warning was absent.

The previous graph-mode Ubuntu run after graph de-duplication was:

`/data/project/lyk/vsa-agent/artifacts/live-video-runs/20260701-094810`

Trace review confirmed that graph QA was agentic: the TopAgent selected
`video_understanding`, which triggered long-video chunking into seven chunks.
The report graph flow then selected `report_agent`, and
`tool-results/report-agent-understanding.json` recorded
`"reused_from": "graph_qa_answer"`, proving that report generation reused the
QA/video-understanding result instead of rerunning VLM.

The final close-out runs above provide both stable shared-flow evidence and
autonomous graph-flow evidence for the recorded-video baseline.

The latest real Ubuntu run previously reviewed was:

`/data/project/lyk/vsa-agent/artifacts/live-video-runs/20260630-100503`

Observed result from that review:

- The run succeeded for video understanding, QA, and report.
- `config.yaml` was used as the config source.
- Active profile was `dashscope_remote`.
- LLM model resolved to `qwen3.7-plus`.
- VLM model resolved to `qwen3-vl-flash-2025-10-15`.
- Long-video understanding triggered on a roughly 201-second video.
- The video was split into 7 chunks with `chunk_duration_sec: 30` and `max_frames_per_chunk: 8`.
- The trace contained long-video and VLM events, shared QA output, direct report-agent output, and run completion.

Important boundary: that run validated shared long-video VLM understanding plus QA/report output. It did not validate a full autonomous TopAgent graph selecting tools end to end, because it used shared video understanding and direct report-agent execution for stability. The later `20260701-094810` graph run above now covers autonomous TopAgent tool selection evidence.

## Current Business Flow

Current one-command live-video validation:

1. Resolve runtime config from `config.yaml` plus optional `config.local.yaml`.
2. Validate and print redacted runtime config.
3. Load the configured video path or CLI video path.
4. Run shared `video_understanding`.
5. Trigger short-video or long-video logic depending on duration.
6. Write frame previews and VLM/understanding trace artifacts.
7. Write QA final answer from the shared understanding result.
8. Generate report through `report_agent` using the shared understanding result.
9. Write manifest, trace, final outputs, and report artifacts.

This flow is intentionally stable and avoids duplicate VLM calls. It is good for validating DashScope connectivity, model configuration, long-video chunking, artifact logging, and report generation.

## Verification Evidence

Recorded completed SDD tasks:

- Task 1 trace helpers: `python -m pytest tests/unit/test_live_trace_logging.py -q` -> 12 passed.
- Task 2 TopAgent trace events: `python -m pytest tests/unit/agents/test_top_agent_live_trace.py tests/unit/agents/test_top_agent.py -q` -> 6 passed.
- Task 3 video-understanding trace: `python -m pytest tests/unit/tools/test_video_understanding_live_trace.py tests/unit/tools/test_video_understanding.py -q` -> 40 passed.
- Task 4 report-agent trace: `python -m pytest tests/unit/agents/test_report_agent_live_trace.py tests/acceptance/test_report_flow.py -q` -> 7 passed.
- Task 5 live-video runner: `python -m pytest tests/unit/test_live_top_agent_video_runner.py tests/unit/test_live_trace_logging.py tests/unit/agents/test_top_agent_live_trace.py -q` -> 16 passed.
- Task 6 DashScope runner/docs: `python -m pytest tests/unit/test_dashscope_live_runner.py tests/unit/test_live_api_docs.py -q` -> 6 passed, 2 skipped.
- Task 7 live-video metrics close-out: `python -m pytest tests/unit/test_live_run_validator.py tests/unit/test_live_top_agent_video_runner.py tests/unit/test_dashscope_live_runner.py tests/unit/test_live_api_docs.py -q` -> 20 passed, 2 skipped.

Latest local close-out verification:

```powershell
python -m pytest tests/unit/test_live_run_validator.py tests/unit/test_live_top_agent_video_runner.py tests/unit/test_dashscope_live_runner.py tests/unit/test_live_api_docs.py -q
```

Result on 2026-07-01: 20 passed, 2 skipped.

Recommended Ubuntu live validation:

```bash
cd /data/project/lyk/vsa-agent
nano config.local.yaml
bash scripts/run_live_top_agent_video_dashscope.sh
```

Exact shared-mode validation:

```bash
cd /data/project/lyk/vsa-agent
unset VSA_LIVE_VIDEO_MODE
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

Exact graph-mode validation:

```bash
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

Validator PASS confirms required files, trace events, model/profile fields, and
flow statuses. It is not a cost or report-quality verdict; inspect
`model_call_count`, `vlm_call_count`, `total_tokens`, `lvs_completed_count`, and
warnings for runtime quality and cost risk.

## NVIDIA VSS Parity Review - 2026-06-30

The latest comparison against `D:\WorkPlace\video-search-and-summarization-main`
is recorded in:

`docs/superpowers/reviews/vsa-agent-original-vss-comprehensive-audit-2026-07-01.md`

Main conclusion:

- Current `vsa-agent` has replaced the core runtime shape with open components:
  config-driven providers, OpenAI-compatible/DashScope calls, vLLM-ready roles,
  LangGraph orchestration, local video understanding, long-video chunking,
  report generation, search-agent modules, traces, artifacts, and run validation.
- The stable live-video runner validates shared video understanding plus QA/report
  output, and graph-mode validation now proves autonomous TopAgent tool selection
  on a real Ubuntu video run.
- The next milestone should be measured by validated recorded-video business
  flows, not by raw module count.
- Report quality is explicitly deferred until shared metrics, graph acceptance,
  and validator checks are stable.

The working roadmap is:

`docs/superpowers/plans/2026-07-01-vss-business-flow-parity-next-phase.md`

## Known Gaps

- Graph mode now executes autonomous TopAgent QA and report flows. The remaining
  gap is repeated multi-video validation beyond the current single real sample.
- Post-run trace validation exists, but it should now be used as a mandatory gate after every Ubuntu live-video run.
- Runtime latency can be high for long videos because every chunk calls the VLM.
- Report quality is not yet the priority and may need a separate prompt/report-format improvement pass.
- The working tree contains many uncommitted changes and generated/untracked directories; this should be cleaned before final merge or push.

## Next Development Tasks

1. Keep shared and graph live-video acceptance as required regression gates.

   Set `VSA_LIVE_VIDEO_MODE=graph` and run `bash scripts/run_live_top_agent_video_dashscope.sh`. The trace should contain `top_agent.agent.request`, `top_agent.agent.response`, `top_agent.tool.call`, `top_agent.tool.result`, and `top_agent.final` in real runs.

2. Use the run-directory trace validator after every Ubuntu live run.

   Run `python -m vsa_agent validate-run artifacts/live-video-runs/<run_id>`. The validator reads `manifest.json` and `trace.jsonl`, then prints a pass/fail summary for required events, model names, output files, and flow statuses. This is the bridge from "it ran" to "the NVIDIA-style business flow was actually replaced and verified."

3. Add timing and cost-oriented run metrics.

   Record per-chunk duration, per-model-call duration, QA duration, report duration, total runtime, and basic token/model metadata when available.

4. Defer report quality improvements until the graph-mode and validator tasks are stable.

   Once the business flow can be automatically judged, improve report structure, safety-risk extraction, and evidence citation without mixing quality work into infrastructure debugging.

5. After current change close-out, open a separate Comet/OpenSpec change for recorded-video VSS business-flow parity.

   Recommended name: `vss-business-flow-parity`. Scope it to Q&A, long-video
   summarization, report generation, graph-mode acceptance, local archive search,
   and run validation. Keep real-time alerts, Enterprise RAG, UI, and production
   deployment out of that milestone.

## Suggested Next Step

Use the final Ubuntu shared-mode and graph-mode validation commands as
regression gates before archiving or expanding the `vss-business-flow-parity`
milestone.
