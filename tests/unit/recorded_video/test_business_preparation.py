from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

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

    def __call__(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(arguments)
        if "-show_entries" in arguments:
            source_path = Path(arguments[-1])
            payload = {
                "streams": [{"codec_name": "h264", "width": 1280, "height": 720}],
                "format": {"duration": "120.0", "size": str(source_path.stat().st_size)},
            }
            return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")
        Path(arguments[-1]).write_bytes(self.clip_bytes)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")


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
    )

    assert prepared.resolved_manifest_path.is_file()
    assert len(prepared.clip_paths) == 6
    assert all(path.read_bytes() == clip_bytes for path in prepared.clip_paths.values())
    assert sum(command[0] == "ffmpeg-test" for command in runner.commands) == 6


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
