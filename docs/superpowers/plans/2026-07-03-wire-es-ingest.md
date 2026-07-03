---
change: wire-es-ingest
design-doc: docs/superpowers/specs/2026-07-03-wire-es-ingest-design.md
base-ref: 5f5a0fbbea5aed470ce8a90e51110855b2492942
---

# Wire ES Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/search/ingest` truthfully index recorded-video search metadata into Elasticsearch when configured.

**Architecture:** Keep the endpoint as a small FastAPI router and reuse `SearchBackendConfig`. The API normalizes a caller-provided metadata object into one ES document and reports skipped, success, or upstream failure explicitly.

**Tech Stack:** FastAPI, Pydantic, `elasticsearch.AsyncElasticsearch`, pytest.

## Global Constraints

- Use the existing `search` configuration block only.
- Do not generate embeddings in this change.
- Do not fake success when ES is disabled or indexing fails.
- Keep route compatibility at `POST /api/search/ingest`.

---

### Task 1: API Tests

**Files:**
- Modify: `tests/unit/api/test_video_search_ingest.py`

**Interfaces:**
- Consumes: `vsa_agent.api.video_search_ingest.router`
- Produces: tests for `VideoSearchIngestRequest`, skipped behavior, successful indexing, ES failure, and app route registration.

- [x] **Step 1: Write failing tests**

Add pytest coverage using `fastapi.testclient.TestClient` and monkeypatched config/client fakes.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/api/test_video_search_ingest.py -q`

Expected: failures showing the current mock endpoint does not accept the desired JSON body, does not call ES, does not return 502, or is not registered on the app.

### Task 2: Endpoint Implementation

**Files:**
- Modify: `src/vsa_agent/api/video_search_ingest.py`

**Interfaces:**
- Consumes: `get_config().search`
- Produces: `_build_ingest_document(video_id: str, metadata: dict[str, Any]) -> dict[str, Any]`
- Produces: `video_search_ingest(request: VideoSearchIngestRequest) -> VideoSearchIngestResponse`

- [x] **Step 1: Add request/response models and metadata normalization**

Implement typed request and response models plus a helper that promotes common metadata fields.

- [x] **Step 2: Add config-driven ES behavior**

Return skipped when disabled or missing endpoint. Otherwise, create `AsyncElasticsearch`, index the document into `search.embed_index`, return the ES id, and raise HTTP 502 on indexing failure.

- [x] **Step 3: Run focused test**

Run: `python -m pytest tests/unit/api/test_video_search_ingest.py -q`

Expected: all tests in the file pass.

### Task 3: Route Wiring

**Files:**
- Modify: `src/vsa_agent/api/routes.py`

**Interfaces:**
- Consumes: `vsa_agent.api.video_search_ingest.router`
- Produces: registered `/api/search/ingest` route in the FastAPI app.

- [x] **Step 1: Register the router**

Import the ingest router and extend `app.router.routes` with it near the existing video API routers.

- [x] **Step 2: Run focused test**

Run: `python -m pytest tests/unit/api/test_video_search_ingest.py -q`

Expected: route registration test passes.

### Task 4: Verification and Tracking

**Files:**
- Modify: `openspec/changes/wire-es-ingest/tasks.md`

**Interfaces:**
- Produces: checked OpenSpec task list and verification notes for final handoff.

- [x] **Step 1: Run focused verification set**

Run: `python -m pytest tests/unit/api/test_video_search_ingest.py tests/unit/api/test_original_ui_chat.py tests/unit/api/test_original_ui_chat_route.py tests/unit/test_config_search.py tests/unit/tools/test_embed_search.py tests/unit/tools/test_attribute_search.py tests/unit/tools/test_search.py tests/unit/agents/test_search_agent.py -q`

Expected: focused set passes in this worktree.

- [x] **Step 2: Update tasks**

Check off completed tasks in `openspec/changes/wire-es-ingest/tasks.md`.

- [x] **Step 3: Inspect diff**

Run: `git status --short` and review the relevant diff before staging.
