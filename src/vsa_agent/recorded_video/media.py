"""Deterministic local media probing, frame extraction, and browser proxying."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, Segment

_MAX_REPRESENTATIVE_FRAMES = 16
_MP4_FORMAT_NAMES = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
_BROWSER_VIDEO_CODECS = frozenset({"avc1", "h264"})
_BROWSER_AUDIO_CODECS = frozenset({"aac", "mp3"})

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class MediaProbe:
    """The media properties required by the recorded-video pipeline."""

    duration_ms: int
    width: int
    height: int
    format_names: frozenset[str]
    video_codec: str
    audio_codec: str | None


class MediaProcessor:
    """Run ffprobe/ffmpeg with bounded, shell-free local file operations."""

    def __init__(
        self,
        store: LocalAssetStore | None = None,
        *,
        ffprobe_path: str = "ffprobe",
        ffmpeg_path: str = "ffmpeg",
        timeout_sec: int = 60,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._store = store
        self._ffprobe_path = ffprobe_path
        self._ffmpeg_path = ffmpeg_path
        self._timeout_sec = timeout_sec
        self._runner = runner

    async def probe(self, path: str | Path) -> MediaProbe:
        """Read trusted metadata from ffprobe's JSON output."""
        media_path = Path(path)
        command = [
            self._ffprobe_path,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(media_path),
        ]
        result = await self._run(command)
        if result.returncode != 0:
            raise self._corrupt_media_error()
        try:
            payload = json.loads(result.stdout)
            return self._parse_probe(payload)
        except (TypeError, ValueError, KeyError):
            raise self._corrupt_media_error() from None

    async def extract_representative_frames(
        self,
        source_path: str | Path,
        segment: Segment,
        destination_dir: str | Path,
        *,
        frame_count: int,
    ) -> list[Path]:
        """Extract bounded, evenly spaced JPEGs from one media segment."""
        if not 1 <= frame_count <= _MAX_REPRESENTATIVE_FRAMES:
            raise ValueError(f"frame_count must be within 1..{_MAX_REPRESENTATIVE_FRAMES}")
        duration_ms = segment.end_offset_ms - segment.start_offset_ms
        if duration_ms <= 0:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message="CORRUPT_MEDIA: segment duration must be positive",
            )

        source = Path(source_path)
        directory = Path(destination_dir)
        frames: list[Path] = []
        for index in range(1, frame_count + 1):
            offset_ms = segment.start_offset_ms + duration_ms * index // (frame_count + 1)
            destination = directory / f"{segment.segment_id}-{index:02}.jpg"
            temporary = self._temporary_path(destination)
            try:
                await self._run_ffmpeg(
                    [
                        self._ffmpeg_path,
                        "-v",
                        "error",
                        "-y",
                        "-ss",
                        self._format_seconds(offset_ms),
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        "-f",
                        "image2",
                        str(temporary),
                    ]
                )
                self._publish_generated_file(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            frames.append(destination)
        return frames

    async def ensure_playback_proxy(self, asset: Asset) -> Path:
        """Return a browser-playable source or publish a validated MP4 proxy."""
        store = self._require_store()
        source = await store.resolve_source_path(asset)
        source_probe = await self.probe(source)
        if self._is_directly_playable(source_probe):
            return source

        destination = source.parent.parent / "playback" / "proxy.mp4"
        existing = await self._validated_existing_proxy(asset, destination)
        if existing is not None:
            return existing

        temporary = self._temporary_path(destination)
        try:
            command = self._proxy_command(source, source_probe, temporary)
            await self._run_ffmpeg(command)
            proxy_probe = await self.probe(temporary)
            if not self._has_browser_codecs(proxy_probe):
                raise self._corrupt_media_error()
            self._publish_generated_file(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    async def _validated_existing_proxy(self, asset: Asset, destination: Path) -> Path | None:
        store = self._require_store()
        try:
            existing = await store.resolve_playback_path(asset)
        except FileNotFoundError:
            return None
        if existing != destination:
            return None
        try:
            probe = await self.probe(existing)
        except RecordedVideoError as error:
            if error.code is not ErrorCode.CORRUPT_MEDIA:
                raise
            destination.unlink(missing_ok=True)
            return None
        if self._has_browser_codecs(probe):
            return existing
        destination.unlink(missing_ok=True)
        return None

    def _proxy_command(self, source: Path, probe: MediaProbe, temporary: Path) -> list[str]:
        common = [self._ffmpeg_path, "-v", "error", "-y", "-i", str(source), "-map", "0"]
        if self._has_browser_codecs(probe):
            return [*common, "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(temporary)]
        return [
            *common,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(temporary),
        ]

    async def _run_ffmpeg(self, command: list[str]) -> None:
        result = await self._run(command)
        if result.returncode != 0:
            raise self._corrupt_media_error()

    async def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return await asyncio.to_thread(
                self._runner,
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=self._timeout_sec,
            )
        except FileNotFoundError:
            raise RecordedVideoError(
                ErrorCode.FFMPEG_MISSING,
                retryable=False,
                message="FFMPEG_MISSING: required media binary was not found",
            ) from None
        except (subprocess.TimeoutExpired, OSError):
            raise self._corrupt_media_error() from None

    @staticmethod
    def _parse_probe(payload: Any) -> MediaProbe:
        if not isinstance(payload, dict):
            raise ValueError("ffprobe payload is not an object")
        format_data = payload.get("format")
        streams = payload.get("streams")
        if not isinstance(format_data, dict) or not isinstance(streams, list):
            raise ValueError("ffprobe payload is incomplete")
        duration_ms = round(float(format_data["duration"]) * 1_000)
        if duration_ms <= 0:
            raise ValueError("media duration must be positive")
        video_stream = next(
            (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
            None,
        )
        if video_stream is None:
            raise ValueError("media has no video stream")
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        video_codec = str(video_stream["codec_name"]).lower()
        if width <= 0 or height <= 0 or not video_codec:
            raise ValueError("video stream is invalid")
        audio_stream = next(
            (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
            None,
        )
        audio_codec = str(audio_stream.get("codec_name")).lower() if audio_stream else None
        names = frozenset(name.strip().lower() for name in str(format_data.get("format_name", "")).split(",") if name)
        if not names:
            raise ValueError("container format is missing")
        return MediaProbe(duration_ms, width, height, names, video_codec, audio_codec)

    @staticmethod
    def _has_browser_codecs(probe: MediaProbe) -> bool:
        return probe.video_codec in _BROWSER_VIDEO_CODECS and (
            probe.audio_codec is None or probe.audio_codec in _BROWSER_AUDIO_CODECS
        )

    @classmethod
    def _is_directly_playable(cls, probe: MediaProbe) -> bool:
        return bool(probe.format_names & _MP4_FORMAT_NAMES) and cls._has_browser_codecs(probe)

    @staticmethod
    def _format_seconds(offset_ms: int) -> str:
        return f"{offset_ms / 1_000:g}"

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.stem}.",
            suffix=f".tmp{destination.suffix}",
            delete=False,
        ) as temporary:
            return Path(temporary.name)

    @staticmethod
    def _publish_generated_file(temporary: Path, destination: Path) -> None:
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise MediaProcessor._corrupt_media_error()
        with temporary.open("rb+") as generated:
            os.fsync(generated.fileno())
        os.replace(temporary, destination)

    def _require_store(self) -> LocalAssetStore:
        if self._store is None:
            raise RecordedVideoError(
                ErrorCode.CONFIGURATION,
                retryable=False,
                message="CONFIGURATION: LocalAssetStore is required for playback proxies",
            )
        return self._store

    @staticmethod
    def _corrupt_media_error() -> RecordedVideoError:
        return RecordedVideoError(
            ErrorCode.CORRUPT_MEDIA,
            retryable=False,
            message="CORRUPT_MEDIA: media could not be parsed or processed",
        )
