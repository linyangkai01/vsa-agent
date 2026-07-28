from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from vsa_agent.recorded_video import business_preparation
from vsa_agent.recorded_video.business_preparation import (
    DatasetPreparationError,
    prepare_business_dataset,
)

from .test_business_manifest import _manifest_payload


def _write_manifest(tmp_path: Path, source_bytes: bytes, clip_bytes: bytes) -> Path:
    payload = _manifest_payload()
    source = payload["sources"][0]
    source["size_bytes"] = len(source_bytes)
    source["sha256"] = hashlib.sha256(source_bytes).hexdigest()
    for case in payload["cases"]:
        case["clip"]["sha256"] = hashlib.sha256(clip_bytes).hexdigest()
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


class _FakeMediaRunner:
    def __init__(self, *, clip_bytes: bytes) -> None:
        self.clip_bytes = clip_bytes
        self.commands: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, arguments: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        self.commands.append(arguments)
        self.timeouts.append(timeout)
        if "-show_entries" in arguments:
            source_path = Path(arguments[-1])
            payload = {
                "streams": [{"codec_name": "h264", "width": 1280, "height": 720}],
                "format": {"duration": "120.0", "size": str(source_path.stat().st_size)},
            }
            return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")
        Path(arguments[-1]).write_bytes(self.clip_bytes)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def _install_download_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: tuple[bytes, ...],
    headers: dict[str, str] | None = None,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, headers=headers, stream=_ChunkStream(*chunks)))
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(business_preparation.httpx, "Client", lambda **_kwargs: client)


def _assert_no_download_artifacts(root: Path) -> None:
    sources = root / "sources"
    assert not (sources / "forklift-safety.mp4").exists()
    assert list(sources.glob("*.part")) == []
    assert list(sources.glob(".*.part")) == []


def test_prepare_reuses_verified_sources_and_derives_all_pinned_clips(tmp_path: Path) -> None:
    source_bytes = b"source-video"
    clip_bytes = b"derived-clip"
    manifest_path = _write_manifest(tmp_path, source_bytes, clip_bytes)
    root = tmp_path / "dataset"
    sources = root / "sources"
    sources.mkdir(parents=True)
    (sources / "forklift-safety.mp4").write_bytes(source_bytes)
    runner = _FakeMediaRunner(clip_bytes=clip_bytes)

    prepared = prepare_business_dataset(
        manifest_path,
        root,
        download_missing=False,
        ffmpeg_path="ffmpeg-test",
        ffprobe_path="ffprobe-test",
        runner=runner,
        media_tool_timeout_sec=7.5,
    )

    assert prepared.resolved_manifest_path.is_file()
    assert len(prepared.clip_paths) == 6
    assert all(path.read_bytes() == clip_bytes for path in prepared.clip_paths.values())
    assert sum(command[0] == "ffmpeg-test" for command in runner.commands) == 6
    assert runner.timeouts == [7.5] * 7


def test_prepare_is_idempotent_when_pinned_clips_exist(tmp_path: Path) -> None:
    source_bytes = b"source-video"
    clip_bytes = b"derived-clip"
    manifest_path = _write_manifest(tmp_path, source_bytes, clip_bytes)
    root = tmp_path / "dataset"
    (root / "sources").mkdir(parents=True)
    (root / "clips").mkdir()
    (root / "sources" / "forklift-safety.mp4").write_bytes(source_bytes)
    for case in _manifest_payload()["cases"]:
        (root / "clips" / case["clip"]["filename"]).write_bytes(clip_bytes)
    runner = _FakeMediaRunner(clip_bytes=clip_bytes)

    prepare_business_dataset(manifest_path, root, download_missing=False, runner=runner)

    assert not any("-i" in command for command in runner.commands)


def test_prepare_rejects_changed_source_before_running_ffmpeg(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, b"expected", b"clip")
    root = tmp_path / "dataset"
    (root / "sources").mkdir(parents=True)
    (root / "sources" / "forklift-safety.mp4").write_bytes(b"changed")
    runner = _FakeMediaRunner(clip_bytes=b"clip")

    with pytest.raises(DatasetPreparationError, match="size mismatch|sha256 mismatch"):
        prepare_business_dataset(manifest_path, root, download_missing=False, runner=runner)

    assert runner.commands == []


def test_prepare_rejects_missing_source_when_downloads_are_disabled(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, b"source", b"clip")

    with pytest.raises(DatasetPreparationError, match="downloads are disabled"):
        prepare_business_dataset(manifest_path, tmp_path / "dataset", download_missing=False)


def test_prepare_download_accepts_matching_content_length_and_exact_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"source-video"
    clip_bytes = b"derived-clip"
    manifest_path = _write_manifest(tmp_path, source_bytes, clip_bytes)
    root = tmp_path / "dataset"
    _install_download_client(
        monkeypatch,
        chunks=(source_bytes[:4], source_bytes[4:]),
        headers={"Content-Length": str(len(source_bytes))},
    )

    prepared = prepare_business_dataset(
        manifest_path,
        root,
        runner=_FakeMediaRunner(clip_bytes=clip_bytes),
    )

    assert prepared.source_paths["forklift-safety"].read_bytes() == source_bytes


def test_prepare_download_rejects_content_length_mismatch_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"source-video"
    manifest_path = _write_manifest(tmp_path, source_bytes, b"clip")
    root = tmp_path / "dataset"
    _install_download_client(
        monkeypatch,
        chunks=(source_bytes,),
        headers={"Content-Length": str(len(source_bytes) + 1)},
    )

    with pytest.raises(DatasetPreparationError, match="Content-Length mismatch"):
        prepare_business_dataset(manifest_path, root)

    _assert_no_download_artifacts(root)


def test_prepare_download_stops_when_stream_exceeds_manifest_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"expected"
    manifest_path = _write_manifest(tmp_path, source_bytes, b"clip")
    root = tmp_path / "dataset"
    _install_download_client(monkeypatch, chunks=(source_bytes, b"overflow"))

    with pytest.raises(DatasetPreparationError, match="exceeded manifest size"):
        prepare_business_dataset(manifest_path, root)

    _assert_no_download_artifacts(root)


def test_prepare_download_rejects_short_stream_at_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"expected"
    manifest_path = _write_manifest(tmp_path, source_bytes, b"clip")
    root = tmp_path / "dataset"
    _install_download_client(monkeypatch, chunks=(source_bytes[:-1],))

    with pytest.raises(DatasetPreparationError, match="size mismatch at EOF"):
        prepare_business_dataset(manifest_path, root)

    _assert_no_download_artifacts(root)


def test_prepare_download_enforces_overall_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"expected"
    manifest_path = _write_manifest(tmp_path, source_bytes, b"clip")
    root = tmp_path / "dataset"
    _install_download_client(monkeypatch, chunks=(source_bytes,))
    ticks = iter((10.0, 12.0))
    monkeypatch.setattr(business_preparation.time, "monotonic", lambda: next(ticks))

    with pytest.raises(DatasetPreparationError, match="download timed out after 1 seconds"):
        prepare_business_dataset(manifest_path, root, download_timeout_sec=1.0)

    _assert_no_download_artifacts(root)


@pytest.mark.parametrize(
    ("timeout_program", "operation"),
    [("ffprobe-test", "probe source"), ("ffmpeg-test", "derive clip")],
)
def test_prepare_normalizes_media_tool_timeouts(
    tmp_path: Path,
    timeout_program: str,
    operation: str,
) -> None:
    source_bytes = b"source-video"
    manifest_path = _write_manifest(tmp_path, source_bytes, b"clip")
    root = tmp_path / "dataset"
    (root / "sources").mkdir(parents=True)
    (root / "sources" / "forklift-safety.mp4").write_bytes(source_bytes)

    def runner(arguments: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        assert timeout == 2.5
        if arguments[0] == timeout_program:
            raise subprocess.TimeoutExpired(arguments, timeout)
        source_path = Path(arguments[-1])
        payload: dict[str, Any] = {
            "streams": [{"codec_name": "h264", "width": 1280, "height": 720}],
            "format": {"duration": "120.0", "size": str(source_path.stat().st_size)},
        }
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")

    with pytest.raises(DatasetPreparationError, match=rf"{operation}.*timed out"):
        prepare_business_dataset(
            manifest_path,
            root,
            ffprobe_path="ffprobe-test",
            ffmpeg_path="ffmpeg-test",
            runner=runner,
            media_tool_timeout_sec=2.5,
        )
