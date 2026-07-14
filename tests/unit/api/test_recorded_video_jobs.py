"""Contract tests for the recorded-video job lifecycle API."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig, RecordedVideoConfig
from vsa_agent.recorded_video.models import JobStage, JobStatus


@pytest.fixture
def api_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    from vsa_agent.api import recorded_video

    data_root = tmp_path / "recorded-video"
    config = AppConfig(
        recorded_video=RecordedVideoConfig(
            data_root=data_root,
            max_upload_bytes=1024,
        )
    )
    monkeypatch.setattr(recorded_video, "get_config", lambda: config)
    app = FastAPI()
    app.include_router(recorded_video.router)
    return TestClient(app), data_root / "recorded-video.sqlite3"


def _ready_asset(client: TestClient, *, filename: str = "yard.mp4") -> str:
    created = client.post("/api/v1/videos", json={"filename": filename})
    assert created.status_code == 200
    body = created.json()
    uploaded = client.post(
        body["url"],
        files={"mediaFile": (filename, b"video", "video/mp4")},
        headers={
            "nvstreamer-chunk-number": "1",
            "nvstreamer-total-chunks": "1",
            "nvstreamer-is-last-chunk": "true",
            "nvstreamer-identifier": f"upload-{filename}",
            "nvstreamer-file-name": filename,
        },
    )
    assert uploaded.status_code == 200
    return body["asset_id"]


def _set_job_state(
    database_path: Path,
    job_id: str,
    status: JobStatus,
    *,
    lease_until: datetime | None = None,
    last_error: str | None = None,
) -> None:
    now = datetime.now(UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, stage = ?, attempt = 2, lease_owner = ?, lease_until = ?,
                heartbeat_at = ?, last_error = ?
            WHERE job_id = ?
            """,
            (
                status.value,
                JobStage.ANALYZING.value,
                "worker-1" if status is JobStatus.RUNNING else None,
                lease_until.isoformat() if lease_until else None,
                now.isoformat() if status is JobStatus.RUNNING else None,
                last_error,
                job_id,
            ),
        )


def test_repeated_complete_returns_same_job_and_visible_status(api_context: tuple[TestClient, Path]) -> None:
    client, _ = api_context
    asset_id = _ready_asset(client)

    one = client.post(f"/api/v1/videos/{asset_id}/complete", json={})
    two = client.post(f"/api/v1/videos/{asset_id}/complete", json={})

    assert one.status_code == two.status_code == 202
    assert one.json() == two.json()
    assert one.json()["asset_id"] == asset_id
    assert one.json()["status"] == "queued"
    status_url = one.json()["status_url"]
    assert status_url == f"/api/v1/jobs/{one.json()['job_id']}"
    assert client.get(status_url).json()["status"] == "queued"


def test_complete_accepts_original_ui_forwarded_upload_payload(api_context: tuple[TestClient, Path]) -> None:
    client, _ = api_context
    asset_id = _ready_asset(client)

    response = client.post(
        f"/api/v1/videos/{asset_id}/complete",
        json={
            "sensorId": asset_id,
            "streamId": asset_id,
            "filePath": "ignored-client-value.mp4",
            "bytes": 5,
            "chunkCount": 1,
            "filename": "yard.mp4",
            "custom_params": {"prompt": "describe safety events"},
        },
    )

    assert response.status_code == 202
    assert response.json()["asset_id"] == asset_id
    assert response.json()["status"] == "queued"


def test_complete_rejects_upload_that_has_not_been_assembled(api_context: tuple[TestClient, Path]) -> None:
    client, database_path = api_context
    created = client.post("/api/v1/videos", json={"filename": "yard.mp4"}).json()

    response = client.post(f"/api/v1/videos/{created['asset_id']}/complete", json={})

    assert response.status_code == 409
    if database_path.exists():
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone() == (0,)


def test_complete_returns_not_found_for_unknown_asset(api_context: tuple[TestClient, Path]) -> None:
    client, _ = api_context

    response = client.post("/api/v1/videos/00000000-0000-0000-0000-000000000000/complete", json={})

    assert response.status_code == 404


def test_job_status_exposes_only_public_fields_and_safe_error(api_context: tuple[TestClient, Path]) -> None:
    client, database_path = api_context
    completed = client.post(f"/api/v1/videos/{_ready_asset(client)}/complete", json={}).json()
    _set_job_state(
        database_path,
        completed["job_id"],
        JobStatus.FAILED,
        last_error="provider failed; Authorization: Bearer super-secret-token",
    )

    response = client.get(completed["status_url"])

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "asset_id",
        "job_id",
        "status",
        "stage",
        "attempt",
        "error",
        "created_at",
        "updated_at",
        "next_run_at",
        "heartbeat_at",
    }
    assert body["status"] == "failed"
    assert body["stage"] == "analyzing"
    assert body["attempt"] == 2
    assert body["error"] == "Recorded video processing failed"
    assert "secret" not in response.text
    assert client.get("/api/v1/jobs/missing").status_code == 404


def test_retry_only_accepts_failed_jobs_and_clears_transient_status(api_context: tuple[TestClient, Path]) -> None:
    client, database_path = api_context
    completed = client.post(f"/api/v1/videos/{_ready_asset(client)}/complete", json={}).json()

    assert client.post(f"/api/v1/jobs/{completed['job_id']}/retry", json={}).status_code == 409
    _set_job_state(
        database_path,
        completed["job_id"],
        JobStatus.FAILED,
        last_error="secret provider detail",
    )

    response = client.post(f"/api/v1/jobs/{completed['job_id']}/retry", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["error"] is None
    assert response.json()["next_run_at"] is not None
    assert client.post(f"/api/v1/jobs/{completed['job_id']}/retry", json={}).status_code == 409
    assert client.post("/api/v1/jobs/missing/retry", json={}).status_code == 404


def test_cancel_is_immediate_for_queued_and_deferred_for_running(api_context: tuple[TestClient, Path]) -> None:
    client, database_path = api_context
    queued = client.post(f"/api/v1/videos/{_ready_asset(client, filename='queued.mp4')}/complete", json={}).json()

    cancelled = client.post(f"/api/v1/jobs/{queued['job_id']}/cancel", json={})

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    running = client.post(f"/api/v1/videos/{_ready_asset(client, filename='running.mp4')}/complete", json={}).json()
    _set_job_state(
        database_path,
        running["job_id"],
        JobStatus.RUNNING,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )

    requested = client.post(f"/api/v1/jobs/{running['job_id']}/cancel", json={})

    assert requested.status_code == 200
    assert requested.json()["status"] == "running"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT cancel_requested FROM jobs WHERE job_id = ?",
            (running["job_id"],),
        ).fetchone()
    assert row == (1,)
    assert client.post("/api/v1/jobs/missing/cancel", json={}).status_code == 404
