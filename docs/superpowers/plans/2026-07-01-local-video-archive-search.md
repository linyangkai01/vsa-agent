# Local Video Archive Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local recorded-video archive search loop that ingests real live-video run artifacts and lets `search_agent` search them without NVIDIA services or Elasticsearch.

**Architecture:** Add a focused `vsa_agent.archive` package for archive records, JSONL persistence, artifact ingest, and deterministic local text search. Keep the public agent contract unchanged by returning existing `SearchOutput` / `SearchResult` objects and using dependency injection or registry wiring around `search_agent`.

**Tech Stack:** Python 3.11+, Pydantic, stdlib `json` / `pathlib`, pytest, existing `vsa_agent` CLI and search agent models.

## Global Constraints

- Do not introduce Elasticsearch, Milvus, LanceDB, or another persistent vector database in this phase.
- Do not call live LLM/VLM APIs during archive ingest or search.
- Do not re-run video understanding during archive ingest.
- Do not redesign `SearchResult`, `SearchOutput`, or the existing search agent contract.
- Archive ingest/search must work with no live API key.
- Existing live video acceptance and validator behavior must remain unchanged.

---

## File Structure

- Create `src/vsa_agent/archive/__init__.py`: public exports for archive functions/classes.
- Create `src/vsa_agent/archive/models.py`: `ArchiveRecord` Pydantic model and conversion to `SearchResult`.
- Create `src/vsa_agent/archive/index.py`: JSONL read/upsert/write helpers.
- Create `src/vsa_agent/archive/ingest.py`: live run artifact parser and ingest API.
- Create `src/vsa_agent/archive/search.py`: deterministic local archive search store.
- Modify `src/vsa_agent/__main__.py`: add `archive ingest` and `archive search` CLI subcommands.
- Modify `tests/acceptance/test_search_archive_flow.py`: replace the injected fake search with a real archive ingest/search acceptance.
- Create `tests/unit/archive/test_ingest.py`: artifact parsing and ingest behavior.
- Create `tests/unit/archive/test_index.py`: JSONL idempotent upsert behavior.
- Create `tests/unit/archive/test_search.py`: search scorer behavior.
- Create `tests/unit/test_archive_cli.py`: CLI command behavior.
- Modify `docs/testing/live-api-validation.md`: add the local archive ingest/search smoke commands.

---

### Task 1: Archive Record Model

**Files:**
- Create: `src/vsa_agent/archive/__init__.py`
- Create: `src/vsa_agent/archive/models.py`
- Test: `tests/unit/archive/test_models.py`

**Interfaces:**
- Produces: `ArchiveRecord(BaseModel)`
- Produces: `ArchiveRecord.to_search_result() -> SearchResult`
- Produces: `build_record_id(run_id: str, video_path: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/archive/test_models.py`:

```python
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id
from vsa_agent.tools.search import SearchResult


def test_archive_record_converts_to_search_result():
    record = ArchiveRecord(
        record_id="run-123",
        video_name="warehouse.mp4",
        video_path="/data/video/warehouse.mp4",
        description="worker walking near forklift",
        search_text="worker walking near forklift loading dock",
        start_time="2026-07-01T10:00:00",
        end_time="2026-07-01T10:01:00",
        sensor_id="warehouse",
        screenshot_url="",
        object_ids=["worker", "forklift"],
        metadata={"mode": "graph"},
    )

    result = record.to_search_result(similarity=0.87)

    assert isinstance(result, SearchResult)
    assert result.video_name == "warehouse.mp4"
    assert result.description == "worker walking near forklift"
    assert result.start_time == "2026-07-01T10:00:00"
    assert result.end_time == "2026-07-01T10:01:00"
    assert result.sensor_id == "warehouse"
    assert result.similarity == 0.87
    assert result.object_ids == ["worker", "forklift"]


def test_build_record_id_prefers_run_id_and_is_stable():
    assert build_record_id("20260701-102652", "/data/video/a.mp4") == "20260701-102652"
    assert build_record_id("", "/data/video/a.mp4") == "a.mp4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/archive/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'vsa_agent.archive'`.

- [ ] **Step 3: Implement the model**

Create `src/vsa_agent/archive/__init__.py`:

```python
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id

__all__ = ["ArchiveRecord", "build_record_id"]
```

Create `src/vsa_agent/archive/models.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.tools.search import SearchResult


def build_record_id(run_id: str, video_path: str) -> str:
    if run_id.strip():
        return run_id.strip()
    name = Path(video_path).name
    return name or "unknown-video"


class ArchiveRecord(BaseModel):
    record_id: str = Field(description="Stable archive record identifier")
    video_name: str = Field(description="Video filename")
    video_path: str = Field(default="", description="Original local video path")
    description: str = Field(default="", description="Concise searchable description")
    search_text: str = Field(default="", description="Concatenated text used for local search")
    start_time: str = Field(default="", description="Run/video start timestamp")
    end_time: str = Field(default="", description="Run/video end timestamp")
    sensor_id: str = Field(default="", description="Sensor or video source identifier")
    screenshot_url: str = Field(default="", description="Optional preview image URL/path")
    object_ids: list[str] = Field(default_factory=list, description="Lightweight extracted tags")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source run metadata")

    def to_search_result(self, similarity: float) -> SearchResult:
        return SearchResult(
            video_name=self.video_name,
            description=self.description,
            start_time=self.start_time,
            end_time=self.end_time,
            sensor_id=self.sensor_id,
            screenshot_url=self.screenshot_url,
            similarity=max(0.0, min(1.0, float(similarity))),
            object_ids=list(self.object_ids),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/archive/test_models.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/vsa_agent/archive/__init__.py src/vsa_agent/archive/models.py tests/unit/archive/test_models.py
git commit -m "feat: add local archive record model"
```

---

### Task 2: JSONL Archive Index

**Files:**
- Create: `src/vsa_agent/archive/index.py`
- Test: `tests/unit/archive/test_index.py`

**Interfaces:**
- Consumes: `ArchiveRecord`
- Produces: `read_archive_index(index_path: str | Path) -> list[ArchiveRecord]`
- Produces: `upsert_archive_records(index_path: str | Path, records: Iterable[ArchiveRecord]) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/archive/test_index.py`:

```python
from pathlib import Path

from vsa_agent.archive.index import read_archive_index
from vsa_agent.archive.index import upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord


def _record(record_id: str, description: str) -> ArchiveRecord:
    return ArchiveRecord(
        record_id=record_id,
        video_name=f"{record_id}.mp4",
        video_path=f"/data/{record_id}.mp4",
        description=description,
        search_text=description,
        start_time="",
        end_time="",
        sensor_id=record_id,
    )


def test_upsert_archive_records_replaces_duplicate_record_id(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"

    written = upsert_archive_records(index_path, [_record("run-1", "old forklift")])
    rewritten = upsert_archive_records(index_path, [_record("run-1", "new forklift")])
    records = read_archive_index(index_path)

    assert written == 1
    assert rewritten == 1
    assert len(records) == 1
    assert records[0].description == "new forklift"


def test_read_archive_index_skips_invalid_jsonl_lines(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        '{"record_id":"run-1","video_name":"a.mp4","description":"person","search_text":"person"}\n'
        'not-json\n',
        encoding="utf-8",
    )

    records = read_archive_index(index_path)

    assert len(records) == 1
    assert records[0].record_id == "run-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/archive/test_index.py -q`

Expected: FAIL with import error for `vsa_agent.archive.index`.

- [ ] **Step 3: Implement JSONL persistence**

Create `src/vsa_agent/archive/index.py`:

```python
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from vsa_agent.archive.models import ArchiveRecord

logger = logging.getLogger(__name__)


def read_archive_index(index_path: str | Path) -> list[ArchiveRecord]:
    path = Path(index_path)
    if not path.exists():
        return []

    records: list[ArchiveRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ArchiveRecord.model_validate(json.loads(line)))
        except Exception as exc:
            logger.warning("Skipping invalid archive index line %s in %s: %s", line_number, path, exc)
    return records


def upsert_archive_records(index_path: str | Path, records: Iterable[ArchiveRecord]) -> int:
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = {record.record_id: record for record in read_archive_index(path)}
    incoming = list(records)
    for record in incoming:
        merged[record.record_id] = record

    ordered = sorted(merged.values(), key=lambda item: item.record_id)
    payload = "\n".join(record.model_dump_json() for record in ordered)
    path.write_text(f"{payload}\n" if payload else "", encoding="utf-8")
    return len(incoming)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/archive/test_index.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/vsa_agent/archive/index.py tests/unit/archive/test_index.py
git commit -m "feat: add local archive jsonl index"
```

---

### Task 3: Live Run Artifact Ingest

**Files:**
- Create: `src/vsa_agent/archive/ingest.py`
- Modify: `src/vsa_agent/archive/__init__.py`
- Test: `tests/unit/archive/test_ingest.py`

**Interfaces:**
- Consumes: `ArchiveRecord`, `upsert_archive_records`
- Produces: `build_record_from_live_run(run_dir: str | Path) -> ArchiveRecord`
- Produces: `ingest_live_run(run_dir: str | Path, index_path: str | Path) -> ArchiveRecord`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/archive/test_ingest.py`:

```python
import json
from pathlib import Path

import pytest

from vsa_agent.archive.index import read_archive_index
from vsa_agent.archive.ingest import build_record_from_live_run
from vsa_agent.archive.ingest import ingest_live_run


def _write_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260701-102652",
                "video_path": "/data/project/lyk/video/1597042367-1-192.mp4",
                "mode": "graph",
                "llm_model": "qwen3.7-plus",
                "vlm_model": "qwen3-vl-flash-2025-10-15",
                "started_at": "2026-07-01T10:26:52",
                "ended_at": "2026-07-01T10:28:51",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text(
        "A worker walks near a forklift in a warehouse loading area. Safety risk: pedestrian and vehicle proximity.",
        encoding="utf-8",
    )
    (run_dir / "report-final.txt").write_text(
        "# Inspection Report\n\nForklift traffic and pedestrian movement overlap near the loading dock.",
        encoding="utf-8",
    )


def test_build_record_from_live_run_extracts_searchable_fields(tmp_path: Path):
    run_dir = tmp_path / "20260701-102652"
    _write_run(run_dir)

    record = build_record_from_live_run(run_dir)

    assert record.record_id == "20260701-102652"
    assert record.video_name == "1597042367-1-192.mp4"
    assert record.sensor_id == "1597042367-1-192"
    assert "worker walks near a forklift" in record.description
    assert "Inspection Report" in record.search_text
    assert "forklift" in record.object_ids
    assert record.metadata["mode"] == "graph"
    assert record.metadata["qa_status"] == "success"
    assert record.metadata["report_status"] == "success"


def test_ingest_live_run_writes_archive_index(tmp_path: Path):
    run_dir = tmp_path / "20260701-102652"
    index_path = tmp_path / "archive" / "index.jsonl"
    _write_run(run_dir)

    record = ingest_live_run(run_dir, index_path)
    records = read_archive_index(index_path)

    assert record.record_id == "20260701-102652"
    assert [item.record_id for item in records] == ["20260701-102652"]


def test_build_record_from_live_run_requires_manifest(tmp_path: Path):
    run_dir = tmp_path / "missing-manifest"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="manifest.json"):
        build_record_from_live_run(run_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/archive/test_ingest.py -q`

Expected: FAIL with import error for `vsa_agent.archive.ingest`.

- [ ] **Step 3: Implement artifact ingest**

Create `src/vsa_agent/archive/ingest.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path

from vsa_agent.archive.index import upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id

KNOWN_TAGS = (
    "person",
    "worker",
    "pedestrian",
    "forklift",
    "vehicle",
    "truck",
    "safety",
    "loading",
    "warehouse",
)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Required manifest.json not found in live run directory: {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _first_sentence(text: str, fallback: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return fallback
    parts = re.split(r"(?<=[.!?。！？])\s+", compact)
    return parts[0][:500]


def _extract_tags(text: str) -> list[str]:
    lowered = text.lower()
    return [tag for tag in KNOWN_TAGS if tag in lowered]


def build_record_from_live_run(run_dir: str | Path) -> ArchiveRecord:
    path = Path(run_dir)
    manifest = _load_manifest(path)
    qa_text = _read_text(path / "qa-final.txt")
    report_text = _read_text(path / "report-final.txt")

    video_path = str(manifest.get("video_path", ""))
    video_name = Path(video_path).name or "unknown-video"
    sensor_id = Path(video_name).stem or video_name
    run_id = str(manifest.get("run_id") or path.name)
    search_text = "\n\n".join(part for part in [qa_text, report_text, json.dumps(manifest, ensure_ascii=False)] if part)

    return ArchiveRecord(
        record_id=build_record_id(run_id, video_path),
        video_name=video_name,
        video_path=video_path,
        description=_first_sentence(qa_text or report_text, fallback=video_name),
        search_text=search_text,
        start_time=str(manifest.get("started_at", "")),
        end_time=str(manifest.get("ended_at", "")),
        sensor_id=sensor_id,
        screenshot_url="",
        object_ids=_extract_tags(search_text),
        metadata={
            "run_dir": str(path),
            "mode": manifest.get("mode", ""),
            "llm_model": manifest.get("llm_model", ""),
            "vlm_model": manifest.get("vlm_model", ""),
            "qa_status": (manifest.get("qa") or {}).get("status", ""),
            "report_status": (manifest.get("report") or {}).get("status", ""),
            "manifest_path": str(path / "manifest.json"),
            "qa_path": str(path / "qa-final.txt") if (path / "qa-final.txt").exists() else "",
            "report_path": str(path / "report-final.txt") if (path / "report-final.txt").exists() else "",
        },
    )


def ingest_live_run(run_dir: str | Path, index_path: str | Path) -> ArchiveRecord:
    record = build_record_from_live_run(run_dir)
    upsert_archive_records(index_path, [record])
    return record
```

Modify `src/vsa_agent/archive/__init__.py`:

```python
from vsa_agent.archive.ingest import build_record_from_live_run
from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id

__all__ = [
    "ArchiveRecord",
    "build_record_from_live_run",
    "build_record_id",
    "ingest_live_run",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/archive/test_ingest.py tests/unit/archive/test_index.py tests/unit/archive/test_models.py -q`

Expected: PASS with `7 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/vsa_agent/archive/__init__.py src/vsa_agent/archive/ingest.py tests/unit/archive/test_ingest.py
git commit -m "feat: ingest live video runs into local archive"
```

---

### Task 4: Deterministic Local Archive Search

**Files:**
- Create: `src/vsa_agent/archive/search.py`
- Modify: `src/vsa_agent/archive/__init__.py`
- Test: `tests/unit/archive/test_search.py`

**Interfaces:**
- Consumes: `read_archive_index`, `ArchiveRecord.to_search_result`
- Produces: `LocalArchiveSearchStore(index_path: str | Path)`
- Produces: `LocalArchiveSearchStore.search(query: str, top_k: int = 10) -> SearchOutput`
- Produces: `LocalArchiveSearchStore.as_embed_search(query: str, top_k: int = 10) -> Callable[[], Awaitable[SearchOutput]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/archive/test_search.py`:

```python
from pathlib import Path

import pytest

from vsa_agent.archive.index import upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.search import LocalArchiveSearchStore


def _record(record_id: str, description: str, search_text: str) -> ArchiveRecord:
    return ArchiveRecord(
        record_id=record_id,
        video_name=f"{record_id}.mp4",
        video_path=f"/data/{record_id}.mp4",
        description=description,
        search_text=search_text,
        start_time="",
        end_time="",
        sensor_id=record_id,
    )


@pytest.mark.asyncio
async def test_local_archive_search_returns_ranked_matches(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(
        index_path,
        [
            _record("run-1", "worker near forklift", "worker near forklift loading dock safety risk"),
            _record("run-2", "empty hallway", "empty hallway no activity"),
        ],
    )
    store = LocalArchiveSearchStore(index_path)

    output = await store.search("forklift safety", top_k=5)

    assert len(output.data) == 1
    assert output.data[0].video_name == "run-1.mp4"
    assert output.data[0].similarity > 0


@pytest.mark.asyncio
async def test_local_archive_search_returns_empty_for_no_match(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(index_path, [_record("run-1", "worker near forklift", "worker near forklift")])
    store = LocalArchiveSearchStore(index_path)

    output = await store.search("ocean beach", top_k=5)

    assert output.data == []


@pytest.mark.asyncio
async def test_as_embed_search_returns_zero_arg_callable(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(index_path, [_record("run-1", "worker near forklift", "worker near forklift")])
    store = LocalArchiveSearchStore(index_path)

    callable_search = store.as_embed_search("forklift", top_k=1)
    output = await callable_search()

    assert output.data[0].video_name == "run-1.mp4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/archive/test_search.py -q`

Expected: FAIL with import error for `vsa_agent.archive.search`.

- [ ] **Step 3: Implement local text search**

Create `src/vsa_agent/archive/search.py`:

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable
from typing import Callable

from vsa_agent.archive.index import read_archive_index
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.tools.search import SearchOutput


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]+", text.lower()) if token}


def _score(query: str, record: ArchiveRecord) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0

    haystack = f"{record.description}\n{record.search_text}".lower()
    record_tokens = _tokens(haystack)
    overlap = query_tokens & record_tokens
    if not overlap:
        return 0.0

    token_score = len(overlap) / len(query_tokens)
    phrase_boost = 0.15 if query.lower().strip() in haystack else 0.0
    return min(1.0, token_score + phrase_boost)


class LocalArchiveSearchStore:
    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path)

    async def search(self, query: str, top_k: int = 10) -> SearchOutput:
        scored = [
            (score, record)
            for record in read_archive_index(self.index_path)
            if (score := _score(query, record)) > 0
        ]
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
        return SearchOutput(data=[record.to_search_result(similarity=score) for score, record in ranked])

    def as_embed_search(self, query: str, top_k: int = 10) -> Callable[[], Awaitable[SearchOutput]]:
        async def _search() -> SearchOutput:
            return await self.search(query=query, top_k=top_k)

        return _search
```

Modify `src/vsa_agent/archive/__init__.py`:

```python
from vsa_agent.archive.ingest import build_record_from_live_run
from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id
from vsa_agent.archive.search import LocalArchiveSearchStore

__all__ = [
    "ArchiveRecord",
    "LocalArchiveSearchStore",
    "build_record_from_live_run",
    "build_record_id",
    "ingest_live_run",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/archive/test_search.py tests/unit/archive/test_ingest.py tests/unit/archive/test_index.py tests/unit/archive/test_models.py -q`

Expected: PASS with `10 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/vsa_agent/archive/__init__.py src/vsa_agent/archive/search.py tests/unit/archive/test_search.py
git commit -m "feat: add deterministic local archive search"
```

---

### Task 5: Archive CLI Commands

**Files:**
- Modify: `src/vsa_agent/__main__.py`
- Test: `tests/unit/test_archive_cli.py`

**Interfaces:**
- Consumes: `ingest_live_run`, `LocalArchiveSearchStore`
- Produces CLI:
- `python -m vsa_agent archive ingest RUN_DIR --index artifacts/video-archive/index.jsonl`
- `python -m vsa_agent archive search QUERY --index artifacts/video-archive/index.jsonl --top-k 5`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_archive_cli.py`:

```python
import json
from pathlib import Path

from vsa_agent.__main__ import main


def _write_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-cli",
                "video_path": "/data/video/warehouse.mp4",
                "started_at": "2026-07-01T10:00:00",
                "ended_at": "2026-07-01T10:01:00",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text("worker near forklift", encoding="utf-8")


def test_archive_ingest_cli_writes_summary(tmp_path: Path, capsys):
    run_dir = tmp_path / "run-cli"
    index_path = tmp_path / "index.jsonl"
    _write_run(run_dir)

    exit_code = main(["archive", "ingest", str(run_dir), "--index", str(index_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["records_written"] == 1
    assert output["record_id"] == "run-cli"
    assert output["index_path"] == str(index_path)


def test_archive_search_cli_prints_search_output(tmp_path: Path, capsys):
    run_dir = tmp_path / "run-cli"
    index_path = tmp_path / "index.jsonl"
    _write_run(run_dir)
    assert main(["archive", "ingest", str(run_dir), "--index", str(index_path)]) == 0
    capsys.readouterr()

    exit_code = main(["archive", "search", "forklift", "--index", str(index_path), "--top-k", "3"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["data"][0]["video_name"] == "warehouse.mp4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_archive_cli.py -q`

Expected: FAIL because the `archive` command is not registered.

- [ ] **Step 3: Implement CLI commands**

Modify `src/vsa_agent/__main__.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.search import LocalArchiveSearchStore
from vsa_agent.config import AppConfig
from vsa_agent.config import resolve_runtime_config
from vsa_agent.config import validate_runtime_config
from vsa_agent.live_run_validator import format_validation_result
from vsa_agent.live_run_validator import validate_live_run


def _load_config(path: str) -> AppConfig:
    return AppConfig.from_yaml(path)


def _config_print(path: str) -> int:
    runtime = resolve_runtime_config(_load_config(path))
    print(json.dumps(runtime.model_dump_redacted(), ensure_ascii=False, indent=2))
    return 0


def _config_doctor(path: str) -> int:
    diagnostics = validate_runtime_config(_load_config(path))
    if diagnostics.ok:
        print("Config OK")
        return 0

    for issue in diagnostics.issues:
        print(f"{issue.severity.upper()}: {issue.message}")
    return 1


def _archive_ingest(run_dir: str, index_path: str) -> int:
    record = ingest_live_run(run_dir, index_path)
    print(json.dumps({"records_written": 1, "index_path": index_path, "record_id": record.record_id}, ensure_ascii=False))
    return 0


def _archive_search(query: str, index_path: str, top_k: int) -> int:
    async def _run() -> dict:
        output = await LocalArchiveSearchStore(index_path).search(query=query, top_k=top_k)
        return output.model_dump()

    print(json.dumps(asyncio.run(_run()), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vsa_agent")
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    print_parser = config_subparsers.add_parser("print")
    print_parser.add_argument("--config", default="config.yaml")

    doctor_parser = config_subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config", default="config.yaml")

    archive_parser = subparsers.add_parser("archive")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command")

    archive_ingest_parser = archive_subparsers.add_parser("ingest")
    archive_ingest_parser.add_argument("run_dir")
    archive_ingest_parser.add_argument("--index", default="artifacts/video-archive/index.jsonl")

    archive_search_parser = archive_subparsers.add_parser("search")
    archive_search_parser.add_argument("query")
    archive_search_parser.add_argument("--index", default="artifacts/video-archive/index.jsonl")
    archive_search_parser.add_argument("--top-k", type=int, default=5)

    validate_run_parser = subparsers.add_parser("validate-run")
    validate_run_parser.add_argument("run_dir")

    args = parser.parse_args(argv)
    if args.command == "config" and args.config_command == "print":
        return _config_print(args.config)
    if args.command == "config" and args.config_command == "doctor":
        return _config_doctor(args.config)
    if args.command == "archive" and args.archive_command == "ingest":
        return _archive_ingest(args.run_dir, args.index)
    if args.command == "archive" and args.archive_command == "search":
        return _archive_search(args.query, args.index, args.top_k)
    if args.command == "validate-run":
        result = validate_live_run(args.run_dir)
        print(format_validation_result(result))
        return 0 if result.ok else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_archive_cli.py tests/unit/archive -q`

Expected: PASS with all archive tests passing.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/vsa_agent/__main__.py tests/unit/test_archive_cli.py
git commit -m "feat: add local archive cli"
```

---

### Task 6: Search Agent Archive Acceptance

**Files:**
- Modify: `tests/acceptance/test_search_archive_flow.py`

**Interfaces:**
- Consumes: `ingest_live_run`, `LocalArchiveSearchStore.as_embed_search`
- Verifies: `execute_search_agent_flow` can use the local archive search store.

- [ ] **Step 1: Replace fake acceptance test with real archive flow**

Modify `tests/acceptance/test_search_archive_flow.py`:

```python
import json
from pathlib import Path

import pytest

from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.agents.search_agent import execute_search_agent_flow
from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.search import LocalArchiveSearchStore


def _write_live_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "warehouse-safety-demo",
                "video_path": "/data/project/lyk/video/warehouse-safety-demo.mp4",
                "mode": "graph",
                "llm_model": "qwen3.7-plus",
                "vlm_model": "qwen3-vl-flash-2025-10-15",
                "started_at": "2026-06-23T10:00:00",
                "ended_at": "2026-06-23T10:00:08",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text(
        "A worker is walking near a forklift in the warehouse loading area.",
        encoding="utf-8",
    )
    (run_dir / "report-final.txt").write_text(
        "Safety risk: pedestrian movement overlaps with forklift traffic near the dock.",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_local_archive_search_returns_matching_video_result(tmp_path: Path):
    run_dir = tmp_path / "warehouse-safety-demo"
    index_path = tmp_path / "archive" / "index.jsonl"
    _write_live_run(run_dir)
    ingest_live_run(run_dir, index_path)

    store = LocalArchiveSearchStore(index_path)
    query = "find a worker walking near a forklift"
    result = await execute_search_agent_flow(
        SearchAgentInput(
            query=query,
            agent_mode=False,
            use_critic=False,
            use_attribute_search=False,
        ),
        embed_search=store.as_embed_search(query, top_k=5),
    )

    assert result.search_output.data
    first = result.search_output.data[0]
    assert first.video_name == "warehouse-safety-demo.mp4"
    assert "forklift" in first.description.lower()
    assert first.start_time == "2026-06-23T10:00:00"
    assert first.end_time == "2026-06-23T10:00:08"
    assert first.sensor_id == "warehouse-safety-demo"
    assert first.similarity > 0
    assert "forklift" in first.object_ids
    assert result.incidents
    assert "forklift" in result.text_answer.lower()
```

- [ ] **Step 2: Run acceptance test**

Run: `python -m pytest tests/acceptance/test_search_archive_flow.py -q`

Expected: PASS with `1 passed`.

- [ ] **Step 3: Run targeted search regression**

Run:

```bash
python -m pytest tests/unit/archive tests/unit/test_archive_cli.py tests/acceptance/test_search_archive_flow.py tests/unit/agents/test_search_agent.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/acceptance/test_search_archive_flow.py
git commit -m "test: verify search agent over local archive"
```

---

### Task 7: Developer Docs and Final Verification

**Files:**
- Modify: `docs/testing/live-api-validation.md`

**Interfaces:**
- Documents local archive commands.
- Verifies no regression in archive/search/runtime config tests.

- [ ] **Step 1: Add local archive smoke commands to docs**

Append this section to `docs/testing/live-api-validation.md`:

```markdown
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
```

- [ ] **Step 2: Run final targeted verification**

Run:

```bash
python -m pytest tests/unit/archive tests/unit/test_archive_cli.py tests/acceptance/test_search_archive_flow.py tests/unit/agents/test_search_agent.py tests/unit/test_live_run_validator.py tests/unit/test_live_top_agent_video_runner.py -q
```

Expected: PASS.

- [ ] **Step 3: Validate OpenSpec still passes**

Run: `.\node_modules\.bin\openspec.cmd validate --all --strict`

Expected: PASS with all specs valid.

- [ ] **Step 4: Commit docs**

Run:

```bash
git add docs/testing/live-api-validation.md
git commit -m "docs: document local archive search smoke test"
```

- [ ] **Step 5: Push master for server pull**

Run:

```bash
git push origin master
```

Server update command:

```bash
cd /data/project/lyk/vsa-agent
git pull origin master
```

Server smoke commands:

```bash
cd /data/project/lyk/vsa-agent
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent archive ingest "$LATEST_RUN" --index artifacts/video-archive/index.jsonl
conda run -n vsa-agent python -m vsa_agent archive search "forklift safety risk" --index artifacts/video-archive/index.jsonl --top-k 5
```

---

## Self-Review

- Spec coverage: Tasks cover archive data model, JSONL persistence, live run ingest, deterministic search, CLI commands, search-agent acceptance, docs, and verification.
- Placeholder scan: No unfinished placeholder markers remain.
- Type consistency: `ArchiveRecord`, `SearchOutput`, `SearchResult`, `LocalArchiveSearchStore.search`, and `LocalArchiveSearchStore.as_embed_search` signatures are consistent across tasks.
- Scope check: The plan intentionally avoids vector database integration and live model calls, matching this phase's minimal archive-search closure.
