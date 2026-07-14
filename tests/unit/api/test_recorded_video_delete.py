"""Contract tests for idempotent recorded-video asset deletion."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig, RecordedVideoConfig
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.models import JobStage, JobStatus
from vsa_agent.recorded_video.repository import JobRepository


class RecordingProjectionStore:
    def __init__(self, events: list[str] | None = None) -> None:
        self.deleted_assets: list[str] = []
        self.events = events

    async def delete_asset(self, asset_id: str) -> None:
        self.deleted_assets.append(asset_id)
        if self.events is not None:
            self.events.append("projection")


class FailingProjectionStore:
    async def delete_asset(self, asset_id: str) -> None:
        raise KeyError(f"projection backend unavailable for {asset_id}")


class OrderedAssetStore(LocalAssetStore):
    def __init__(self, root: Path, events: list[str], *, fail_derived_once: bool = False) -> None:
        super().__init__(root)
        self.events = events
        self.fail_derived_once = fail_derived_once

    async def remove_derived(self, asset_id: str) -> None:
        self.events.append("derived")
        if self.fail_derived_once:
            self.fail_derived_once = False
            raise OSError("derived storage unavailable")
        await super().remove_derived(asset_id)

    async def remove_source(self, asset_id: str) -> None:
        self.events.append("source")
        await super().remove_source(asset_id)

    async def remove_upload_sessions(self, session_ids: list[str]) -> None:
        self.events.append("upload")
        await super().remove_upload_sessions(session_ids)


class OrderedRepository(JobRepository):
    def __init__(self, database_path: Path, events: list[str]) -> None:
        super().__init__(database_path)
        self.events = events

    async def finalize_asset_deletion(self, asset_id: str, now: datetime) -> None:
        self.events.append("sqlite")
        await super().finalize_asset_deletion(asset_id, now)


@pytest.fixture
def api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, Path, RecordingProjectionStore]:
    from vsa_agent.api import recorded_video

    data_root = tmp_path / "recorded-video"
    config = AppConfig(
        recorded_video=RecordedVideoConfig(
            data_root=data_root,
            max_upload_bytes=1024,
        )
    )
    monkeypatch.setattr(recorded_video, "get_config", lambda: config)
    projection_store = RecordingProjectionStore()
    app = FastAPI()
    app.state.recorded_video_projection_store = projection_store
    app.include_router(recorded_video.router)
    return TestClient(app), data_root, projection_store


def _ready_asset(client: TestClient, filename: str = "yard.mp4") -> tuple[str, str]:
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
    completed = client.post(f"/api/v1/videos/{body['asset_id']}/complete", json={})
    assert completed.status_code == 202
    return body["asset_id"], completed.json()["job_id"]


def test_delete_requests_cancel_then_is_idempotent(
    api_context: tuple[TestClient, Path, RecordingProjectionStore],
) -> None:
    client, data_root, projection_store = api_context
    asset_id, job_id = _ready_asset(client)
    database_path = data_root / "recorded-video.sqlite3"
    now = datetime.now(UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, stage = ?, lease_owner = ?, lease_until = ?, heartbeat_at = ?
            WHERE job_id = ?
            """,
            (
                JobStatus.RUNNING.value,
                JobStage.ANALYZING.value,
                "worker-1",
                (now + timedelta(minutes=1)).isoformat(),
                now.isoformat(),
                job_id,
            ),
        )

    first = client.delete(f"/api/v1/videos/{asset_id}")
    second = client.delete(f"/api/v1/videos/{asset_id}")

    assert first.status_code == 202
    assert second.status_code in {202, 204}
    with sqlite3.connect(database_path) as connection:
        job = connection.execute(
            "SELECT status, cancel_requested FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        asset = connection.execute(
            "SELECT deleted_at FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
    assert job == (JobStatus.RUNNING.value, 1)
    assert asset == (None,)
    assert projection_store.deleted_assets == []
    assert (data_root / "assets" / asset_id / "source" / "original.mp4").is_file()

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, cancel_requested = 0, lease_owner = NULL,
                lease_until = NULL, heartbeat_at = NULL
            WHERE job_id = ?
            """,
            (JobStatus.CANCELLED.value, job_id),
        )

    completed = client.delete(f"/api/v1/videos/{asset_id}")
    repeated = client.delete(f"/api/v1/videos/{asset_id}")

    assert completed.status_code == repeated.status_code == 204
    assert projection_store.deleted_assets == [asset_id]
    assert not (data_root / "assets" / asset_id).exists()


def test_delete_cascades_in_retryable_strict_order(
    api_context: tuple[TestClient, Path, RecordingProjectionStore],
) -> None:
    client, data_root, _ = api_context
    asset_id, _ = _ready_asset(client)
    store = LocalAssetStore(data_root)
    asyncio.run(store.write_atomic(f"assets/{asset_id}/derived/v1/thumb.jpg", b"thumb"))
    asyncio.run(store.write_atomic(f"assets/{asset_id}/playback/proxy.mp4", b"proxy"))
    events: list[str] = []
    repository = OrderedRepository(data_root / "recorded-video.sqlite3", events)
    ordered_store = OrderedAssetStore(data_root, events)
    projection_store = RecordingProjectionStore(events)

    from vsa_agent.api.recorded_video import DeletionService

    result = asyncio.run(DeletionService(repository, ordered_store).delete(asset_id, projection_store))

    assert result.pending is False
    assert events == ["projection", "derived", "source", "upload", "sqlite"]
    assert not (data_root / "assets" / asset_id).exists()
    assert not list((data_root / "uploads").glob("*"))
    with sqlite3.connect(repository.database_path) as connection:
        asset = connection.execute(
            "SELECT status, deleted_at FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        steps = connection.execute(
            "SELECT step FROM asset_deletion_steps WHERE asset_id = ? ORDER BY rowid",
            (asset_id,),
        ).fetchall()
        child_counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table} WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            for table in ("upload_sessions", "jobs", "segments")
        )
    assert asset is not None and asset[0] == "deleted" and asset[1] is not None
    assert steps == [(step,) for step in ("projection", "derived", "source", "upload", "sqlite")]
    assert child_counts == (0, 0, 0)


def test_delete_retry_resumes_after_last_persisted_step(
    api_context: tuple[TestClient, Path, RecordingProjectionStore],
) -> None:
    client, data_root, _ = api_context
    asset_id, _ = _ready_asset(client)
    events: list[str] = []
    repository = OrderedRepository(data_root / "recorded-video.sqlite3", events)
    store = OrderedAssetStore(data_root, events, fail_derived_once=True)
    projection_store = RecordingProjectionStore(events)

    from vsa_agent.api.recorded_video import DeletionService

    with pytest.raises(OSError, match="derived storage unavailable"):
        asyncio.run(DeletionService(repository, store).delete(asset_id, projection_store))

    with sqlite3.connect(repository.database_path) as connection:
        steps_after_failure = connection.execute(
            "SELECT step FROM asset_deletion_steps WHERE asset_id = ? ORDER BY rowid",
            (asset_id,),
        ).fetchall()
    assert steps_after_failure == [("projection",)]

    result = asyncio.run(DeletionService(repository, store).delete(asset_id, projection_store))

    assert result.pending is False
    assert projection_store.deleted_assets == [asset_id]
    assert events == [
        "projection",
        "derived",
        "derived",
        "source",
        "upload",
        "sqlite",
    ]


def test_delete_never_treats_asset_id_as_a_filesystem_path(
    api_context: tuple[TestClient, Path, RecordingProjectionStore],
) -> None:
    client, data_root, projection_store = api_context
    outside = data_root.parent / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")

    response = client.delete("/api/v1/videos/..%5Coutside")

    assert response.status_code == 404
    assert outside.read_text(encoding="utf-8") == "preserve"
    assert projection_store.deleted_assets == []


def test_projection_key_error_remains_retryable_server_failure(
    api_context: tuple[TestClient, Path, RecordingProjectionStore],
) -> None:
    client, data_root, _ = api_context
    asset_id, _ = _ready_asset(client)
    client.app.state.recorded_video_projection_store = FailingProjectionStore()
    failure_client = TestClient(client.app, raise_server_exceptions=False)

    response = failure_client.delete(f"/api/v1/videos/{asset_id}")

    assert response.status_code == 500
    with sqlite3.connect(data_root / "recorded-video.sqlite3") as connection:
        steps = connection.execute(
            "SELECT step FROM asset_deletion_steps WHERE asset_id = ?",
            (asset_id,),
        ).fetchall()
    assert steps == []
