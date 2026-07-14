"""HTTP byte-range contract tests for recorded-video media."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

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


def test_media_supports_suffix_and_open_ended_ranges(media_client: tuple[TestClient, str]) -> None:
    http, asset_id = media_client
    path = f"/api/v1/vst/v1/storage/file/{asset_id}"

    suffix = http.get(path, headers={"Range": "bytes=-3"})
    open_ended = http.get(path, headers={"Range": "bytes=7-"})

    assert (suffix.status_code, suffix.headers["content-range"], suffix.content) == (206, "bytes 7-9/10", b"789")
    assert (open_ended.status_code, open_ended.headers["content-range"], open_ended.content) == (
        206,
        "bytes 7-9/10",
        b"789",
    )


def test_media_range_unit_is_case_insensitive_and_unknown_units_are_ignored(
    media_client: tuple[TestClient, str],
) -> None:
    http, asset_id = media_client
    path = f"/api/v1/vst/v1/storage/file/{asset_id}"

    case_insensitive = http.get(path, headers={"Range": "BYTES=2-4"})
    unknown_unit = http.get(path, headers={"Range": "items=2-4"})

    assert (
        case_insensitive.status_code,
        case_insensitive.headers["content-range"],
        case_insensitive.content,
    ) == (206, "bytes 2-4/10", b"234")
    assert (unknown_unit.status_code, unknown_unit.content) == (200, b"0123456789")


@pytest.mark.parametrize(
    "range_header",
    [
        "bytes=",
        "bytes=abc-def",
        "bytes=4-2",
        "bytes=0-1,3-4",
        "bytes=-0",
        "bytes=+1-2",
        "bytes=1-+2",
        "bytes=1 -2",
        "bytes=1- 2",
        f"bytes={'9' * 4_301}-",
        f"bytes=1-{'9' * 4_301}",
        f"bytes=-{'9' * 4_301}",
    ],
)
def test_media_rejects_malformed_or_unsupported_ranges(
    media_client: tuple[TestClient, str],
    range_header: str,
) -> None:
    http, asset_id = media_client

    response = http.get(
        f"/api/v1/vst/v1/storage/file/{asset_id}",
        headers={"Range": range_header},
    )

    assert (response.status_code, response.headers["content-range"]) == (416, "bytes */10")


def test_media_closes_file_when_asgi_send_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root)
    real_open = Path.open
    opened: list[Any] = []

    def tracking_open(candidate: Path, *args: object, **kwargs: object) -> Any:
        media = real_open(candidate, *args, **kwargs)
        opened.append(media)
        return media

    monkeypatch.setattr(Path, "open", tracking_open)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/v1/vst/v1/storage/file/{asset_id}",
        "raw_path": f"/api/v1/vst/v1/storage/file/{asset_id}".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def run_response() -> None:
        response = await recorded_video_vst.media(asset_id, Request(scope))

        async def receive() -> dict[str, str]:
            return {"type": "http.request"}

        async def fail_on_body(message: dict[str, object]) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(scope, receive, fail_on_body)

    asyncio.run(run_response())

    assert opened and opened[0].closed


def test_empty_media_supports_full_response_and_rejects_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root)
    source = data_root / "assets" / asset_id / "source" / "original.mp4"
    source.write_bytes(b"")
    app = FastAPI()
    app.include_router(recorded_video_vst.router)
    http = TestClient(app)
    path = f"/api/v1/vst/v1/storage/file/{asset_id}"

    full = http.get(path)
    ranged = http.get(path, headers={"Range": "bytes=0-"})

    assert (full.status_code, full.headers["content-length"], full.content) == (200, "0", b"")
    assert (ranged.status_code, ranged.headers["content-range"]) == (416, "bytes */0")


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


def test_mkv_without_playback_proxy_returns_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vsa_agent.api import recorded_video_vst

    data_root = tmp_path / "recorded-video"
    config = AppConfig(recorded_video=RecordedVideoConfig(data_root=data_root, max_upload_bytes=1_024))
    monkeypatch.setattr(recorded_video_vst, "get_config", lambda: config)
    asset_id = _seed_ready_asset(data_root, extension="mkv")
    app = FastAPI()
    app.include_router(recorded_video_vst.router)

    response = TestClient(app).get(f"/api/v1/vst/v1/storage/file/{asset_id}")

    assert response.status_code == 404
