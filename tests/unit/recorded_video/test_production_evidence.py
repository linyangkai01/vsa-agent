from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object | None = None,
        *,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload) if payload is not None else ""

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("response has no JSON")
        return self._payload


class BusinessFlowClient:
    def __init__(self, data_root: Path, records: dict[str, dict[str, object]]) -> None:
        self.data_root = data_root
        self.records = records
        self.deleted: set[str] = set()
        self.requests: list[tuple[str, str]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append(("POST", url))
        if url.endswith("/_refresh"):
            return FakeResponse(200, {"_shards": {"failed": 0}})
        if url.endswith("/_search"):
            query = kwargs["json"]
            filters = query.get("query", {}).get("bool", {}).get("filter", [])
            if filters:
                terms = {next(iter(item["term"])): next(iter(item["term"].values())) for item in filters}
                asset_id = terms["asset_id"]
                record = self.records[asset_id]
                return FakeResponse(
                    200,
                    {
                        "hits": {
                            "hits": []
                            if asset_id in self.deleted
                            else [{"_id": record["segment_id"], "_source": record}]
                        }
                    },
                )
            asset_id = query["query"]["term"]["asset_id"]
            return FakeResponse(200, {"hits": {"hits": [] if asset_id in self.deleted else [{}]}})
        if url.endswith("/api/v1/search"):
            query = kwargs["json"]["query"]
            matches = [
                {
                    **record,
                    "similarity": 0.91,
                }
                for record in self.records.values()
                if record["query"] == query and record["asset_id"] not in self.deleted
            ]
            return FakeResponse(200, {"data": matches})
        if url.endswith("/api/chat"):
            body = kwargs["json"]
            assert body["chatCompletionURL"] == "http://127.0.0.1:8000/chat/stream"
            assert "[Context:" in body["messages"][0]["content"]
            return FakeResponse(
                200, content=b"answer", text="选中片段显示叉车靠近工作人员，存在碰撞风险，需要保持安全距离。"
            )
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append(("GET", url))
        asset_id = next((value for value in self.records if value in url), None)
        assert asset_id is not None, url
        if asset_id in self.deleted:
            return FakeResponse(404)
        if url.endswith("/thumbnail"):
            return FakeResponse(200, content=b"jpeg")
        if kwargs.get("headers") == {"Range": "bytes=0-0"}:
            return FakeResponse(
                206,
                content=b"0",
                headers={"Accept-Ranges": "bytes", "Content-Range": "bytes 0-0/100"},
            )
        raise AssertionError(f"unexpected GET {url}")

    def delete(self, url: str, **_kwargs: object) -> FakeResponse:
        self.requests.append(("DELETE", url))
        asset_id = next(value for value in self.records if value in url)
        if asset_id not in self.deleted:
            record = self.records[asset_id]
            with sqlite3.connect(self.data_root / "recorded-video.sqlite3") as connection:
                connection.execute("DELETE FROM job_steps WHERE job_id = ?", (record["job_id"],))
                connection.execute("DELETE FROM jobs WHERE job_id = ?", (record["job_id"],))
                connection.execute("DELETE FROM segments WHERE asset_id = ?", (asset_id,))
                connection.execute(
                    "UPDATE assets SET status = 'deleted', deleted_at = '2026-07-21T00:00:00+00:00' WHERE asset_id = ?",
                    (asset_id,),
                )
            shutil.rmtree(self.data_root / "assets" / asset_id)
            self.deleted.add(asset_id)
        return FakeResponse(204)


def _database(data_root: Path, records: dict[str, dict[str, object]]) -> None:
    data_root.mkdir()
    with sqlite3.connect(data_root / "recorded-video.sqlite3") as connection:
        connection.executescript(
            """
            CREATE TABLE assets (asset_id TEXT PRIMARY KEY, status TEXT, deleted_at TEXT);
            CREATE TABLE jobs (job_id TEXT PRIMARY KEY, asset_id TEXT, status TEXT, stage TEXT, attempt INTEGER);
            CREATE TABLE job_steps (
                job_id TEXT, stage TEXT, status TEXT, output_manifest TEXT,
                output_checksum TEXT, model TEXT, elapsed_ms INTEGER
            );
            CREATE TABLE segments (segment_id TEXT PRIMARY KEY, asset_id TEXT, ordinal INTEGER);
            """
        )
        for record in records.values():
            asset_id = record["asset_id"]
            job_id = record["job_id"]
            asset_dir = data_root / "assets" / str(asset_id)
            manifest_relative = "derived/v1/attempts/1/manifest.json"
            manifest_path = asset_dir / manifest_relative
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "checkpoint_identity": {
                            "vision": {
                                "provider": "vsa_agent.recorded_video.providers.OpenAIVisionProvider",
                                "model": "vlm-real",
                            },
                            "embedding": {
                                "provider": "vsa_agent.recorded_video.providers.OpenAIEmbeddingProvider",
                                "model": "embed-real",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            connection.execute("INSERT INTO assets VALUES (?, 'ready', NULL)", (asset_id,))
            connection.execute("INSERT INTO jobs VALUES (?, ?, 'completed', 'publish', 2)", (job_id, asset_id))
            connection.executemany(
                "INSERT INTO job_steps VALUES (?, ?, 'completed', ?, ?, ?, 10)",
                [
                    (job_id, "probing", manifest_relative, f"sha-probe-{asset_id}", "ffprobe"),
                    (job_id, "segmenting", manifest_relative, f"sha-segment-{asset_id}", None),
                    (job_id, "extracting", manifest_relative, f"sha-extract-{asset_id}", "ffmpeg"),
                    (job_id, "analyzing", manifest_relative, f"sha-analysis-{asset_id}", "vlm-real"),
                    (job_id, "embedding", manifest_relative, f"sha-embedding-{asset_id}", "embed-real"),
                    (job_id, "indexing", manifest_relative, f"sha-index-{asset_id}", None),
                    (job_id, "publish", manifest_relative, f"sha-publish-{asset_id}", None),
                ],
            )
            connection.execute(
                "INSERT INTO segments VALUES (?, ?, 0)",
                (record["segment_id"], asset_id),
            )
            (asset_dir / "source.mp4").write_bytes(b"video")


def _records() -> dict[str, dict[str, object]]:
    return {
        f"asset-{index}": {
            "asset_id": f"asset-{index}",
            "job_id": f"job-{index}",
            "segment_id": f"segment-{index}",
            "sensor_id": f"asset-{index}",
            "video_name": f"video-{index}.mp4",
            "description": f"description-{index}",
            "start_time": "2026-07-21T00:00:00Z",
            "end_time": "2026-07-21T00:00:05Z",
            "screenshot_url": f"/api/v1/videos/asset-{index}/segments/segment-{index}/thumbnail",
            "query": f"query-{index}",
        }
        for index in range(3)
    }


def test_collect_business_evidence_covers_three_assets_and_cleanup(tmp_path: Path) -> None:
    from vsa_agent.recorded_video.production_acceptance import AcceptanceCase, JobIdentity
    from vsa_agent.recorded_video.production_evidence import RuntimeEvidence, collect_business_evidence

    records = _records()
    data_root = tmp_path / "video-data"
    _database(data_root, records)
    cases = []
    jobs = []
    for index, record in enumerate(records.values()):
        path = tmp_path / str(record["video_name"])
        path.write_bytes(bytes([index]))
        cases.append(AcceptanceCase(path=path, query=str(record["query"]), sha256=str(index)))
        jobs.append(JobIdentity(str(record["asset_id"]), str(record["job_id"]), f"/api/v1/jobs/job-{index}"))
    runtime = RuntimeEvidence(
        es_endpoint="http://127.0.0.1:9200",
        index="vsa-video-embeddings",
        vision_provider="openai_compatible",
        vision_model="vlm-real",
        embedding_provider="openai_compatible",
        embedding_model="embed-real",
    )
    client = BusinessFlowClient(data_root, records)

    evidence = collect_business_evidence(
        client,
        ui_url="http://127.0.0.1:3000",
        api_url="http://127.0.0.1:8000",
        runtime=runtime,
        data_root=data_root,
        cases=tuple(cases),
        jobs=tuple(jobs),
        minimum_similarity=0.2,
        timeout=1.0,
        poll_interval=0.01,
    )

    assert len(evidence.cases) == 3
    assert evidence.document_count == 3
    assert evidence.segment_ids == ("segment-0", "segment-1", "segment-2")
    assert all(case.content_range == "bytes 0-0/100" for case in evidence.cases)
    assert all("叉车" in case.answer_excerpt for case in evidence.cases)
    assert client.deleted == set(records)
    assert all(not (data_root / "assets" / asset_id).exists() for asset_id in records)
    assert sum(method == "DELETE" for method, _url in client.requests) == 6


def test_render_acceptance_report_records_two_runs_and_all_case_evidence(tmp_path: Path) -> None:
    from vsa_agent.recorded_video.production_acceptance import RunHandle
    from vsa_agent.recorded_video.production_evidence import (
        AcceptanceEvidence,
        BusinessEvidence,
        CaseEvidence,
        RuntimeEvidence,
        render_acceptance_report,
    )

    runtime = RuntimeEvidence(
        es_endpoint="http://127.0.0.1:9200",
        index="vsa-video-embeddings",
        vision_provider="openai_compatible",
        vision_model="vlm-real",
        embedding_provider="openai_compatible",
        embedding_model="embed-real",
    )
    cases = tuple(
        CaseEvidence(
            asset_id=f"asset-{index}",
            job_id=f"job-{index}",
            segment_ids=(f"segment-{index}",),
            query=f"query-{index}",
            similarity=0.9,
            screenshot_url=f"/thumbnail-{index}",
            content_range="bytes 0-0/100",
            cleanup_path=Path(f"/data/video/assets/asset-{index}"),
        )
        for index in range(3)
    )
    business = BusinessEvidence(cases=cases, document_count=3, segment_ids=tuple(f"segment-{i}" for i in range(3)))
    run_ids = (
        "123e4567-e89b-42d3-a456-426614174001",
        "123e4567-e89b-42d3-a456-426614174002",
    )
    handles = []
    for run_id in run_ids:
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "stack.log").write_text(f"run_id={run_id}\n", encoding="utf-8")
        (run_dir / "processes.json").write_text(json.dumps({"run_id": run_id, "processes": []}), encoding="utf-8")
        handles.append(RunHandle(run_id, run_dir, 100, run_dir / "launcher.log"))
    evidence = AcceptanceEvidence(
        acceptance_id="123e4567-e89b-42d3-a456-426614174099",
        launcher_runs=tuple(handles),
        runtime=runtime,
        business=business,
        timestamp_utc="2026-07-21T00:00:00Z",
        secret_scan="PASS (无密钥)",
    )
    report = tmp_path / "report.md"

    render_acceptance_report(evidence, report)

    content = report.read_text(encoding="utf-8")
    case_path = report.with_suffix(".cases.json")
    assert "- 总体结果：PASS" in content
    assert f"- launcher_runs: {run_ids[0]},{run_ids[1]}" in content
    assert "- concurrency: 3" in content
    assert "- worker_restart: PASS" in content
    assert "- asset_ids: asset-0,asset-1,asset-2" in content
    assert f"- case_evidence_ref: {case_path}" in content
    assert len(json.loads(case_path.read_text(encoding="utf-8"))["cases"]) == 3


def test_scan_runtime_logs_requires_video_understanding_trace_for_each_asset(tmp_path: Path) -> None:
    from vsa_agent.recorded_video.production_acceptance import RunHandle, ValidationError
    from vsa_agent.recorded_video.production_evidence import BusinessEvidence, CaseEvidence, scan_runtime_logs

    handles = []
    for index, run_id in enumerate(
        (
            "123e4567-e89b-42d3-a456-426614174001",
            "123e4567-e89b-42d3-a456-426614174002",
        )
    ):
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "stack.log").write_text(f"run_id={run_id}\n", encoding="utf-8")
        handles.append(RunHandle(run_id, run_dir, 100 + index))
    cases = tuple(
        CaseEvidence(
            asset_id=f"asset-{index}",
            job_id=f"job-{index}",
            segment_ids=(f"segment-{index}",),
            query=f"query-{index}",
            similarity=0.9,
            screenshot_url="/thumbnail",
            content_range="bytes 0-0/100",
            cleanup_path=tmp_path / f"asset-{index}",
            answer_excerpt="A sufficiently detailed selected-video answer.",
        )
        for index in range(3)
    )
    trace_root = handles[-1].run_dir / "chat-traces"
    for index, case in enumerate(cases):
        trace_dir = trace_root / f"trace-{index}"
        trace_dir.mkdir(parents=True)
        (trace_dir / "request.json").write_text(
            json.dumps({"selected_asset_id": case.asset_id, "selected_segment_id": case.segment_ids[0]}),
            encoding="utf-8",
        )
        events = ("original_ui.chat.request", "video_understanding.result")
        (trace_dir / "trace.jsonl").write_text(
            "".join(json.dumps({"event_type": event}) + "\n" for event in events),
            encoding="utf-8",
        )
    business = BusinessEvidence(cases=cases, document_count=3, segment_ids=tuple(f"segment-{i}" for i in range(3)))

    assert scan_runtime_logs(handles, business) == "PASS (无密钥)"

    (trace_root / "trace-2" / "trace.jsonl").write_text(
        json.dumps({"event_type": "original_ui.chat.request"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="does not prove video understanding"):
        scan_runtime_logs(handles, business)
