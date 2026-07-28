"""Download, verify, probe, and derive pinned real business-video fixtures."""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from vsa_agent.recorded_video.business_manifest import (
    BusinessBaselineManifest,
    BusinessCase,
    VideoSource,
    load_business_manifest,
)

_COPY_CHUNK_BYTES = 1024 * 1024
_DOWNLOAD_TIMEOUT_SEC = 30.0 * 60.0
_MEDIA_TOOL_TIMEOUT_SEC = 10.0 * 60.0


class DatasetPreparationError(RuntimeError):
    """The external video dataset cannot be reproduced from its manifest."""


@dataclass(frozen=True, slots=True)
class PreparedDataset:
    manifest: BusinessBaselineManifest
    root: Path
    resolved_manifest_path: Path
    source_paths: dict[str, Path]
    clip_paths: dict[str, Path]


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _default_runner(arguments: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(arguments, timeout, output=stdout, stderr=stderr) from error
    return subprocess.CompletedProcess(arguments, process.returncode, stdout=stdout, stderr=stderr)


def _run(
    arguments: list[str],
    operation: str,
    runner: CommandRunner,
    *,
    timeout_sec: float,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(arguments, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        raise DatasetPreparationError(f"{operation} timed out after {timeout_sec:g} seconds") from None
    except OSError as error:
        raise DatasetPreparationError(f"{operation} could not start: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise DatasetPreparationError(f"{operation} failed: {detail}")
    return result


def _verify_identity(path: Path, *, expected_size: int | None, expected_sha256: str, label: str) -> None:
    try:
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_file():
            raise OSError("not a regular file")
        observed_size = resolved.stat().st_size
        observed_hash = sha256_file(resolved)
    except OSError as error:
        raise DatasetPreparationError(f"{label} is unreadable: {error}") from None
    if expected_size is not None and observed_size != expected_size:
        raise DatasetPreparationError(f"{label} size mismatch: expected {expected_size}, observed {observed_size}")
    if observed_hash != expected_sha256:
        raise DatasetPreparationError(f"{label} sha256 mismatch: expected {expected_sha256}, observed {observed_hash}")


def _content_length(response: httpx.Response, source: VideoSource) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        observed = int(value)
    except ValueError:
        raise DatasetPreparationError(f"source {source.source_id} returned an invalid Content-Length") from None
    if observed < 0:
        raise DatasetPreparationError(f"source {source.source_id} returned an invalid Content-Length")
    if observed != source.size_bytes:
        raise DatasetPreparationError(
            f"source {source.source_id} Content-Length mismatch: expected {source.size_bytes}, observed {observed}"
        )
    return observed


def _download_source(source: VideoSource, target: Path, *, timeout_sec: float) -> None:
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.part"
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_sec
    try:
        timeout = httpx.Timeout(
            connect=min(30.0, timeout_sec),
            read=min(60.0, timeout_sec),
            write=min(30.0, timeout_sec),
            pool=min(30.0, timeout_sec),
        )
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            with client.stream("GET", source.download_url) as response:
                response.raise_for_status()
                _content_length(response, source)
                observed_size = 0
                with temporary.open("xb") as output:
                    for chunk in response.iter_bytes(_COPY_CHUNK_BYTES):
                        if time.monotonic() >= deadline:
                            raise DatasetPreparationError(
                                f"source {source.source_id} download timed out after {timeout_sec:g} seconds"
                            )
                        observed_size += len(chunk)
                        if observed_size > source.size_bytes:
                            raise DatasetPreparationError(
                                f"source {source.source_id} exceeded manifest size: "
                                f"expected {source.size_bytes}, observed at least {observed_size}"
                            )
                        output.write(chunk)
                    if time.monotonic() >= deadline:
                        raise DatasetPreparationError(
                            f"source {source.source_id} download timed out after {timeout_sec:g} seconds"
                        )
                    if observed_size != source.size_bytes:
                        raise DatasetPreparationError(
                            f"source {source.source_id} download size mismatch at EOF: "
                            f"expected {source.size_bytes}, observed {observed_size}"
                        )
                    output.flush()
                    os.fsync(output.fileno())
        _verify_identity(
            temporary,
            expected_size=source.size_bytes,
            expected_sha256=source.sha256,
            label=f"downloaded source {source.source_id}",
        )
        os.replace(temporary, target)
    except (httpx.HTTPError, OSError) as error:
        raise DatasetPreparationError(f"source {source.source_id} download failed: {error}") from None
    finally:
        temporary.unlink(missing_ok=True)


def _probe_source(
    path: Path,
    source: VideoSource,
    ffprobe_path: str,
    runner: CommandRunner,
    *,
    timeout_sec: float,
) -> None:
    result = _run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        f"probe source {source.source_id}",
        runner,
        timeout_sec=timeout_sec,
    )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        media_format = payload["format"]
        observed = {
            "codec": stream["codec_name"],
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "duration": float(media_format["duration"]),
            "size": int(media_format["size"]),
        }
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise DatasetPreparationError(f"probe source {source.source_id} returned invalid JSON") from None
    if observed["codec"] != source.codec or observed["width"] != source.width or observed["height"] != source.height:
        raise DatasetPreparationError(f"source {source.source_id} video stream does not match manifest")
    if observed["size"] != source.size_bytes or abs(observed["duration"] - source.duration_sec) > 0.05:
        raise DatasetPreparationError(f"source {source.source_id} media format does not match manifest")


def _clip_command(ffmpeg_path: str, source_path: Path, case: BusinessCase, target: Path) -> list[str]:
    duration = case.clip.end_sec - case.clip.start_sec
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{case.clip.start_sec:g}",
        "-i",
        str(source_path),
        "-t",
        f"{duration:g}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-c:v",
        "libopenh264",
        "-b:v",
        "2M",
        "-maxrate",
        "2M",
        "-bufsize",
        "4M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(target),
    ]


def _write_resolved_manifest(path: Path, manifest: BusinessBaselineManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    payload: dict[str, Any] = manifest.model_dump(mode="json")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_business_dataset(
    manifest_path: Path,
    root: Path,
    *,
    download_missing: bool = True,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    runner: CommandRunner | None = None,
    download_timeout_sec: float = _DOWNLOAD_TIMEOUT_SEC,
    media_tool_timeout_sec: float = _MEDIA_TOOL_TIMEOUT_SEC,
) -> PreparedDataset:
    """Materialize only manifest-pinned sources and clips under one external data root."""

    if not math.isfinite(download_timeout_sec) or download_timeout_sec <= 0:
        raise ValueError("download_timeout_sec must be a positive finite number")
    if not math.isfinite(media_tool_timeout_sec) or media_tool_timeout_sec <= 0:
        raise ValueError("media_tool_timeout_sec must be a positive finite number")

    manifest = load_business_manifest(manifest_path)
    dataset_root = Path(root).resolve(strict=False)
    sources_root = dataset_root / "sources"
    clips_root = dataset_root / "clips"
    sources_root.mkdir(parents=True, exist_ok=True)
    clips_root.mkdir(parents=True, exist_ok=True)
    command_runner = runner or _default_runner

    source_paths: dict[str, Path] = {}
    for source in manifest.sources:
        target = sources_root / source.filename
        if not target.exists():
            if not download_missing:
                raise DatasetPreparationError(f"source {source.source_id} is missing and downloads are disabled")
            _download_source(source, target, timeout_sec=download_timeout_sec)
        _verify_identity(
            target,
            expected_size=source.size_bytes,
            expected_sha256=source.sha256,
            label=f"source {source.source_id}",
        )
        _probe_source(
            target,
            source,
            ffprobe_path,
            command_runner,
            timeout_sec=media_tool_timeout_sec,
        )
        source_paths[source.source_id] = target.resolve()

    clip_paths: dict[str, Path] = {}
    for case in manifest.cases:
        target = clips_root / case.clip.filename
        if not target.exists():
            temporary = clips_root / f".{target.name}.{uuid.uuid4().hex}.tmp.mp4"
            try:
                _run(
                    _clip_command(ffmpeg_path, source_paths[case.source_id], case, temporary),
                    f"derive clip {case.case_id}",
                    command_runner,
                    timeout_sec=media_tool_timeout_sec,
                )
                _verify_identity(
                    temporary,
                    expected_size=None,
                    expected_sha256=case.clip.sha256,
                    label=f"derived clip {case.case_id}",
                )
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        _verify_identity(
            target,
            expected_size=None,
            expected_sha256=case.clip.sha256,
            label=f"clip {case.case_id}",
        )
        clip_paths[case.case_id] = target.resolve()

    resolved_manifest_path = dataset_root / "resolved-manifest.yaml"
    _write_resolved_manifest(resolved_manifest_path, manifest)
    return PreparedDataset(
        manifest=manifest,
        root=dataset_root,
        resolved_manifest_path=resolved_manifest_path,
        source_paths=source_paths,
        clip_paths=clip_paths,
    )


__all__ = [
    "DatasetPreparationError",
    "PreparedDataset",
    "prepare_business_dataset",
    "sha256_file",
]
