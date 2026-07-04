# Verify ES Ingest Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in runtime smoke validation path proving `/api/search/ingest` writes to a real Elasticsearch index.

**Architecture:** Keep normal unit tests isolated from Elasticsearch. Add a Python smoke script under `scripts/` that targets a running API service and Elasticsearch endpoint, validates the ingest response, refreshes/searches the configured index, and validates the indexed document. Add docs that show how to start Elasticsearch/API service, run the script, inspect results, and clean up.

**Tech Stack:** Python standard library, `elasticsearch.AsyncElasticsearch`, FastAPI app `vsa_agent.api.routes:app`, existing `SearchBackendConfig` fields, OpenSpec/Comet.

## Global Constraints

- All project-development work MUST be managed through the `comet` skill workflow.
- Development uses local branches or worktrees only; completed work merges locally to `master` and pushes only `master`.
- Default `config.yaml` must keep `search.enabled: false`.
- Normal unit tests must not require a running Elasticsearch service.
- Runtime smoke validation must fail clearly when Elasticsearch or the API service is unavailable.
- The `/api/search/ingest` API contract must remain unchanged unless validation exposes a concrete defect.

---

## File Structure

- Create `scripts/es_ingest_smoke.py`: opt-in smoke validator with argument parsing, API POST, Elasticsearch lookup, and validation helpers.
- Create `tests/unit/scripts/test_es_ingest_smoke.py`: unit tests for helper behavior that does not require real Elasticsearch.
- Create `docs/es-ingest-runtime-validation.md`: operational instructions for local/server validation.
- Modify `docs/DEVELOPMENT_STATUS.md`: mark the active change and point to the smoke command.
- Modify `openspec/changes/verify-es-ingest-runtime/tasks.md`: check off completed Comet tasks as implementation proceeds.

---

### Task 1: Smoke Script Helper Layer

**Files:**
- Create: `scripts/es_ingest_smoke.py`
- Create: `tests/unit/scripts/test_es_ingest_smoke.py`

**Interfaces:**
- Produces: `sample_payload(video_id: str) -> dict[str, object]`
- Produces: `validate_ingest_response(payload: dict[str, object], expected_video_id: str) -> str`
- Produces: `validate_indexed_document(document: dict[str, object], expected_video_id: str) -> None`

- [x] **Step 1: Write failing tests for payload and response validation**

Add `tests/unit/scripts/test_es_ingest_smoke.py`:

```python
from scripts.es_ingest_smoke import sample_payload
from scripts.es_ingest_smoke import validate_indexed_document
from scripts.es_ingest_smoke import validate_ingest_response


def test_sample_payload_contains_required_metadata():
    payload = sample_payload("runtime-video-1")

    assert payload["video_id"] == "runtime-video-1"
    metadata = payload["metadata"]
    assert metadata["video_name"] == "runtime-validation.mp4"
    assert metadata["description"] == "forklift passes near worker in loading zone"
    assert metadata["sensor_id"] == "camera-runtime-1"
    assert metadata["start_time"] == "2026-07-04T08:00:00Z"
    assert metadata["end_time"] == "2026-07-04T08:00:05Z"
    assert metadata["screenshot_url"] == "http://example.invalid/frames/runtime-validation.jpg"
    assert metadata["vector"] == [0.11, 0.22, 0.33]


def test_validate_ingest_response_returns_result_id():
    result_id = validate_ingest_response(
        {"status": "ingested", "video_id": "runtime-video-1", "indexed": True, "result_id": "abc123"},
        expected_video_id="runtime-video-1",
    )

    assert result_id == "abc123"


def test_validate_ingest_response_rejects_skipped_status():
    try:
        validate_ingest_response(
            {"status": "skipped", "video_id": "runtime-video-1", "indexed": False, "result_id": None},
            expected_video_id="runtime-video-1",
        )
    except RuntimeError as exc:
        assert "Expected ingested/indexed response" in str(exc)
    else:
        raise AssertionError("validate_ingest_response should reject skipped responses")


def test_validate_indexed_document_accepts_required_fields():
    validate_indexed_document(
        {
            "video_id": "runtime-video-1",
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": [0.11, 0.22, 0.33],
            "metadata": {"site": "runtime-yard"},
        },
        expected_video_id="runtime-video-1",
    )


def test_validate_indexed_document_rejects_wrong_video_id():
    try:
        validate_indexed_document({"video_id": "other", "metadata": {}}, expected_video_id="runtime-video-1")
    except RuntimeError as exc:
        assert "video_id" in str(exc)
    else:
        raise AssertionError("validate_indexed_document should reject mismatched video_id")
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests\unit\scripts\test_es_ingest_smoke.py -q
```

Expected: FAIL because `scripts.es_ingest_smoke` does not exist.

- [x] **Step 3: Implement helper functions**

Create `scripts/es_ingest_smoke.py` with:

```python
from __future__ import annotations

from typing import Any


def sample_payload(video_id: str) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "metadata": {
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": [0.11, 0.22, 0.33],
            "site": "runtime-yard",
        },
    }


def validate_ingest_response(payload: dict[str, Any], expected_video_id: str) -> str:
    if payload.get("status") != "ingested" or payload.get("indexed") is not True:
        raise RuntimeError(f"Expected ingested/indexed response, got: {payload}")
    if payload.get("video_id") != expected_video_id:
        raise RuntimeError(f"Expected video_id {expected_video_id!r}, got {payload.get('video_id')!r}")
    result_id = payload.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        raise RuntimeError(f"Expected non-empty result_id, got: {result_id!r}")
    return result_id


def validate_indexed_document(document: dict[str, Any], expected_video_id: str) -> None:
    expected = sample_payload(expected_video_id)["metadata"]
    checks = {
        "video_id": expected_video_id,
        "video_name": expected["video_name"],
        "description": expected["description"],
        "sensor_id": expected["sensor_id"],
        "start_time": expected["start_time"],
        "end_time": expected["end_time"],
        "screenshot_url": expected["screenshot_url"],
        "vector": expected["vector"],
    }
    for key, value in checks.items():
        if document.get(key) != value:
            raise RuntimeError(f"Indexed document field {key!r} mismatch: expected {value!r}, got {document.get(key)!r}")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("site") != "runtime-yard":
        raise RuntimeError(f"Indexed document metadata missing expected site: {metadata!r}")
```

- [x] **Step 4: Run helper tests**

Run:

```powershell
python -m pytest tests\unit\scripts\test_es_ingest_smoke.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

Run:

```powershell
git add scripts\es_ingest_smoke.py tests\unit\scripts\test_es_ingest_smoke.py openspec\changes\verify-es-ingest-runtime\tasks.md
git commit -m "test: add es ingest smoke validation helpers"
```

### Task 2: Runtime Smoke Execution

**Files:**
- Modify: `scripts/es_ingest_smoke.py`
- Modify: `tests/unit/scripts/test_es_ingest_smoke.py`

**Interfaces:**
- Produces: CLI command `python scripts/es_ingest_smoke.py --api-url <url> --es-endpoint <url> --index <name>`
- Consumes: running FastAPI service exposing `/api/search/ingest`
- Consumes: reachable Elasticsearch endpoint

- [x] **Step 1: Add tests for API request helper with fake opener**

Add these tests to `tests/unit/scripts/test_es_ingest_smoke.py`:

```python
import json

from scripts.es_ingest_smoke import post_ingest


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_post_ingest_posts_json_to_ingest_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        captured["content_type"] = request.headers["Content-type"]
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"status": "ingested", "video_id": "runtime-video-1", "indexed": True, "result_id": "abc123"})

    monkeypatch.setattr("scripts.es_ingest_smoke.urlopen", fake_urlopen)

    response = post_ingest("http://127.0.0.1:8000", {"video_id": "runtime-video-1"}, timeout_sec=7.5)

    assert response["result_id"] == "abc123"
    assert captured == {
        "url": "http://127.0.0.1:8000/api/search/ingest",
        "timeout": 7.5,
        "method": "POST",
        "content_type": "application/json",
        "body": {"video_id": "runtime-video-1"},
    }
```

- [x] **Step 2: Implement HTTP POST helper using Python standard library**

Add `post_ingest(api_url: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]` using `urllib.request.Request` and `urllib.request.urlopen`.

Implementation requirements:

- Import `Request` and `urlopen` directly from `urllib.request` so tests can monkeypatch `scripts.es_ingest_smoke.urlopen`.
- Strip a trailing slash from `api_url` before appending `/api/search/ingest`.
- Encode payload with `json.dumps(payload).encode("utf-8")`.
- Set `Content-Type: application/json`.
- Return the decoded JSON object as `dict[str, Any]`.

- [x] **Step 3: Implement Elasticsearch lookup helpers**

Add async helpers:

```python
async def find_indexed_document(es_endpoint: str, index: str, video_id: str, timeout_sec: float, verify_certs: bool) -> dict[str, Any]:
    """Return the indexed document for video_id or raise RuntimeError."""
```

Implementation requirements:

- Create `AsyncElasticsearch(es_endpoint, request_timeout=timeout_sec, verify_certs=verify_certs)`.
- In a `try/finally`, close the client with `await es.close()`.
- Call `await es.indices.refresh(index=index)` before searching.
- First search body:

```python
{"query": {"term": {"video_id.keyword": video_id}}, "size": 1}
```

- If no hits are returned, run fallback body:

```python
{"query": {"match": {"video_id": video_id}}, "size": 1}
```

- Return `hits["hits"][0]["_source"]` when found.
- Raise `RuntimeError(f"Indexed document not found for video_id={video_id!r} in index={index!r}")` when both searches return no hits.

- [x] **Step 4: Implement CLI**

Add `argparse` flags:

- `--api-url`, default from `VSA_API_URL`, fallback `http://127.0.0.1:8000`
- `--es-endpoint`, default from `VSA_ES_ENDPOINT`, required if env missing
- `--index`, default from `VSA_ES_INDEX`, fallback `vsa-video-embeddings`
- `--video-id`, default `runtime-video-<timestamp>`
- `--timeout-sec`, default `30`
- `--insecure`, sets `verify_certs=False`

The CLI should print `PASS: Elasticsearch ingest smoke validation` on success and exit non-zero on failure.

- [x] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests\unit\scripts\test_es_ingest_smoke.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

Run:

```powershell
git add scripts\es_ingest_smoke.py tests\unit\scripts\test_es_ingest_smoke.py openspec\changes\verify-es-ingest-runtime\tasks.md
git commit -m "feat: add es ingest runtime smoke script"
```

### Task 3: Runtime Documentation And Status

**Files:**
- Create: `docs/es-ingest-runtime-validation.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Produces: documented local/server validation flow
- Consumes: `scripts/es_ingest_smoke.py`

- [x] **Step 1: Write validation documentation**

Create `docs/es-ingest-runtime-validation.md` with these sections:

- Purpose
- Prerequisites
- Temporary config example with `search.enabled: true`
- API startup command, for example `python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port 8000`
- Smoke command
- Expected PASS output
- Manual Elasticsearch inspection command
- Cleanup command for the test index or test document
- Server validation notes

- [x] **Step 2: Update development status**

Update `docs/DEVELOPMENT_STATUS.md`:

- Current active change: `verify-es-ingest-runtime`
- Branch: `codex/es-real-service-validation`
- Next validation command: `python scripts/es_ingest_smoke.py --api-url http://127.0.0.1:8000 --es-endpoint <endpoint> --index vsa-video-embeddings`

- [x] **Step 3: Commit**

Run:

```powershell
git add docs\es-ingest-runtime-validation.md docs\DEVELOPMENT_STATUS.md openspec\changes\verify-es-ingest-runtime\tasks.md
git commit -m "docs: add es ingest runtime validation guide"
```

### Task 4: Verification And Comet Build Close

**Files:**
- Modify: `openspec/changes/verify-es-ingest-runtime/tasks.md`
- Modify: `openspec/changes/verify-es-ingest-runtime/.comet.yaml`

**Interfaces:**
- Consumes: Comet shell guard
- Produces: build-ready change for verify phase

- [x] **Step 1: Run focused unit tests**

Run:

```powershell
python -m pytest tests\unit\scripts\test_es_ingest_smoke.py tests\unit\api\test_video_search_ingest.py -q
```

Expected: PASS.

- [x] **Step 2: Run OpenSpec validation**

Run:

```powershell
npx openspec validate verify-es-ingest-runtime
```

Expected: `Change 'verify-es-ingest-runtime' is valid`.

- [x] **Step 3: Run Comet build guard**

Run:

```powershell
bash -lc 'source .agents/skills/comet/scripts/comet-env.sh && "$COMET_BASH" "$COMET_GUARD" verify-es-ingest-runtime build --apply'
```

Expected: guard passes and `.comet.yaml` moves to `phase: verify`.

- [x] **Step 4: Commit**

Run:

```powershell
git add openspec\changes\verify-es-ingest-runtime\.comet.yaml openspec\changes\verify-es-ingest-runtime\tasks.md
git commit -m "chore: complete es validation build phase"
```
