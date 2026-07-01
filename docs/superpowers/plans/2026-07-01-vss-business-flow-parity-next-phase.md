# VSS Business Flow Parity Next Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current real-video `vsa-agent` prototype into a validated recorded-video VSS replacement milestone, with controlled graph-mode cost, local archive search acceptance, and repeatable run evidence.

**Architecture:** Keep `config.yaml` plus ignored `config.local.yaml` as the only runtime configuration path. Keep shared mode as the stable low-cost acceptance path and graph mode as the autonomous TopAgent evidence path. Use `manifest.json`, `trace.jsonl`, `validate-run`, and live Ubuntu runs as the acceptance gate before expanding report quality, RAG, real-time alerts, or production deployment.

**Tech Stack:** Python 3.12, LangGraph, LangChain, Pydantic v2, OpenAI-compatible DashScope/Bailian API, vLLM-ready model adapters, pytest, JSONL live traces, OpenSpec/Comet.

## Global Constraints

- Do not reintroduce provider-specific committed config files such as `config_live_dashscope.yaml`.
- Do not store API keys in git; use ignored `config.local.yaml` or environment variables.
- Do not make NVIDIA NIM, NAT/AIQ Toolkit, VST/VIOS, Cosmos, RTVI, Docker Compose, Helm, or Brev required runtime dependencies.
- Prioritize recorded-video Q&A, long-video understanding, report generation, graph-mode acceptance, local archive search, and run validation.
- Keep real-time alerts, Enterprise RAG, UI, production deployment, and full VST tool parity out of this milestone.
- Use TDD for code changes: add a failing unit or acceptance test before implementation.
- Every Ubuntu live run must be validated with `conda run -n vsa-agent python -m vsa_agent validate-run <run_dir>`.

---

## Current Gap Snapshot

Current state after the latest local work:

- `unify-live-video-config` is complete: OpenSpec reports `14/14`.
- Shared live run `20260701-082912` passed validation with `7` VLM calls, `7` chunks, and `52.192s` total runtime.
- Graph live run `20260701-083328` passed validation but exposed cost blow-up: `26` model calls, `21` VLM calls, `3` LVS completions, `211325` tokens, and `276.445s`.
- A local fix has been implemented and synced to the server to defer `report_agent` during QA and reuse QA/video understanding in graph report flow, but it still needs a fresh Ubuntu graph run for real verification.
- Search modules exist, but local archive search is not yet proven end-to-end against a real or deterministic local video archive.
- Report quality is functional but not yet a priority; improving report format before business-flow gates are stable would mix concerns.

## File Structure

- `src/vsa_agent/live_video_acceptance.py`
  - Owns shared/graph live-video orchestration, graph QA/report separation, temporary graph-only tool overrides, and manifest metrics.
- `src/vsa_agent/live_run_validator.py`
  - Owns post-run validation, required events, flow statuses, tool error detection, model usage summary, and repeated LVS warnings.
- `src/vsa_agent/registry.py`
  - Owns tool registration and temporary tool override support.
- `src/vsa_agent/tools/video_understanding.py`
  - Owns short/long-video analysis entry point and VLM trace evidence.
- `src/vsa_agent/tools/lvs_video_understanding.py`
  - Owns long-video chunking and chunk-level trace evidence.
- `src/vsa_agent/agents/search_agent.py`
  - Owns natural-language search flow, query decomposition, result summarization, and optional critic integration.
- `src/vsa_agent/tools/search.py`
  - Owns search output models, conversion helpers, and search tool dispatch.
- `src/vsa_agent/tools/embed_search.py`
  - Owns embedding search tool path.
- `src/vsa_agent/tools/attribute_search.py`
  - Owns attribute search tool path.
- `src/vsa_agent/tools/vector_store.py`
  - Owns local vector search utility path.
- `tests/unit/test_live_top_agent_video_runner.py`
  - Unit gate for shared/graph live runner behavior and graph reuse.
- `tests/unit/test_live_run_validator.py`
  - Unit gate for run validation, tool errors, usage stats, and repeated LVS warnings.
- `tests/unit/test_registry.py`
  - Unit gate for temporary tool override behavior.
- `tests/acceptance/test_search_archive_flow.py`
  - New acceptance gate for local archive search.
- `docs/superpowers/reviews/project-status-2026-06-30.md`
  - Status document to update after each verified live run.
- `docs/superpowers/reviews/vsa-agent-original-vss-comprehensive-audit-2026-07-01.md`
  - Baseline audit document for parity scope.
- `openspec/changes/vss-business-flow-parity/`
  - New OpenSpec change for the next milestone.

## Task 1: Verify The Graph De-Duplication Fix On Ubuntu

**Files:**
- Read: `src/vsa_agent/live_video_acceptance.py`
- Read: `src/vsa_agent/live_run_validator.py`
- Output: `artifacts/live-video-runs/<run_id>/manifest.json`
- Output: `artifacts/live-video-runs/<run_id>/trace.jsonl`
- Modify: `docs/superpowers/reviews/project-status-2026-06-30.md`

**Interfaces:**
- Consumes: `VSA_LIVE_VIDEO_MODE=graph`, `scripts/run_live_top_agent_video_dashscope.sh`, `validate-run`.
- Produces: a fresh graph-mode run proving whether `lvs_completed_count` dropped from `3` to `1`.

- [ ] **Step 1: Run local unit verification before Ubuntu live run**

Run from Windows repo root:

```powershell
python -m pytest tests/unit/test_live_run_validator.py tests/unit/test_live_top_agent_video_runner.py tests/unit/test_registry.py tests/unit/test_dashscope_live_runner.py tests/unit/test_live_api_docs.py -q
```

Expected:

```text
27 passed, 2 skipped
```

- [ ] **Step 2: Run graph mode on Ubuntu**

Run on Ubuntu:

```bash
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
```

Expected:

```text
Running DashScope live TopAgent video acceptance
  mode: graph
```

- [ ] **Step 3: Validate the newest graph run**

Run:

```bash
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

Expected:

```text
PASS: live run validation
mode: graph
```

- [ ] **Step 4: Check graph cost metrics**

Run:

```bash
conda run -n vsa-agent python - <<'PY'
import json
from pathlib import Path
run = Path(__import__("os").environ["LATEST_RUN"])
m = json.loads((run / "manifest.json").read_text())
print(json.dumps(m.get("metrics", {}), indent=2, ensure_ascii=False))
PY
```

Expected:

```text
lvs_completed_count should be 1 in validator summary
vlm_call_count should be around 7
model_call_count should be much lower than 26
No warning: Repeated long-video understanding detected
```

- [ ] **Step 5: Update status document with real run evidence**

Modify `docs/superpowers/reviews/project-status-2026-06-30.md`.

Add a short entry under `Latest Known Live-Run Result`:

```markdown
The latest graph-mode Ubuntu run after graph de-duplication was:

`/data/project/lyk/vsa-agent/artifacts/live-video-runs/<run_id>`

Observed result:

- `validate-run` returned PASS.
- `mode` was `graph`.
- `lvs_completed_count` was `<value>`.
- `vlm_call_count` was `<value>`.
- `model_call_count` was `<value>`.
- `total_tokens` was `<value>`.
- `total_elapsed_sec` was `<value>`.
- Repeated LVS warning was `<present/absent>`.
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/reviews/project-status-2026-06-30.md
git commit -m "docs: record graph de-duplication live evidence"
```

## Task 2: Create The `vss-business-flow-parity` OpenSpec Change

**Files:**
- Create: `openspec/changes/vss-business-flow-parity/proposal.md`
- Create: `openspec/changes/vss-business-flow-parity/design.md`
- Create: `openspec/changes/vss-business-flow-parity/tasks.md`
- Create: `openspec/changes/vss-business-flow-parity/specs/recorded-video-business-flow/spec.md`

**Interfaces:**
- Consumes: `docs/superpowers/reviews/vsa-agent-original-vss-comprehensive-audit-2026-07-01.md`
- Produces: OpenSpec scope for recorded-video parity.

- [ ] **Step 1: Create proposal**

Create `openspec/changes/vss-business-flow-parity/proposal.md`:

```markdown
# vss-business-flow-parity

## Why

`vsa-agent` is intended to replace the useful recorded-video business flows from NVIDIA VSS without requiring NVIDIA runtime services. The current project can run real-video shared and graph validations, but still needs a scoped parity milestone for graph acceptance, local archive search, validation gates, and documented live-run evidence.

## What Changes

- Define recorded-video VSS parity around Q&A, long-video understanding, report generation, graph-mode TopAgent tool selection, local archive search, and replayable validation.
- Add local archive search acceptance independent of NVIDIA services.
- Promote live-run validator metrics and repeated-LVS warnings into acceptance criteria.
- Keep report quality, Enterprise RAG, real-time alerts, UI, production deployment, and full VST/VIOS parity out of this change.

## Impact

- Affects live-video validation, search acceptance tests, validator behavior, and project documentation.
- Does not add required NVIDIA dependencies.
```

- [ ] **Step 2: Create design**

Create `openspec/changes/vss-business-flow-parity/design.md`:

```markdown
# Design

## Scope

This change validates the open recorded-video business flow:

1. Resolve config from `config.yaml` plus optional `config.local.yaml`.
2. Analyze a real local video through shared and graph modes.
3. Prove graph-mode TopAgent can select tools without duplicate long-video VLM calls.
4. Validate run evidence with `validate-run`.
5. Add local archive search acceptance with deterministic local data.

## Out Of Scope

- Report wording polish.
- Enterprise RAG.
- Real-time alerts.
- UI.
- Production deployment.
- Full NVIDIA VST/VIOS parity.

## Acceptance Gates

- Unit tests for validator, live runner, registry, and search pass.
- Shared Ubuntu run validates with PASS.
- Graph Ubuntu run validates with PASS and no repeated LVS warning.
- Local archive search acceptance passes without Elasticsearch or NVIDIA services.
- Project status document records run IDs and metrics.
```

- [ ] **Step 3: Create tasks**

Create `openspec/changes/vss-business-flow-parity/tasks.md`:

```markdown
## 1. Live Graph Acceptance

- [ ] 1.1 Verify graph de-duplication on Ubuntu with a fresh live run.
- [ ] 1.2 Record graph run metrics and validator output in project status docs.
- [ ] 1.3 Promote repeated LVS warning to an explicit acceptance gate.

## 2. Local Archive Search Acceptance

- [ ] 2.1 Add deterministic local archive fixture.
- [ ] 2.2 Add acceptance test for `search_agent` over the local archive.
- [ ] 2.3 Ensure search results include video name, description, timestamps, sensor id, similarity, and object ids.

## 3. Business-Flow Documentation

- [ ] 3.1 Update status docs with shared and graph run evidence.
- [ ] 3.2 Document exact Ubuntu run and validation commands.
- [ ] 3.3 Document out-of-scope NVIDIA parity areas.

## 4. Verification

- [ ] 4.1 Run selected unit tests.
- [ ] 4.2 Run local archive acceptance test.
- [ ] 4.3 Run shared and graph live Ubuntu validation.
```

- [ ] **Step 4: Create capability spec**

Create `openspec/changes/vss-business-flow-parity/specs/recorded-video-business-flow/spec.md`:

```markdown
# recorded-video-business-flow

## ADDED Requirements

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
```

- [ ] **Step 5: Validate OpenSpec list**

Run:

```powershell
.\node_modules\.bin\openspec.cmd list --json
```

Expected:

```text
vss-business-flow-parity appears as in-progress
```

- [ ] **Step 6: Commit**

```bash
git add openspec/changes/vss-business-flow-parity
git commit -m "spec: add recorded-video business flow parity change"
```

## Task 3: Make Repeated LVS A Stronger Acceptance Gate

**Files:**
- Modify: `src/vsa_agent/live_run_validator.py`
- Modify: `tests/unit/test_live_run_validator.py`

**Interfaces:**
- Consumes: trace events from `trace.jsonl`.
- Produces: validator summary and warnings/failures for repeated long-video understanding.

- [ ] **Step 1: Write failing test for strict repeated-LVS mode**

Add to `tests/unit/test_live_run_validator.py`:

```python
def test_validate_live_run_can_fail_on_repeated_graph_lvs_when_strict(validator_dir, monkeypatch):
    from vsa_agent.live_run_validator import validate_live_run

    monkeypatch.setenv("VSA_STRICT_GRAPH_LVS", "1")
    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace_events(
        run_dir / "trace.jsonl",
        [
            {"event_type": "live_video_acceptance.run.started", "payload": {}},
            {"event_type": "top_agent.agent.request", "payload": {}},
            {"event_type": "top_agent.agent.response", "payload": {"has_tool_calls": True}},
            {"event_type": "top_agent.tool.call", "payload": {"tool_name": "video_understanding"}},
            {"event_type": "video_understanding.result", "payload": {}},
            {"event_type": "top_agent.tool.result", "payload": {"tool_name": "video_understanding", "result_preview": "ok"}},
            {"event_type": "top_agent.final", "payload": {"final_answer": "answer"}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "live_video_acceptance.run.completed", "payload": {}},
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is False
    assert any("Repeated long-video understanding" in failure for failure in result.failures)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/unit/test_live_run_validator.py::test_validate_live_run_can_fail_on_repeated_graph_lvs_when_strict -q
```

Expected:

```text
FAIL because repeated LVS is currently only a warning
```

- [ ] **Step 3: Implement strict gate**

Modify `src/vsa_agent/live_run_validator.py`:

```python
import os
```

Inside `validate_live_run`, where repeated LVS warning is created:

```python
message = (
    f"Repeated long-video understanding detected in graph mode: "
    f"lvs_video_understanding.completed={lvs_completed_count}"
)
if os.getenv("VSA_STRICT_GRAPH_LVS") == "1":
    failures.append(message)
else:
    warnings.append(message)
```

- [ ] **Step 4: Run validator tests**

Run:

```powershell
python -m pytest tests/unit/test_live_run_validator.py -q
```

Expected:

```text
All tests pass
```

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/live_run_validator.py tests/unit/test_live_run_validator.py
git commit -m "test: gate repeated graph long-video understanding"
```

## Task 4: Add Local Archive Search Acceptance

**Files:**
- Create: `tests/acceptance/test_search_archive_flow.py`
- Modify: `src/vsa_agent/tools/vector_store.py`
- Modify: `src/vsa_agent/tools/embed_search.py`
- Modify: `src/vsa_agent/tools/attribute_search.py`
- Modify: `src/vsa_agent/tools/search.py`
- Modify: `src/vsa_agent/agents/search_agent.py`

**Interfaces:**
- Consumes: deterministic local archive records.
- Produces: `SearchOutput` with `SearchResult` entries.

- [ ] **Step 1: Write failing acceptance test**

Create `tests/acceptance/test_search_archive_flow.py`:

```python
import pytest

from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.agents.search_agent import execute_search_agent_flow
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


@pytest.mark.asyncio
async def test_local_archive_search_returns_matching_video_result():
    async def local_embed_search(**kwargs):
        assert "forklift" in kwargs["query"].lower()
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="warehouse-safety-demo.mp4",
                    description="worker walking near forklift in loading area",
                    start_time="2026-06-23T10:00:00",
                    end_time="2026-06-23T10:00:08",
                    sensor_id="warehouse-cam-01",
                    screenshot_url="",
                    similarity=0.93,
                    object_ids=["person-1", "forklift-1"],
                )
            ]
        )

    result = await execute_search_agent_flow(
        SearchAgentInput(
            query="find a worker walking near a forklift",
            use_critic=False,
            use_attribute_search=False,
        ),
        embed_search=local_embed_search,
    )

    assert result.search_output.data
    first = result.search_output.data[0]
    assert first.video_name == "warehouse-safety-demo.mp4"
    assert first.sensor_id == "warehouse-cam-01"
    assert first.similarity >= 0.9
    assert "forklift" in first.description
    assert result.incidents
    assert "forklift" in result.text_answer
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```powershell
python -m pytest tests/acceptance/test_search_archive_flow.py -q
```

Expected:

```text
PASS if injected local search path already works
```

If it fails because callable signatures differ, adjust the acceptance test to match the existing `execute_search_agent_flow` interface rather than changing production code first.

- [ ] **Step 3: Add deterministic local store only if injection is insufficient**

If the injected path passes, do not add production code in this task. If it fails because `search_agent` cannot accept deterministic local search, add the smallest adapter required in `src/vsa_agent/tools/search.py`:

```python
async def local_archive_search(records: list[SearchResult], query: str, top_k: int = 5) -> SearchOutput:
    query_terms = {term.lower() for term in query.split()}
    ranked = []
    for record in records:
        text = f"{record.video_name} {record.description}".lower()
        score = sum(1 for term in query_terms if term in text)
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda item: (item[0], item[1].similarity), reverse=True)
    return SearchOutput(data=[record for _, record in ranked[:top_k]])
```

- [ ] **Step 4: Add unit test for local search helper if created**

Add to `tests/unit/tools/test_search.py`:

```python
@pytest.mark.asyncio
async def test_local_archive_search_ranks_matching_records():
    from vsa_agent.tools.search import SearchResult
    from vsa_agent.tools.search import local_archive_search

    records = [
        SearchResult(
            video_name="a.mp4",
            description="worker near forklift",
            start_time="t1",
            end_time="t2",
            sensor_id="cam-1",
            similarity=0.8,
            object_ids=["obj-1"],
        )
    ]

    result = await local_archive_search(records, "forklift worker")

    assert result.data[0].video_name == "a.mp4"
```

- [ ] **Step 5: Run search tests**

Run:

```powershell
python -m pytest tests/acceptance/test_search_archive_flow.py tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 6: Commit**

```bash
git add tests/acceptance/test_search_archive_flow.py src/vsa_agent/tools/search.py tests/unit/tools/test_search.py
git commit -m "test: add local archive search acceptance"
```

## Task 5: Update Runtime Docs With Exact Shared And Graph Commands

**Files:**
- Modify: `docs/testing/live-api-validation.md`
- Modify: `CONFIG.md`
- Modify: `docs/superpowers/reviews/project-status-2026-06-30.md`

**Interfaces:**
- Consumes: current unified config behavior and live runner commands.
- Produces: copy-paste-safe command docs.

- [ ] **Step 1: Add command section to live API docs**

Modify `docs/testing/live-api-validation.md` and add:

```markdown
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
```

- [ ] **Step 2: Add validator interpretation notes**

Add:

```markdown
Validator PASS means required files, trace events, model/profile fields, and flow statuses are present. It does not automatically mean the run was cheap or high quality. Inspect `model_call_count`, `vlm_call_count`, `total_tokens`, `lvs_completed_count`, and warnings.
```

- [ ] **Step 3: Update CONFIG.md command block**

Add:

```markdown
# Live real-video graph validation on Ubuntu
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

- [ ] **Step 4: Run doc tests if present**

Run:

```powershell
python -m pytest tests/unit/test_live_api_docs.py -q
```

Expected:

```text
Tests pass or documented live-key skips remain intentional
```

- [ ] **Step 5: Commit**

```bash
git add docs/testing/live-api-validation.md CONFIG.md docs/superpowers/reviews/project-status-2026-06-30.md
git commit -m "docs: document shared and graph live validation commands"
```

## Task 6: Verify And Close The Parity Milestone

**Files:**
- Read: `openspec/changes/vss-business-flow-parity/tasks.md`
- Read: `docs/superpowers/reviews/project-status-2026-06-30.md`
- Output: Ubuntu `artifacts/live-video-runs/<run_id>/`

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: verified evidence ready for Comet verify/archive decision.

- [ ] **Step 1: Run selected unit and acceptance tests**

Run:

```powershell
python -m pytest tests/unit/test_live_run_validator.py tests/unit/test_live_top_agent_video_runner.py tests/unit/test_registry.py tests/acceptance/test_search_archive_flow.py -q
```

Expected:

```text
All selected tests pass
```

- [ ] **Step 2: Run shared live validation on Ubuntu**

Run:

```bash
cd /data/project/lyk/vsa-agent
unset VSA_LIVE_VIDEO_MODE
bash scripts/run_live_top_agent_video_dashscope.sh
SHARED_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$SHARED_RUN"
```

Expected:

```text
PASS: live run validation
mode: shared
```

- [ ] **Step 3: Run graph live validation on Ubuntu**

Run:

```bash
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
GRAPH_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$GRAPH_RUN"
```

Expected:

```text
PASS: live run validation
mode: graph
No repeated LVS warning
```

- [ ] **Step 4: Mark OpenSpec tasks complete**

Update `openspec/changes/vss-business-flow-parity/tasks.md` by checking completed items.

- [ ] **Step 5: Run OpenSpec status**

Run:

```powershell
.\node_modules\.bin\openspec.cmd list --json
```

Expected:

```text
vss-business-flow-parity completedTasks equals totalTasks
```

- [ ] **Step 6: Commit**

```bash
git add openspec/changes/vss-business-flow-parity docs/superpowers/reviews/project-status-2026-06-30.md
git commit -m "chore: verify recorded-video business flow parity"
```

## Self-Review

- Spec coverage: The plan covers graph cost stabilization, new OpenSpec parity scope, validator gates, local archive search acceptance, docs, and live verification.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation placeholders remain.
- Type consistency: Function names and file names match current code: `validate_live_run`, `run_live_top_agent_video_acceptance`, `temporary_tool_override`, `execute_search_agent_flow`, `SearchOutput`, and `SearchResult`.
- Scope control: Report quality, RAG, real-time alerts, UI, deployment, and full VST/VIOS parity are explicitly out of scope.
