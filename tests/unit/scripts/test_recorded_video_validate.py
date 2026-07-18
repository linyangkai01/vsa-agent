"""Contract tests for the production recorded-video validator."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "recorded-video-validate.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recorded_video_validate", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_script()


class FakeClient:
    def __init__(
        self,
        data_root: Path,
        *,
        media_status: int = 206,
        upload_status: int = 200,
        es_status: int = 200,
        leave_orphan_steps: bool = False,
        retain_es_document: bool = False,
        duplicate_es_hit: bool = False,
        retain_asset_directory: bool = False,
        search_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.data_root = data_root
        self.media_status = media_status
        self.upload_status = upload_status
        self.es_status = es_status
        self.leave_orphan_steps = leave_orphan_steps
        self.retain_es_document = retain_es_document
        self.duplicate_es_hit = duplicate_es_hit
        self.retain_asset_directory = retain_asset_directory
        self.search_overrides = search_overrides or {}
        self.requests: list[tuple[str, str]] = []
        self.deleted = False

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(("GET", url))
        headers = kwargs.get("headers", {})
        if url == "http://api.test/health":
            return _response(200, {"status": "ok", "service": "vsa-agent"})
        if url == "http://ui.test/":
            return _response(200, text="<html>ui</html>")
        if url == "http://ui.test/api/v1/vst/v1/replay/streams":
            return _response(200, [])
        if url == "http://api.test/api/v1/jobs/job-1":
            return _response(
                200,
                {"asset_id": "asset-1", "job_id": "job-1", "status": "completed", "stage": "publish"},
            )
        if url == "http://api.test/thumb.jpg":
            return _response(200, content=b"jpeg")
        if url == "http://api.test/api/v1/vst/v1/storage/file/asset-1":
            if self.deleted:
                return _response(404, {"detail": "asset not found"})
            if headers.get("Range") == "bytes=0-0":
                response_headers = {
                    "Accept-Ranges": "bytes",
                    "Content-Range": "bytes 0-0/5",
                    "Content-Length": "1",
                }
                return _response(self.media_status, content=b"v", headers=response_headers)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **_kwargs: Any) -> httpx.Response:
        self.requests.append(("POST", url))
        if url == "http://es.test/validation-index/_refresh":
            return _response(self.es_status, {"_shards": {"failed": 0}})
        if url == "http://es.test/validation-index/_search":
            if self.es_status != 200:
                return _response(self.es_status, {"error": "unavailable"})
            hits = []
            if not self.deleted or self.retain_es_document:
                hits = [
                    {
                        "_id": "segment-1",
                        "_source": {
                            "asset_id": "asset-1",
                            "job_id": "job-1",
                            "segment_id": "segment-1",
                            "sensor_id": "asset-1",
                            "video_name": "validation.mp4",
                            "start_time": "2026-07-15T00:00:00Z",
                            "end_time": "2026-07-15T00:00:01Z",
                        },
                    }
                ]
                if self.duplicate_es_hit:
                    hits.append(dict(hits[0]))
            return _response(200, {"hits": {"total": {"value": len(hits)}, "hits": hits}})
        if url == "http://api.test/api/v1/videos":
            return _response(
                200,
                {
                    "asset_id": "asset-1",
                    "upload_session_id": "session-1",
                    "url": "/api/v1/vst/v1/storage/file?upload_session_id=session-1",
                },
            )
        if url.startswith("http://api.test/api/v1/vst/v1/storage/file?"):
            return _response(
                self.upload_status,
                {"sensorId": "asset-1", "streamId": "asset-1", "chunkCount": 1},
            )
        if url == "http://api.test/api/v1/videos/asset-1/complete":
            return _response(
                202,
                {
                    "asset_id": "asset-1",
                    "job_id": "job-1",
                    "status": "queued",
                    "status_url": "/api/v1/jobs/job-1",
                },
            )
        if url == "http://api.test/api/v1/search":
            if self.deleted:
                return _response(200, {"data": []})
            result = {
                "video_name": "validation.mp4",
                "description": "forklift near worker",
                "start_time": "2026-07-15T00:00:00Z",
                "end_time": "2026-07-15T00:00:01Z",
                "sensor_id": "asset-1",
                "screenshot_url": "/thumb.jpg",
                "similarity": 0.91,
            }
            result.update(self.search_overrides)
            return _response(
                200,
                {"data": [result]},
            )
        raise AssertionError(f"unexpected POST {url}")

    def delete(self, url: str, **_kwargs: Any) -> httpx.Response:
        self.requests.append(("DELETE", url))
        assert url == "http://api.test/api/v1/videos/asset-1"
        self.deleted = True
        with sqlite3.connect(self.data_root / "recorded-video.sqlite3") as connection:
            if not self.leave_orphan_steps:
                connection.execute("DELETE FROM job_steps WHERE job_id = 'job-1'")
            connection.execute("DELETE FROM segments WHERE asset_id = 'asset-1'")
            connection.execute("DELETE FROM jobs WHERE job_id = 'job-1'")
            connection.execute("UPDATE assets SET status = 'deleted', deleted_at = 'now' WHERE asset_id = 'asset-1'")
        if not self.retain_asset_directory:
            import shutil

            shutil.rmtree(self.data_root / "assets" / "asset-1", ignore_errors=True)
        return _response(204)


def _response(
    status_code: int,
    json_data: object | None = None,
    *,
    text: str | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "http://test")
    if json_data is not None:
        return httpx.Response(status_code, json=json_data, headers=headers, request=request)
    if text is not None:
        return httpx.Response(status_code, text=text, headers=headers, request=request)
    return httpx.Response(status_code, content=content or b"", headers=headers, request=request)


def _runtime(
    tmp_path: Path,
    *,
    media_status: int = 206,
    vision_checkpoint_provider: str = "vsa_agent.recorded_video.providers.OpenAIVisionProvider",
    vision_checkpoint_model: str = "vision-model",
    embedding_checkpoint_provider: str = "vsa_agent.recorded_video.providers.OpenAIEmbeddingProvider",
    embedding_checkpoint_model: str = "embedding-model",
    log_contents: str | None = None,
):
    run_dir = tmp_path / "123e4567-e89b-12d3-a456-426614174000"
    data_root = run_dir / "data"
    data_root.mkdir(parents=True)
    database_path = data_root / "recorded-video.sqlite3"
    manifest_relative = "derived/pipeline-v1/attempts/1/manifest.json"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE job_steps (
                job_id TEXT, stage TEXT, status TEXT, output_manifest TEXT,
                output_checksum TEXT, model TEXT, elapsed_ms INTEGER
            );
            CREATE TABLE segments (segment_id TEXT, asset_id TEXT);
            CREATE TABLE jobs (job_id TEXT, asset_id TEXT);
            CREATE TABLE assets (asset_id TEXT, status TEXT, deleted_at TEXT);
            INSERT INTO assets VALUES ('asset-1', 'ready', NULL);
            INSERT INTO jobs VALUES ('job-1', 'asset-1');
            INSERT INTO segments VALUES ('segment-1', 'asset-1');
            """
        )
        for stage in validator.REQUIRED_STAGES:
            model = "vision-model" if stage == "analyzing" else "embedding-model" if stage == "embedding" else NULL
            connection.execute(
                "INSERT INTO job_steps VALUES (?, ?, 'completed', ?, 'sha256', ?, 1)",
                ("job-1", stage, manifest_relative, model),
            )
    manifest_path = data_root / "assets" / "asset-1" / manifest_relative
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoint_identity": {
                    "vision": {
                        "provider": vision_checkpoint_provider,
                        "model": vision_checkpoint_model,
                    },
                    "embedding": {
                        "provider": embedding_checkpoint_provider,
                        "model": embedding_checkpoint_model,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    video_path = run_dir / "validation.mp4"
    video_path.write_bytes(b"video")
    report_path = run_dir / "report.md"
    (run_dir / "stack.log").write_text(
        log_contents if log_contents is not None else "run_id=123e4567-e89b-12d3-a456-426614174000\n",
        encoding="utf-8",
    )
    return data_root, video_path, report_path, FakeClient(data_root, media_status=media_status)


NULL = None


def _write_config(
    tmp_path: Path,
    *,
    allow_mock_fallback: bool = False,
    vision_provider: str = "openai_compatible",
    embedding_provider: str = "openai_compatible",
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "runtime-config.yaml"
    config_path.write_text(
        f"""
active_profile: production
backends:
  vision:
    provider: {vision_provider}
    base_url: https://vision.example.test/v1
    api_key_env: VISION_API_KEY
    api_key: do-not-record-this
  embedding:
    provider: {embedding_provider}
    base_url: https://embedding.example.test/v1
    api_key_env: EMBEDDING_API_KEY
profiles:
  production:
    vlm:
      backend: vision
      model: vision-model
    embedding:
      backend: embedding
      model: embedding-model
search:
  enabled: true
  es_endpoint: http://es.test
  embed_index: validation-index
  allow_mock_fallback: {str(allow_mock_fallback).lower()}
  force_mock_embedding: false
""",
        encoding="utf-8",
    )
    return config_path


def test_runtime_config_summary_is_production_only_and_never_records_keys(tmp_path: Path) -> None:
    config = validator._load_runtime_config(_write_config(tmp_path))

    summary = validator._runtime_config_summary(config)

    assert config.es_endpoint == "http://es.test"
    assert config.index == "validation-index"
    assert "profile=production" in summary
    assert "vision=vision-model@vision.example.test" in summary
    assert "embedding=embedding-model@embedding.example.test" in summary
    assert "mock_fallback=false" in summary
    assert "API_KEY" not in summary
    assert "do-not-record-this" not in summary

    with pytest.raises(validator.ValidationError, match="mock fallback"):
        validator._load_runtime_config(_write_config(tmp_path / "mock", allow_mock_fallback=True))


@pytest.mark.parametrize("mock_role", ["vision", "embedding"])
def test_mock_active_provider_fails_with_complete_report(tmp_path: Path, mock_role: str) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)
    config = _write_config(
        tmp_path,
        vision_provider="mock" if mock_role == "vision" else "openai_compatible",
        embedding_provider="mock" if mock_role == "embedding" else "openai_compatible",
    )

    exit_code = validator.run_validation(
        _options(data_root, video_path, report_path, config=config),
        client=client,
    )

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## runtime\n\nFAIL" in report
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "mock" in report.lower()


def test_checkpoint_provider_mismatch_fails_with_complete_report(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(
        tmp_path,
        vision_checkpoint_provider="fake.provider.Vision",
    )

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## provider\n\nFAIL" in report
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "provider" in report.lower()
    assert "不匹配" in report


def test_checkpoint_model_mismatch_fails_with_complete_report(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(
        tmp_path,
        embedding_checkpoint_model="different-embedding-model",
    )

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## provider\n\nFAIL" in report
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "model" in report.lower()
    assert "不匹配" in report


def test_es_evidence_refreshes_and_queries_actual_index_identity(tmp_path: Path) -> None:
    data_root, _, _, client = _runtime(tmp_path)
    config = validator._load_runtime_config(_write_config(tmp_path))

    evidence = validator._check_es(config, client, "asset-1", "job-1")

    assert evidence.document_count == 1
    assert evidence.segments[0].segment_id == "segment-1"
    assert ("POST", "http://es.test/validation-index/_refresh") in client.requests
    assert ("POST", "http://es.test/validation-index/_search") in client.requests


def test_es_dependency_failure_is_not_reported_as_pass(tmp_path: Path) -> None:
    data_root, _, _, _ = _runtime(tmp_path)
    config = validator._load_runtime_config(_write_config(tmp_path))
    client = FakeClient(data_root, es_status=503)

    with pytest.raises(validator.ValidationError, match="Elasticsearch refresh") as error:
        validator._check_es(config, client, "asset-1", "job-1")

    assert error.value.field == "es"


def test_sqlite_evidence_connections_are_read_only_and_query_only(tmp_path: Path) -> None:
    data_root, _, _, _ = _runtime(tmp_path)

    with validator._readonly_database(data_root / "recorded-video.sqlite3") as connection:
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden (value TEXT)")


def test_delete_fails_when_job_steps_remain_orphaned(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, leave_orphan_steps=True)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## delete\n\nFAIL" in report
    assert "SQLite" in report


def test_delete_fails_when_es_asset_identity_remains_after_refresh(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, retain_es_document=True)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## delete\n\nFAIL" in report
    assert "Elasticsearch" in report
    assert client.requests.count(("POST", "http://es.test/validation-index/_refresh")) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"video_name": "other.mp4"},
        {"start_time": "not-iso"},
        {"start_time": "2026-07-15T00:00:02Z", "end_time": "2026-07-15T00:00:01Z"},
        {"sensor_id": "other-asset"},
        {"end_time": "2026-07-15T00:00:02Z"},
    ],
)
def test_malformed_search_identity_fails_search_and_es_evidence(tmp_path: Path, overrides: dict[str, Any]) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, search_overrides=overrides)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## search\n\nFAIL" in report
    assert "## es\n\nPASS" in report


def test_cli_uses_nonzero_default_semantic_quality_threshold(tmp_path: Path) -> None:
    args = validator._parser().parse_args(
        ["--api-url", "http://api.test", "--ui-url", "http://ui.test", "--report", str(tmp_path / "report.md")]
    )

    assert args.minimum_similarity == 0.2


def test_cli_invalid_minimum_similarity_writes_complete_failure_report(tmp_path: Path) -> None:
    report_path = tmp_path / "invalid-quality.md"

    exit_code = validator.main(
        [
            "--api-url",
            "http://api.test",
            "--ui-url",
            "http://ui.test",
            "--report",
            str(report_path),
            "--minimum-similarity",
            "-1",
        ]
    )

    assert exit_code == 1
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "## runtime\n\nFAIL" in report
    assert "minimum similarity" in report


def test_malformed_url_still_writes_all_report_fields(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)
    options = _options(data_root, video_path, report_path)
    options = validator.ValidationOptions(**{**options.__dict__, "api_url": "http://api.test:invalid"})

    exit_code = validator.run_validation(options, client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)


def test_client_close_failure_does_not_mask_primary_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)

    class CloseFailureClient(FakeClient):
        def close(self) -> None:
            raise RuntimeError("Authorization: Bearer close-secret")

    client = CloseFailureClient(data_root, media_status=200)
    monkeypatch.setattr(validator.httpx, "Client", lambda **_kwargs: client)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path))

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "HTTP Range 请求未返回 206" in report
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "close-secret" not in report


def _options(data_root: Path, video_path: Path, report_path: Path, *, config: Path | None = None):
    return validator.ValidationOptions(
        api_url="http://api.test",
        ui_url="http://ui.test",
        report=report_path,
        config=config or _write_config(report_path.parent),
        data_root=data_root,
        video=video_path,
        query="forklift near worker",
        timeout_seconds=1.0,
        poll_interval_seconds=0.0,
        minimum_similarity=0.5,
    )


def test_validator_checks_full_business_flow_in_order(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 0
    report = report_path.read_text(encoding="utf-8")
    assert all(f"## {field}\n\nPASS" in report for field in validator.REPORT_FIELDS)
    assert "es=http://es.test/validation-index" in report
    assert ("POST", "http://es.test/validation-index/_search") in client.requests
    media_index = client.requests.index(("GET", "http://api.test/api/v1/vst/v1/storage/file/asset-1"))
    delete_index = client.requests.index(("DELETE", "http://api.test/api/v1/videos/asset-1"))
    assert media_index < delete_index


def test_success_report_publishes_structured_evidence_bound_to_run_artifact(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 0
    report = report_path.read_text(encoding="utf-8")
    run_id = report.split("- run_id: ", 1)[1].splitlines()[0]
    assert run_id in report
    assert report.count(f"- run_id: {run_id}") == len(validator.REPORT_FIELDS)
    assert report.count("- timestamp_utc:") == len(validator.REPORT_FIELDS)
    assert report.count("- asset_id: asset-1") == len(validator.REPORT_FIELDS)
    assert report.count("- job_id: job-1") == len(validator.REPORT_FIELDS)
    assert report.count("- segment_id: segment-1") == len(validator.REPORT_FIELDS)
    assert "- endpoint: http://es.test" in report
    assert "- index: validation-index" in report
    assert "- document_count: 1" in report
    assert "- expected_segment_count: 1" in report
    assert "- dedup_count: 1" in report
    assert "- similarity: 0.910" in report
    assert "- HTTP 206: PASS" in report
    assert "- Accept-Ranges: bytes" in report
    assert "- Content-Range: bytes 0-0/5" in report
    assert "- cleanup_path:" in report
    assert "- cleanup_status: PASS" in report
    assert "- secret_scan: PASS (无密钥)" in report
    log_ref = next(line.split(": ", 1)[1] for line in report.splitlines() if line.startswith("- log_ref:"))
    assert Path(log_ref).is_file()
    assert run_id in Path(log_ref).read_text(encoding="utf-8")


def test_success_report_does_not_mark_search_as_es_evidence(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)

    assert validator.run_validation(_options(data_root, video_path, report_path), client=client) == 0

    sections = report_path.read_text(encoding="utf-8").split("\n## ")
    es_section = next(section for section in sections if section.startswith("es\n"))
    search_section = next(section for section in sections if section.startswith("search\n"))
    assert "业务搜索" not in es_section
    assert "similarity" not in es_section
    assert "similarity: 0.910" in search_section


def test_report_rejects_log_artifact_without_same_run_id(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path, log_contents="different-run\n")

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## runtime\n\nFAIL" in report
    assert "log" in report.lower()


def test_es_rejects_duplicate_or_unexpected_segments(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, duplicate_es_hit=True)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## es\n\nFAIL" in report
    assert "duplicate" in report.lower() or "segment" in report.lower()


def test_delete_rejects_cleanup_path_that_still_exists(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, retain_asset_directory=True)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## delete\n\nFAIL" in report
    assert "cleanup" in report.lower()


def test_validation_script_returns_nonzero_when_media_range_is_not_206(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path, media_status=200)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## media\n\nFAIL" in report
    assert "HTTP Range 请求未返回 206" in report
    assert "## delete\n\nPASS" in report


def test_dependency_failure_is_reported_without_secret_or_silent_skip(tmp_path: Path) -> None:
    data_root, video_path, report_path, client = _runtime(tmp_path)
    missing_root = tmp_path / "Authorization-Bearer-secret"

    exit_code = validator.run_validation(_options(missing_root, video_path, report_path), client=client)

    assert exit_code == 1
    report = report_path.read_text(encoding="utf-8")
    assert all(f"## {field}" in report for field in validator.REPORT_FIELDS)
    assert "SKIP" not in report
    assert "Bearer" not in report
    assert "authorization-bearer-secret" not in report.lower()


def test_asset_is_cleaned_when_upload_fails_after_session_creation(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, upload_status=503)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    assert ("DELETE", "http://api.test/api/v1/videos/asset-1") in client.requests
    assert "## delete\n\nPASS" in report_path.read_text(encoding="utf-8")
