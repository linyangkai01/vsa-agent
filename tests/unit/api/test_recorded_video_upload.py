"""Contract tests for recorded-video uploads served by the agent."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig, RecordedVideoConfig
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from vsa_agent.api import recorded_video

    config = AppConfig(
        recorded_video=RecordedVideoConfig(
            data_root=tmp_path / "recorded-video",
            max_upload_bytes=10,
        )
    )
    monkeypatch.setattr(recorded_video, "get_config", lambda: config)
    app = FastAPI()
    app.include_router(recorded_video.router)
    return TestClient(app)


def _create_upload(client: TestClient, filename: str = "yard.mkv") -> dict[str, str]:
    response = client.post("/api/v1/videos", json={"filename": filename})
    assert response.status_code == 200
    return response.json()


def _upload_chunk(
    client: TestClient,
    upload_url: str,
    content: bytes,
    *,
    chunk: int = 1,
    total: int = 1,
    identifier: str = "upload-identifier",
    filename: str = "yard.mkv",
) -> object:
    return client.post(
        upload_url,
        files={"mediaFile": (filename, content, "video/x-matroska")},
        headers={
            "nvstreamer-chunk-number": str(chunk),
            "nvstreamer-total-chunks": str(total),
            "nvstreamer-is-last-chunk": str(chunk == total).lower(),
            "nvstreamer-identifier": identifier,
            "nvstreamer-file-name": filename,
        },
    )


def test_create_upload_accepts_only_safe_mp4_or_mkv_basename(client: TestClient) -> None:
    assert client.post("/api/v1/videos", json={"filename": "../yard.mp4"}).status_code == 400
    assert client.post("/api/v1/videos", json={"filename": "yard.avi"}).status_code == 400
    assert client.post("/api/v1/videos", json={"filename": "yard.mp4", "total_bytes": 1}).status_code == 422


def test_final_chunk_returns_same_sensor_and_stream_id(client: TestClient) -> None:
    created = _create_upload(client)

    response = _upload_chunk(client, created["url"], b"video", filename="yard.mkv")

    assert response.status_code == 200
    body = response.json()
    assert body["sensorId"] == body["streamId"] == created["asset_id"]
    assert body["bytes"] == 5
    assert body["chunkCount"] == 1
    assert Path(body["filePath"]).is_file()


def test_final_chunk_persists_assembled_integrity_before_idempotent_complete(
    client: TestClient,
    tmp_path: Path,
) -> None:
    created = _create_upload(client, "yard.mp4")
    content = b"video"

    first = _upload_chunk(client, created["url"], content, filename="yard.mp4")
    duplicate = _upload_chunk(client, created["url"], content, filename="yard.mp4")
    completion = client.post(f"/api/v1/videos/{created['asset_id']}/complete", json={})
    conflicting = _upload_chunk(client, created["url"], b"other", filename="yard.mp4")

    assert first.status_code == duplicate.status_code == 200
    assert completion.status_code == 202
    assert conflicting.status_code == 409
    database_path = tmp_path / "recorded-video" / "recorded-video.sqlite3"
    with sqlite3.connect(database_path) as connection:
        persisted = connection.execute(
            "SELECT size_bytes, sha256 FROM assets WHERE asset_id = ?",
            (created["asset_id"],),
        ).fetchone()
    assert persisted == (len(content), hashlib.sha256(content).hexdigest())


def test_chunk_cumulative_size_limit_rejects_before_assembly(client: TestClient, tmp_path: Path) -> None:
    created = _create_upload(client)

    response = _upload_chunk(client, created["url"], b"x" * 11)

    assert response.status_code == 413
    assert not (tmp_path / "recorded-video" / "assets").exists()


def test_chunks_require_a_stable_identifier_and_idempotent_content(client: TestClient) -> None:
    created = _create_upload(client, "yard.mp4")
    first = _upload_chunk(
        client,
        created["url"],
        b"first",
        chunk=1,
        total=2,
        identifier="stable-id",
        filename="yard.mp4",
    )
    duplicate = _upload_chunk(
        client,
        created["url"],
        b"first",
        chunk=1,
        total=2,
        identifier="stable-id",
        filename="yard.mp4",
    )
    different_identifier = _upload_chunk(
        client,
        created["url"],
        b"second",
        chunk=2,
        total=2,
        identifier="other-id",
        filename="yard.mp4",
    )
    conflicting_duplicate = _upload_chunk(
        client,
        created["url"],
        b"changed",
        chunk=1,
        total=2,
        identifier="stable-id",
        filename="yard.mp4",
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert different_identifier.status_code == 409
    assert conflicting_duplicate.status_code == 409


def test_chunk_protocol_rejects_invalid_chunk_number(client: TestClient) -> None:
    created = _create_upload(client)

    response = _upload_chunk(client, created["url"], b"x", chunk=0, total=1)

    assert response.status_code == 400


def test_first_chunk_can_bind_total_without_being_chunk_one(client: TestClient) -> None:
    created = _create_upload(client)

    response = _upload_chunk(
        client,
        created["url"],
        b"second",
        chunk=2,
        total=2,
    )

    assert response.status_code == 200
    assert response.json() == {"chunkCount": 1}


def test_create_upload_removes_database_rows_when_session_directory_creation_fails(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vsa_agent.api import recorded_video

    original_create_session = recorded_video.LocalAssetStore.create_session

    async def fail_create_session(store: object, *args: object, **kwargs: object) -> None:
        await original_create_session(store, *args, **kwargs)
        raise OSError("session directory unavailable")

    monkeypatch.setattr(recorded_video.LocalAssetStore, "create_session", fail_create_session)

    with pytest.raises(OSError, match="session directory unavailable"):
        client.post("/api/v1/videos", json={"filename": "yard.mp4"})

    database_path = tmp_path / "recorded-video" / "recorded-video.sqlite3"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM upload_sessions").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone() == (0,)
    assert not list((tmp_path / "recorded-video" / "uploads").glob("*"))


def test_chunk_confirm_losing_reservation_returns_conflict_instead_of_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vsa_agent.api import recorded_video

    created = _create_upload(client)

    async def lose_reservation(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(recorded_video.JobRepository, "confirm_reserved_upload_chunk", lose_reservation)

    response = _upload_chunk(client, created["url"], b"video")

    assert response.status_code == 409
    assert "reservation" in response.json()["detail"]


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [(ErrorCode.CORRUPT_MEDIA, 409), (ErrorCode.DISK_FULL, 507)],
)
def test_chunk_domain_storage_errors_return_stable_http_responses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    code: ErrorCode,
    expected_status: int,
) -> None:
    from vsa_agent.api import recorded_video

    created = _create_upload(client)

    async def fail_write(*_args: object, **_kwargs: object) -> str:
        raise RecordedVideoError(code, retryable=False, message=f"{code.value}: storage failure")

    monkeypatch.setattr(recorded_video.LocalAssetStore, "write_chunk", fail_write)

    response = _upload_chunk(client, created["url"], b"video")

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"error_code": code.value, "error_message": f"{code.value}: storage failure"}}


def test_failed_first_chunk_write_releases_identifier_and_total_binding(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vsa_agent.api import recorded_video

    created = _create_upload(client, "yard.mp4")
    original_write_chunk = recorded_video.LocalAssetStore.write_chunk
    writes = 0

    async def fail_first_write(store: object, *args: object, **kwargs: object) -> str:
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("chunk write failed")
        return await original_write_chunk(store, *args, **kwargs)

    monkeypatch.setattr(recorded_video.LocalAssetStore, "write_chunk", fail_first_write)

    with pytest.raises(OSError, match="chunk write failed"):
        _upload_chunk(
            client,
            created["url"],
            b"failed",
            chunk=1,
            total=2,
            identifier="failed-identifier",
            filename="yard.mp4",
        )

    database_path = tmp_path / "recorded-video" / "recorded-video.sqlite3"
    with sqlite3.connect(database_path) as connection:
        persisted = connection.execute(
            "SELECT identifier, total_chunks, received_chunks FROM upload_sessions WHERE session_id = ?",
            (created["upload_session_id"],),
        ).fetchone()
    assert persisted == (created["upload_session_id"], 1, 0)

    retry = _upload_chunk(
        client,
        created["url"],
        b"retry",
        chunk=1,
        total=1,
        identifier="retry-identifier",
        filename="yard.mp4",
    )

    assert retry.status_code == 200
    assert retry.json()["chunkCount"] == 1
