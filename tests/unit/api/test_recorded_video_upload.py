"""Contract tests for recorded-video uploads served by the agent."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig, RecordedVideoConfig


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
