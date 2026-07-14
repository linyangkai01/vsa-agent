"""VST read facade contract tests for recorded-video assets."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig, RecordedVideoConfig
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.models import Asset, AssetStatus, UploadSession
from vsa_agent.recorded_video.repository import JobRepository

NOW = datetime(2026, 7, 14, 0, 0, tzinfo=UTC)


def _run(coro):
    return asyncio.run(coro)


def _seed_ready_asset(
    data_root: Path,
    *,
    extension: str = "mp4",
    duration_ms: int | None = 10_000,
    playback_proxy: bytes | None = None,
) -> str:
    asset_id = str(uuid.uuid4())
    asset = Asset(
        asset_id=asset_id,
        display_filename=f"yard.{extension}",
        safe_filename=f"yard.{extension}",
        size_bytes=10,
        sha256="a" * 64,
        mime_type="video/mp4" if extension == "mp4" else "video/x-matroska",
        source_extension=extension,
        duration_ms=duration_ms,
        timeline_origin=NOW,
        status=AssetStatus.UPLOADING,
        created_at=NOW,
        updated_at=NOW,
    )
    session = UploadSession(
        session_id=str(uuid.uuid4()),
        identifier=str(uuid.uuid4()),
        asset_id=asset_id,
        total_chunks=1,
        filename=f"yard.{extension}",
        temp_dir="uploads/unused",
        status=AssetStatus.UPLOADING,
        expires_at=NOW + timedelta(days=1),
    )
    repository = JobRepository(data_root / "recorded-video.sqlite3")
    store = LocalAssetStore(data_root)
    _run(repository.initialize())
    _run(repository.create_upload_session(asset, session))
    _run(repository.record_chunk(session.session_id, 1, "chunk", size_bytes=10, path="000001.part"))
    _run(repository.complete_upload(asset_id, "v1", now=NOW))
    _run(store.write_atomic(f"assets/{asset_id}/source/original.{extension}", b"0123456789"))
    if playback_proxy is not None:
        _run(store.write_atomic(f"assets/{asset_id}/playback/proxy.mp4", playback_proxy))
    _run(store.write_atomic(f"assets/{asset_id}/derived/v1/thumb.jpg", b"thumbnail"))
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO segments (
                segment_id, asset_id, pipeline_version, ordinal, start_offset_ms, end_offset_ms,
                start_time, end_time, description, thumbnail_key, model, prompt_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "segment-1",
                asset_id,
                "v1",
                0,
                0,
                10_000,
                NOW.isoformat(),
                (NOW + timedelta(seconds=10)).isoformat(),
                "yard",
                "derived/v1/thumb.jpg",
                None,
                None,
            ),
        )
        connection.commit()
    return asset_id


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root)
    app = FastAPI()
    app.include_router(recorded_video_vst.router)
    return TestClient(app), asset_id


def test_vst_lists_ready_streams_sensors_and_storage_timeline(client: tuple[TestClient, str]) -> None:
    http, asset_id = client

    streams = http.get("/api/v1/vst/v1/replay/streams")
    sensors = http.get("/api/v1/vst/v1/sensor/list")
    storage = http.get("/api/v1/vst/v1/storage/size?timelines=true")

    assert streams.status_code == sensors.status_code == storage.status_code == 200
    assert streams.json()[0][asset_id][0]["streamId"] == asset_id
    assert sensors.json() == [{"name": "yard.mp4", "sensorId": asset_id, "state": "online", "type": "recorded"}]
    assert storage.json()[asset_id]["timelines"][0]["startTime"] == NOW.isoformat()
    assert storage.json()[asset_id]["timelines"][0]["sizeInMegabytes"] == pytest.approx(10 / 1_000_000)
    assert storage.json()["total"]["sizeInMegabytes"] == pytest.approx(10 / 1_000_000)


def test_vst_returns_same_origin_media_url_and_segment_thumbnail(client: tuple[TestClient, str]) -> None:
    http, asset_id = client

    url = http.get(
        f"/api/v1/vst/v1/storage/file/{asset_id}/url",
        params={"startTime": NOW.isoformat(), "endTime": (NOW + timedelta(seconds=1)).isoformat()},
    )
    picture = http.get(f"/api/v1/vst/v1/replay/stream/{asset_id}/picture", params={"startTime": NOW.isoformat()})

    assert url.status_code == picture.status_code == 200
    assert url.json()["videoUrl"].startswith("http://testserver/api/v1/vst/v1/storage/file/")
    assert NOW.isoformat() not in url.json()["videoUrl"]
    assert url.json()["startTime"] == 0
    assert url.json()["endTime"] == 1
    assert url.json()["videoUrl"].endswith("#t=0,1")
    assert picture.content == b"thumbnail"


def test_vst_clamps_requested_playback_offsets_to_asset_duration(client: tuple[TestClient, str]) -> None:
    http, asset_id = client

    response = http.get(
        f"/api/v1/vst/v1/storage/file/{asset_id}/url",
        params={
            "startTime": (NOW - timedelta(seconds=5)).isoformat(),
            "endTime": (NOW + timedelta(seconds=20)).isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.json()["startTime"] == 0
    assert response.json()["endTime"] == 10
    assert response.json()["videoUrl"].endswith("#t=0,10")
