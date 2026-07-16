"""Contract tests for the production recorded-video validator."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

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
    def __init__(self, data_root: Path, *, media_status: int = 206, upload_status: int = 200) -> None:
        self.data_root = data_root
        self.media_status = media_status
        self.upload_status = upload_status
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
            return _response(
                200,
                {
                    "data": [
                        {
                            "video_name": "validation.mp4",
                            "description": "forklift near worker",
                            "start_time": "2026-07-15T00:00:00Z",
                            "end_time": "2026-07-15T00:00:01Z",
                            "sensor_id": "asset-1",
                            "screenshot_url": "/thumb.jpg",
                            "similarity": 0.91,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected POST {url}")

    def delete(self, url: str, **_kwargs: Any) -> httpx.Response:
        self.requests.append(("DELETE", url))
        assert url == "http://api.test/api/v1/videos/asset-1"
        self.deleted = True
        with sqlite3.connect(self.data_root / "recorded-video.sqlite3") as connection:
            connection.execute("DELETE FROM job_steps WHERE job_id = 'job-1'")
            connection.execute("DELETE FROM segments WHERE asset_id = 'asset-1'")
            connection.execute("DELETE FROM jobs WHERE job_id = 'job-1'")
            connection.execute("UPDATE assets SET status = 'deleted', deleted_at = 'now' WHERE asset_id = 'asset-1'")
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


def _runtime(tmp_path: Path, *, media_status: int = 206):
    data_root = tmp_path / "data"
    data_root.mkdir()
    database_path = data_root / "recorded-video.sqlite3"
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
                "INSERT INTO job_steps VALUES (?, ?, 'completed', 'manifest.json', 'sha256', ?, 1)",
                ("job-1", stage, model),
            )
    video_path = tmp_path / "validation.mp4"
    video_path.write_bytes(b"video")
    report_path = tmp_path / "report.md"
    return data_root, video_path, report_path, FakeClient(data_root, media_status=media_status)


NULL = None


def _options(data_root: Path, video_path: Path, report_path: Path):
    return validator.ValidationOptions(
        api_url="http://api.test",
        ui_url="http://ui.test",
        report=report_path,
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
    media_index = client.requests.index(("GET", "http://api.test/api/v1/vst/v1/storage/file/asset-1"))
    delete_index = client.requests.index(("DELETE", "http://api.test/api/v1/videos/asset-1"))
    assert media_index < delete_index


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
    assert "secret" not in report.lower()


def test_asset_is_cleaned_when_upload_fails_after_session_creation(tmp_path: Path) -> None:
    data_root, video_path, report_path, _ = _runtime(tmp_path)
    client = FakeClient(data_root, upload_status=503)

    exit_code = validator.run_validation(_options(data_root, video_path, report_path), client=client)

    assert exit_code == 1
    assert ("DELETE", "http://api.test/api/v1/videos/asset-1") in client.requests
    assert "## delete\n\nPASS" in report_path.read_text(encoding="utf-8")
