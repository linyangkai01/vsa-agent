"""HTTP byte-range contract tests for recorded-video media."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.api.test_recorded_video_vst import _seed_ready_asset
from vsa_agent.config import AppConfig, RecordedVideoConfig


@pytest.fixture
def media_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root)
    app = FastAPI()
    app.include_router(recorded_video_vst.router)
    return TestClient(app), asset_id


def test_media_returns_full_and_partial_ranges_and_rejects_unsatisfiable(
    media_client: tuple[TestClient, str],
) -> None:
    http, asset_id = media_client
    path = f"/api/v1/vst/v1/storage/file/{asset_id}"

    full = http.get(path)
    partial = http.get(path, headers={"Range": "bytes=2-4"})
    clamped = http.get(path, headers={"Range": "bytes=8-99"})
    unsatisfiable = http.get(path, headers={"Range": "bytes=20-"})

    assert (full.status_code, full.headers["accept-ranges"], full.content) == (200, "bytes", b"0123456789")
    assert (partial.status_code, partial.headers["content-range"], partial.content) == (206, "bytes 2-4/10", b"234")
    assert (clamped.status_code, clamped.headers["content-range"], clamped.content) == (206, "bytes 8-9/10", b"89")
    assert (unsatisfiable.status_code, unsatisfiable.headers["content-range"]) == (416, "bytes */10")


def test_mkv_playback_proxy_is_served_as_mp4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root, extension="mkv", playback_proxy=b"mp4-proxy")
    app = FastAPI()
    app.include_router(recorded_video_vst.router)
    http = TestClient(app)

    response = http.get(f"/api/v1/vst/v1/storage/file/{asset_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"mp4-proxy"
