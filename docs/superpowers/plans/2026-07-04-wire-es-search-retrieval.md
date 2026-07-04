---
change: wire-es-search-retrieval
design-doc: docs/superpowers/specs/2026-07-04-wire-es-search-retrieval-design.md
base-ref: 681c81767bcc5134031c406f4d7a903fc165d0c1
---

# ES Video Segment Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current project retrieve `/api/search/ingest` video segment index records through Elasticsearch, then provide scriptable local/server ES startup and validation.

**Architecture:** Keep the lightweight current-project path: `/api/search/ingest` normalizes one video segment index record, `embed_search_tool` searches the configured `search.embed_index`, and runtime scripts prove ingest-then-search without copying the original VSS Kafka/Logstash pipeline. Unit tests mock ES and embeddings; runtime validation is isolated in scripts.

**Tech Stack:** Python 3.11+, FastAPI, pytest/pytest-asyncio, `elasticsearch.AsyncElasticsearch`, Docker Compose for single-node development Elasticsearch, PowerShell scripts for Windows/local and mapped `Z:\vsa-agent` use.

## Global Constraints

- Development must follow Comet; this plan belongs to OpenSpec change `wire-es-search-retrieval`.
- Use TDD for code changes: write a focused failing test, run it, implement the smallest passing change, then run the focused tests again.
- Treat "Elasticsearch document" as a video segment index record, not a Word/PDF/RAG document.
- Preserve vector-first ES behavior; keyword fallback may exist only as an explicit resilience/runtime-validation path with visible warning behavior.
- Keep Enterprise RAG document retrieval and `frag_retrieval` out of this change.
- Do not enable Elasticsearch by default in committed `config.yaml`.
- After local implementation is complete, sync changed code/scripts/docs to `Z:\vsa-agent` and attempt server-side validation when the mapped environment can execute it.
- Git policy for this solo project: finish locally on the development branch, merge locally to `master`, then push only remote `master`.

---

## File Structure

- Modify `tests/unit/tools/test_embed_search.py`: add ES video segment hit mapping, query body, ES failure, and optional keyword fallback tests.
- Modify `src/vsa_agent/tools/embed_search.py`: add only the minimal search behavior needed by tests, likely a guarded keyword fallback helper and stable video segment field mapping refinements.
- Modify `tests/unit/api/test_video_search_ingest.py`: add aliases/contract tests for normalized video segment index records if the existing tests do not already cover every design field.
- Modify `src/vsa_agent/api/video_search_ingest.py`: only if ingest normalization misses a tested field or alias.
- Modify `scripts/es_ingest_smoke.py`: extend runtime validation from "document indexed" to "document can be searched".
- Modify `tests/unit/scripts/test_es_ingest_smoke.py`: cover the new runtime search validation helper.
- Create `docker-compose.es.yml`: single-node development Elasticsearch service.
- Create `scripts/es-dev-start.ps1`, `scripts/es-dev-stop.ps1`, and `scripts/es-dev-probe.ps1`: scriptable ES lifecycle for local and mapped-server project copies.
- Create or modify `docs/superpowers/reference/es-video-search-runtime.md`: local and `Z:\vsa-agent` startup/validation instructions.
- Modify `openspec/changes/wire-es-search-retrieval/tasks.md`: check off completed tasks after each verified commit.

## Task 1: ES Retrieval Unit Tests

**Files:**
- Modify: `tests/unit/tools/test_embed_search.py`
- Verify against: `src/vsa_agent/tools/embed_search.py`

**Interfaces:**
- Consumes: `embed_search._search_real_es(query: str, top_k: int, search_config: SearchBackendConfig) -> SearchOutput | None`
- Produces: failing tests that define expected ES video segment search behavior before implementation.

- [ ] **Step 1: Add a fake ES client and embedding client test for video segment hits**

Add tests equivalent to this shape in `tests/unit/tools/test_embed_search.py`:

```python
@pytest.mark.asyncio
async def test_search_real_es_returns_ingested_video_segment_record(monkeypatch):
    from vsa_agent.config import SearchBackendConfig
    from vsa_agent.tools.embed_search import _search_real_es

    created_clients = []

    class FakeIndices:
        async def exists(self, index):
            assert index == "vsa-video-embeddings"
            return True

    class FakeES:
        def __init__(self, endpoint, request_timeout, verify_certs):
            assert endpoint == "http://es:9200"
            assert request_timeout == 9.0
            assert verify_certs is False
            self.indices = FakeIndices()
            self.search_bodies = []
            self.closed = False
            created_clients.append(self)

        async def search(self, index, body):
            self.search_bodies.append((index, body))
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.87,
                            "_source": {
                                "video_id": "runtime-video-1",
                                "video_name": "runtime-validation.mp4",
                                "description": "forklift passes near worker",
                                "sensor_id": "camera-runtime-1",
                                "start_time": "2026-07-04T08:00:00Z",
                                "end_time": "2026-07-04T08:00:05Z",
                                "screenshot_url": "http://example.invalid/frame.jpg",
                                "vector": [0.11, 0.22, 0.33],
                                "metadata": {"site": "runtime-yard"},
                            },
                        }
                    ]
                }
            }

        async def close(self):
            self.closed = True

    class FakeEmbedClient:
        async def embed_query(self, query):
            assert query == "forklift near worker"
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr("vsa_agent.tools.embed_search.AsyncElasticsearch", FakeES)
    monkeypatch.setattr("vsa_agent.tools.embed_search._create_default_embed_client", lambda: FakeEmbedClient())

    output = await _search_real_es(
        "forklift near worker",
        top_k=3,
        search_config=SearchBackendConfig(
            enabled=True,
            es_endpoint="http://es:9200",
            embed_index="vsa-video-embeddings",
            vector_field="vector",
            embed_confidence_threshold=0.2,
            request_timeout_sec=9.0,
            verify_certs=False,
        ),
    )

    assert output is not None
    assert len(output.data) == 1
    result = output.data[0]
    assert result.video_name == "runtime-validation.mp4"
    assert result.description == "forklift passes near worker"
    assert result.sensor_id == "camera-runtime-1"
    assert result.start_time == "2026-07-04T08:00:00Z"
    assert result.end_time == "2026-07-04T08:00:05Z"
    assert result.screenshot_url == "http://example.invalid/frame.jpg"
    assert result.similarity == 0.87
    assert created_clients[0].search_bodies[0][0] == "vsa-video-embeddings"
    assert created_clients[0].search_bodies[0][1]["query"]["script_score"]["script"]["params"]["query_vector"] == [0.1, 0.2, 0.3]
    assert created_clients[0].closed is True
```

- [ ] **Step 2: Add a failure-preserves-fallback test at `embed_search_tool` level**

Add a test equivalent to:

```python
@pytest.mark.asyncio
async def test_embed_search_tool_uses_store_when_es_search_raises(monkeypatch):
    from vsa_agent.config import AppConfig, SearchBackendConfig
    from vsa_agent.tools.embed_search import embed_search_tool
    from vsa_agent.tools.search import SearchOutput, SearchResult

    async def fake_search_real_es(query, top_k, search_config):
        raise RuntimeError("es rejected vector query")

    class FakeStore:
        async def search(self, query, top_k):
            assert query == "worker near forklift"
            assert top_k == 2
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="fallback.mp4",
                        description="fallback result",
                        start_time="t1",
                        end_time="t2",
                        sensor_id="cam-fallback",
                        similarity=0.42,
                    )
                ]
            )

    monkeypatch.setattr(
        "vsa_agent.config.get_config",
        lambda: AppConfig(search=SearchBackendConfig(enabled=True, es_endpoint="http://es:9200")),
    )
    monkeypatch.setattr("vsa_agent.tools.embed_search._search_real_es", fake_search_real_es)

    output = await embed_search_tool("worker near forklift", store=FakeStore(), top_k=2)

    assert output.data[0].video_name == "fallback.mp4"
```

- [ ] **Step 3: Run the new tests and confirm red**

Run:

```powershell
pytest tests/unit/tools/test_embed_search.py -q
```

Expected: at least one new test fails before implementation, most likely because keyword fallback/search validation helper does not exist yet or a query/mapping expectation differs.

- [ ] **Step 4: Commit tests only if they fail for the intended reason**

Commit after the red phase:

```powershell
git add tests/unit/tools/test_embed_search.py
git commit -m "test: define es video segment retrieval"
```

## Task 2: Minimal ES Retrieval Implementation

**Files:**
- Modify: `src/vsa_agent/tools/embed_search.py`
- Test: `tests/unit/tools/test_embed_search.py`

**Interfaces:**
- Consumes: failing tests from Task 1.
- Produces: ES vector search returning `SearchOutput` for video segment records and preserving fallback on ES errors.

- [ ] **Step 1: Implement only what Task 1 requires**

In `src/vsa_agent/tools/embed_search.py`, keep `_search_real_es` vector-first. If the tests expose a missing behavior, make the smallest change. Acceptable changes:

```python
def _source_text(source: dict[str, Any]) -> str:
    metadata = source.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return (
        source.get("description")
        or source.get("caption")
        or source.get("summary")
        or source.get("text")
        or metadata.get("description")
        or metadata.get("caption")
        or metadata.get("summary")
        or metadata.get("text")
        or ""
    )
```

Only add a helper like this if stable top-level and metadata fallback behavior is not already covered by `_process_search_hit`.

- [ ] **Step 2: Keep ES failure fallback at `embed_search_tool` boundary**

Do not catch and hide every error inside `_search_real_es`. Let unexpected ES/vector failures bubble to `embed_search_tool`, where the existing warning and store fallback preserve behavior.

- [ ] **Step 3: Run focused tests**

Run:

```powershell
pytest tests/unit/tools/test_embed_search.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit implementation**

```powershell
git add src/vsa_agent/tools/embed_search.py tests/unit/tools/test_embed_search.py
git commit -m "feat: retrieve es video segment records"
```

## Task 3: Ingest Contract Tests

**Files:**
- Modify: `tests/unit/api/test_video_search_ingest.py`
- Modify if required: `src/vsa_agent/api/video_search_ingest.py`

**Interfaces:**
- Consumes: `_build_ingest_document(video_id: str, metadata: dict[str, Any]) -> dict[str, Any]`
- Produces: explicit tests that the ingest endpoint writes a video segment index record with aliases normalized.

- [ ] **Step 1: Add contract test for aliases**

Add a test equivalent to:

```python
def test_build_ingest_document_normalizes_video_segment_aliases():
    from vsa_agent.api.video_search_ingest import _build_ingest_document

    document = _build_ingest_document(
        "video-42",
        {
            "filename": "dock-camera.mp4",
            "caption": "worker walks through loading dock",
            "sensor": {"id": "camera-7"},
            "timestamp": "2026-07-04T09:00:00Z",
            "timestamp_end": "2026-07-04T09:00:04Z",
            "thumbnail_url": "http://example.invalid/thumb.jpg",
            "vector": [0.2, 0.3, 0.4],
            "site": "dock-a",
        },
    )

    assert document == {
        "video_id": "video-42",
        "video_name": "dock-camera.mp4",
        "description": "worker walks through loading dock",
        "sensor_id": "camera-7",
        "start_time": "2026-07-04T09:00:00Z",
        "end_time": "2026-07-04T09:00:04Z",
        "screenshot_url": "http://example.invalid/thumb.jpg",
        "vector": [0.2, 0.3, 0.4],
        "metadata": {
            "filename": "dock-camera.mp4",
            "caption": "worker walks through loading dock",
            "sensor": {"id": "camera-7"},
            "timestamp": "2026-07-04T09:00:00Z",
            "timestamp_end": "2026-07-04T09:00:04Z",
            "thumbnail_url": "http://example.invalid/thumb.jpg",
            "vector": [0.2, 0.3, 0.4],
            "site": "dock-a",
        },
    }
```

- [ ] **Step 2: Run contract test and confirm result**

Run:

```powershell
pytest tests/unit/api/test_video_search_ingest.py -q
```

Expected: PASS if current code already satisfies the contract; otherwise FAIL for the exact missing field or alias.

- [ ] **Step 3: Implement only missing normalization if the test fails**

If the test fails, update `_build_ingest_document` so top-level fields match the contract and `metadata` preserves the original source payload.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/unit/api/test_video_search_ingest.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit ingest contract**

```powershell
git add tests/unit/api/test_video_search_ingest.py src/vsa_agent/api/video_search_ingest.py
git commit -m "test: lock video segment ingest contract"
```

## Task 4: Runtime Search Validation Script

**Files:**
- Modify: `scripts/es_ingest_smoke.py`
- Modify: `tests/unit/scripts/test_es_ingest_smoke.py`

**Interfaces:**
- Consumes: `sample_payload`, `post_ingest`, `find_indexed_document`
- Produces: runtime validation that can ingest and then search for a sample video segment record.

- [ ] **Step 1: Add failing unit test for search validation helper**

Add a test equivalent to:

```python
@pytest.mark.asyncio
async def test_search_indexed_document_uses_description_match(monkeypatch):
    from scripts.es_ingest_smoke import search_indexed_document

    created_clients = []

    class FakeAsyncElasticsearch:
        def __init__(self, endpoint, request_timeout, verify_certs):
            self.endpoint = endpoint
            self.request_timeout = request_timeout
            self.verify_certs = verify_certs
            self.search_bodies = []
            self.closed = False
            created_clients.append(self)

        async def search(self, index, body):
            self.search_bodies.append((index, body))
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "video_id": "runtime-video-1",
                                "description": "forklift passes near worker in loading zone",
                            }
                        }
                    ]
                }
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr("scripts.es_ingest_smoke.AsyncElasticsearch", FakeAsyncElasticsearch)

    document = await search_indexed_document(
        "http://es:9200",
        index="vsa-video-embeddings",
        query="forklift worker",
        timeout_sec=5.0,
        verify_certs=False,
    )

    assert document["video_id"] == "runtime-video-1"
    assert created_clients[0].search_bodies == [
        (
            "vsa-video-embeddings",
            {
                "query": {
                    "multi_match": {
                        "query": "forklift worker",
                        "fields": ["description", "video_name", "sensor_id", "metadata.description", "metadata.site"],
                    }
                },
                "size": 1,
            },
        )
    ]
    assert created_clients[0].closed is True
```

- [ ] **Step 2: Run the new script test and confirm red**

Run:

```powershell
pytest tests/unit/scripts/test_es_ingest_smoke.py -q
```

Expected: FAIL because `search_indexed_document` is not defined.

- [ ] **Step 3: Implement `search_indexed_document` and call it from `_run`**

Add this helper to `scripts/es_ingest_smoke.py`:

```python
async def search_indexed_document(
    es_endpoint: str,
    index: str,
    query: str,
    timeout_sec: float,
    verify_certs: bool,
) -> dict[str, Any]:
    es = AsyncElasticsearch(es_endpoint, request_timeout=timeout_sec, verify_certs=verify_certs)
    try:
        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["description", "video_name", "sensor_id", "metadata.description", "metadata.site"],
                }
            },
            "size": 1,
        }
        result = await es.search(index=index, body=body)
        hits = result.get("hits", {}).get("hits", [])
        if hits:
            source = hits[0].get("_source", {})
            if not isinstance(source, dict):
                raise RuntimeError(f"Expected search hit source to be an object, got: {source!r}")
            return source
    finally:
        await es.close()

    raise RuntimeError(f"Search validation found no hits for query={query!r} in index={index!r}")
```

Then update `_run` after `validate_indexed_document(...)`:

```python
    search_hit = await search_indexed_document(
        args.es_endpoint,
        index=args.index,
        query="forklift worker",
        timeout_sec=args.timeout_sec,
        verify_certs=not args.insecure,
    )
    if search_hit.get("video_id") != args.video_id:
        raise RuntimeError(f"Search hit video_id mismatch: expected {args.video_id!r}, got {search_hit.get('video_id')!r}")
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/unit/scripts/test_es_ingest_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit runtime validation helper**

```powershell
git add scripts/es_ingest_smoke.py tests/unit/scripts/test_es_ingest_smoke.py
git commit -m "feat: validate es ingest search path"
```

## Task 5: Scriptable Development Elasticsearch Runtime

**Files:**
- Create: `docker-compose.es.yml`
- Create: `scripts/es-dev-start.ps1`
- Create: `scripts/es-dev-stop.ps1`
- Create: `scripts/es-dev-probe.ps1`
- Create or modify: `docs/superpowers/reference/es-video-search-runtime.md`

**Interfaces:**
- Consumes: Docker CLI with Compose support.
- Produces: repeatable local/server project commands to start, stop, and probe ES.

- [ ] **Step 1: Add Docker Compose file**

Create `docker-compose.es.yml`:

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.14.3
    container_name: ${VSA_ES_CONTAINER_NAME:-vsa-agent-es}
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: ${VSA_ES_JAVA_OPTS:--Xms512m -Xmx512m}
    ports:
      - "${VSA_ES_PORT:-9200}:9200"
    volumes:
      - ${VSA_ES_DATA_DIR:-./.runtime/elasticsearch}:/usr/share/elasticsearch/data
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:9200 >/dev/null || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12
```

- [ ] **Step 2: Add start script**

Create `scripts/es-dev-start.ps1`:

```powershell
param(
    [int]$Port = 9200,
    [string]$DataDir = ".runtime\elasticsearch",
    [string]$ContainerName = "vsa-agent-es"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$env:VSA_ES_PORT = "$Port"
$env:VSA_ES_DATA_DIR = $DataDir
$env:VSA_ES_CONTAINER_NAME = $ContainerName
docker compose -f docker-compose.es.yml up -d
& "$PSScriptRoot\es-dev-probe.ps1" -Endpoint "http://127.0.0.1:$Port"
```

- [ ] **Step 3: Add stop script**

Create `scripts/es-dev-stop.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
docker compose -f docker-compose.es.yml down
```

- [ ] **Step 4: Add probe script**

Create `scripts/es-dev-probe.ps1`:

```powershell
param(
    [string]$Endpoint = "http://127.0.0.1:9200",
    [int]$TimeoutSec = 90
)

$ErrorActionPreference = "Stop"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
do {
    try {
        $response = Invoke-RestMethod -Uri $Endpoint -TimeoutSec 5
        if ($response.cluster_name) {
            Write-Host "PASS: Elasticsearch is reachable at $Endpoint"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "Elasticsearch did not become reachable at $Endpoint within $TimeoutSec seconds"
```

- [ ] **Step 5: Add runtime documentation**

Create `docs/superpowers/reference/es-video-search-runtime.md` with:

```markdown
# ES Video Search Runtime

This runtime is for development validation of video segment index records. It does not store video bytes and does not reproduce the original VSS Kafka/Logstash pipeline.

## Local Start

```powershell
.\scripts\es-dev-start.ps1 -Port 9200
```

## Probe

```powershell
.\scripts\es-dev-probe.ps1 -Endpoint http://127.0.0.1:9200
```

## Stop

```powershell
.\scripts\es-dev-stop.ps1
```

## Ingest And Search Validation

Start the API with `search.enabled=true`, `search.es_endpoint=http://127.0.0.1:9200`, `search.embed_index=vsa-video-embeddings`, and `search.verify_certs=false` in a local override. Then run:

```powershell
python scripts\es_ingest_smoke.py --api-url http://127.0.0.1:8000 --es-endpoint http://127.0.0.1:9200 --insecure
```

## Mapped Server Copy

`Z:\vsa-agent` is the mapped server project copy. After local commits, sync the changed files there. If commands cannot execute through the mapped drive, validation is blocked until a server shell is available; the scripts are still copied so the server can run the same commands.
```

- [ ] **Step 6: Run static checks for scripts/docs**

Run:

```powershell
Test-Path docker-compose.es.yml
Test-Path scripts\es-dev-start.ps1
Test-Path scripts\es-dev-stop.ps1
Test-Path scripts\es-dev-probe.ps1
Test-Path docs\superpowers\reference\es-video-search-runtime.md
```

Expected: all commands print `True`.

- [ ] **Step 7: Commit ES runtime scripts**

```powershell
git add docker-compose.es.yml scripts/es-dev-start.ps1 scripts/es-dev-stop.ps1 scripts/es-dev-probe.ps1 docs/superpowers/reference/es-video-search-runtime.md
git commit -m "chore: add scriptable es development runtime"
```

## Task 6: Local Verification, Server Sync, And Comet Closeout Prep

**Files:**
- Modify: `openspec/changes/wire-es-search-retrieval/tasks.md`
- May modify: verification notes under `docs/superpowers/reports/`
- Sync target: `Z:\vsa-agent`

**Interfaces:**
- Consumes: completed Tasks 1-5.
- Produces: checked tasks, local verification evidence, synced server project copy.

- [ ] **Step 1: Run focused local verification**

Run:

```powershell
pytest tests/unit/tools/test_embed_search.py tests/unit/api/test_video_search_ingest.py tests/unit/scripts/test_es_ingest_smoke.py -q
```

Expected: PASS.

- [ ] **Step 2: Run OpenSpec validation**

Run:

```powershell
npx openspec validate wire-es-search-retrieval
```

Expected: PASS.

- [ ] **Step 3: Optionally run ES probe if Docker is available**

Run:

```powershell
.\scripts\es-dev-start.ps1 -Port 9200
.\scripts\es-dev-probe.ps1 -Endpoint http://127.0.0.1:9200
.\scripts\es-dev-stop.ps1
```

Expected: PASS if Docker Desktop/Compose can run. If Docker is unavailable, record the exact blocker in the verification report and continue with unit/OpenSpec evidence.

- [ ] **Step 4: Sync changed files to `Z:\vsa-agent`**

Use a safe copy command that preserves paths for changed files only. Example:

```powershell
robocopy D:\WorkPlace\vsa-agent Z:\vsa-agent docker-compose.es.yml
robocopy D:\WorkPlace\vsa-agent\scripts Z:\vsa-agent\scripts es_ingest_smoke.py es-dev-start.ps1 es-dev-stop.ps1 es-dev-probe.ps1
robocopy D:\WorkPlace\vsa-agent\src Z:\vsa-agent\src /E
robocopy D:\WorkPlace\vsa-agent\tests Z:\vsa-agent\tests /E
robocopy D:\WorkPlace\vsa-agent\docs Z:\vsa-agent\docs /E
robocopy D:\WorkPlace\vsa-agent\openspec Z:\vsa-agent\openspec /E
```

After running `robocopy`, treat exit codes `0` through `7` as success and `8` or above as failure.

- [ ] **Step 5: Attempt mapped-server validation**

If the mapped drive supports command execution from this machine, run:

```powershell
Push-Location Z:\vsa-agent
pytest tests/unit/tools/test_embed_search.py tests/unit/api/test_video_search_ingest.py tests/unit/scripts/test_es_ingest_smoke.py -q
Pop-Location
```

Expected: PASS. If `Z:\` is only file mapping and cannot execute server-side dependencies, record that as the blocker.

- [ ] **Step 6: Check off OpenSpec tasks**

Update `openspec/changes/wire-es-search-retrieval/tasks.md` so completed tasks are checked. Do not check a task whose verification was blocked; instead add a short note below it.

- [ ] **Step 7: Commit verification/task updates**

```powershell
git add openspec/changes/wire-es-search-retrieval/tasks.md docs/superpowers/reports
git commit -m "chore: record es retrieval verification"
```

- [ ] **Step 8: Run Comet build guard**

Run:

```powershell
D:\working\Git\bin\bash.exe -lc 'source .agents/skills/comet/scripts/comet-env.sh && "$COMET_GUARD" wire-es-search-retrieval build --apply'
```

Expected: PASS and `.comet.yaml` moves to `phase: verify`.

## Self-Review

- Spec coverage: Tasks 1-3 cover ES video segment retrieval and ingest contract; Task 4 covers ingest-then-search validation; Task 5 covers scriptable single-node ES runtime; Task 6 covers local verification, OpenSpec validation, and `Z:\vsa-agent` sync.
- Placeholder scan: no task uses TBD/TODO/later. Each code change has exact file path, sample implementation, command, expected result, and commit message.
- Type consistency: plan uses existing `SearchBackendConfig`, `SearchOutput`, `SearchResult`, `_search_real_es`, `_build_ingest_document`, and `AsyncElasticsearch` interfaces from the current codebase.
