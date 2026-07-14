from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.media import MediaProcessor
from vsa_agent.recorded_video.models import Asset, AssetStatus, Segment

NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


def _asset(*, asset_id: str = "asset-uuid", extension: str = "mkv") -> Asset:
    return Asset(
        asset_id=asset_id,
        display_filename=f"recording.{extension}",
        safe_filename=f"recording.{extension}",
        size_bytes=10,
        sha256="sha256",
        mime_type="video/x-matroska" if extension == "mkv" else "video/mp4",
        source_extension=extension,
        timeline_origin=NOW,
        status=AssetStatus.PROCESSING,
        created_at=NOW,
        updated_at=NOW,
    )


def _segment(*, start_offset_ms: int = 0, end_offset_ms: int = 8_000) -> Segment:
    return Segment(
        segment_id="segment-uuid",
        asset_id="asset-uuid",
        pipeline_version="v1",
        ordinal=0,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
        start_time=NOW,
        end_time=NOW,
    )


def _probe_payload(*, container: str = "matroska", video_codec: str = "h264", audio_codec: str = "aac") -> str:
    return json.dumps(
        {
            "format": {"format_name": container, "duration": "12.5"},
            "streams": [
                {"codec_type": "video", "codec_name": video_codec, "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": audio_codec},
            ],
        }
    )


def _probe_payload_with_values(*, duration: object = "12.5", width: object = 1920, height: object = 1080) -> str:
    return json.dumps(
        {
            "format": {"format_name": "matroska", "duration": duration},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": width, "height": height},
            ],
        }
    )


class FakeRunner:
    def __init__(self, payload: str | None = None, generated_payload: str | None = None) -> None:
        self.payload = payload or _probe_payload()
        self.generated_payload = generated_payload or _probe_payload(container="mov,mp4,m4a,3gp,3g2,mj2")
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs))
        if args[0] == "ffprobe":
            path = Path(args[-1])
            payload = self.generated_payload if "proxy" in path.name or ".tmp." in path.name else self.payload
            return subprocess.CompletedProcess(args, 0, stdout=payload, stderr="")
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"generated-media")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


@pytest.fixture
def store(tmp_path: Path) -> LocalAssetStore:
    return LocalAssetStore(tmp_path)


async def test_probe_uses_json_argv_and_parses_media_metadata(tmp_path: Path) -> None:
    source = tmp_path / "original.mp4"
    source.write_bytes(b"source")
    runner = FakeRunner(_probe_payload(container="mov,mp4,m4a,3gp,3g2,mj2"))
    processor = MediaProcessor(runner=runner, timeout_sec=17)

    probe = await processor.probe(source)

    assert probe.duration_ms == 12_500
    assert (probe.width, probe.height) == (1920, 1080)
    assert probe.video_codec == "h264"
    assert probe.audio_codec == "aac"
    assert runner.calls == [
        (
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
            {"capture_output": True, "check": False, "text": True, "timeout": 17},
        )
    ]


async def test_probe_classifies_missing_binary_and_corrupt_media(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.mkv"
    source.write_bytes(b"not-media")

    def missing_runner(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(RecordedVideoError, match="FFMPEG_MISSING") as missing:
        await MediaProcessor(runner=missing_runner).probe(source)
    assert missing.value.code is ErrorCode.FFMPEG_MISSING
    assert missing.value.retryable is False

    def corrupt_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="invalid data")

    with pytest.raises(RecordedVideoError, match="CORRUPT_MEDIA") as corrupt:
        await MediaProcessor(runner=corrupt_runner).probe(source)
    assert corrupt.value.code is ErrorCode.CORRUPT_MEDIA
    assert corrupt.value.retryable is False


@pytest.mark.parametrize(
    ("duration", "width", "height"),
    [
        ("NaN", 1920, 1080),
        ("Infinity", 1920, 1080),
        ("-Infinity", 1920, 1080),
        ("12.5", float("nan"), 1080),
        ("12.5", float("inf"), 1080),
        ("12.5", 1920, float("-inf")),
    ],
)
async def test_probe_rejects_nonfinite_numeric_values_as_corrupt_media(
    tmp_path: Path,
    duration: object,
    width: object,
    height: object,
) -> None:
    source = tmp_path / "nonfinite.mkv"
    source.write_bytes(b"source")
    runner = FakeRunner(_probe_payload_with_values(duration=duration, width=width, height=height))

    with pytest.raises(RecordedVideoError, match="CORRUPT_MEDIA") as corrupt:
        await MediaProcessor(runner=runner).probe(source)

    assert corrupt.value.code is ErrorCode.CORRUPT_MEDIA
    assert corrupt.value.retryable is False


async def test_extract_representative_frames_is_evenly_spaced_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "original.mkv"
    source.write_bytes(b"source")
    runner = FakeRunner()
    processor = MediaProcessor(runner=runner)

    frames = await processor.extract_representative_frames(
        source,
        _segment(),
        tmp_path / "thumbnails",
        frame_count=3,
    )

    assert [frame.name for frame in frames] == ["segment-uuid-01.jpg", "segment-uuid-02.jpg", "segment-uuid-03.jpg"]
    assert all(frame.read_bytes() == b"generated-media" for frame in frames)
    frame_calls = [args for args, _kwargs in runner.calls if args[0] == "ffmpeg"]
    assert [call[call.index("-ss") + 1] for call in frame_calls] == ["2", "4", "6"]
    with pytest.raises(ValueError, match="frame_count"):
        await processor.extract_representative_frames(source, _segment(), tmp_path / "too-many", frame_count=17)


async def test_compatible_mp4_reuses_source_without_invoking_ffmpeg(store: LocalAssetStore) -> None:
    asset = _asset(extension="mp4")
    source = Path(await store.write_atomic("assets/asset-uuid/source/original.mp4", b"source"))
    runner = FakeRunner(_probe_payload(container="mov,mp4,m4a,3gp,3g2,mj2"))
    processor = MediaProcessor(store=store, runner=runner)

    playback = await processor.ensure_playback_proxy(asset)

    assert playback == source
    assert [args[0] for args, _kwargs in runner.calls] == ["ffprobe"]


async def test_mkv_remuxes_or_transcodes_then_reuses_a_valid_proxy(store: LocalAssetStore) -> None:
    asset = _asset(extension="mkv")
    await store.write_atomic("assets/asset-uuid/source/original.mkv", b"source")
    runner = FakeRunner()
    processor = MediaProcessor(store=store, runner=runner)

    proxy = await processor.ensure_playback_proxy(asset)
    reused = await processor.ensure_playback_proxy(asset)

    assert proxy == store.root / "assets" / asset.asset_id / "playback" / "proxy.mp4"
    assert reused == proxy
    ffmpeg_calls = [args for args, _kwargs in runner.calls if args[0] == "ffmpeg"]
    assert len(ffmpeg_calls) == 1
    assert ffmpeg_calls[0][ffmpeg_calls[0].index("-c") + 1] == "copy"
    assert all("shell" not in kwargs for _args, kwargs in runner.calls)

    incompatible = FakeRunner(_probe_payload(video_codec="hevc", audio_codec="opus"))
    await store.remove_derived(asset.asset_id)
    transcoding_processor = MediaProcessor(store=store, runner=incompatible)

    await transcoding_processor.ensure_playback_proxy(asset)

    transcode_call = next(args for args, _kwargs in incompatible.calls if args[0] == "ffmpeg")
    assert transcode_call[transcode_call.index("-c:v") + 1] == "libx264"
    assert transcode_call[transcode_call.index("-c:a") + 1] == "aac"


async def test_existing_proxy_with_mkv_container_is_rebuilt(store: LocalAssetStore) -> None:
    asset = _asset(extension="mkv")
    await store.write_atomic("assets/asset-uuid/source/original.mkv", b"source")
    destination = Path(await store.write_atomic("assets/asset-uuid/playback/proxy.mp4", b"stale-proxy"))
    calls: list[list[str]] = []
    probe_outputs = iter(
        [
            _probe_payload(),
            _probe_payload(container="matroska"),
            _probe_payload(container="mov,mp4,m4a,3gp,3g2,mj2"),
        ]
    )

    def runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 0, stdout=next(probe_outputs), stderr="")
        Path(args[-1]).write_bytes(b"rebuilt-proxy")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    playback = await MediaProcessor(store=store, runner=runner).ensure_playback_proxy(asset)

    assert playback == destination
    assert destination.read_bytes() == b"rebuilt-proxy"
    assert [args[0] for args in calls] == ["ffprobe", "ffprobe", "ffmpeg", "ffprobe"]


async def test_proxy_maps_only_first_video_and_optional_first_audio(store: LocalAssetStore) -> None:
    asset = _asset(extension="mkv")
    await store.write_atomic("assets/asset-uuid/source/original.mkv", b"source")
    payload = json.dumps(
        {
            "format": {"format_name": "matroska", "duration": "12.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "subtitle", "codec_name": "subrip"},
                {"codec_type": "data", "codec_name": "bin_data"},
                {"codec_type": "attachment", "codec_name": "ttf"},
            ],
        }
    )
    runner = FakeRunner(payload)

    await MediaProcessor(store=store, runner=runner).ensure_playback_proxy(asset)

    command = next(args for args, _kwargs in runner.calls if args[0] == "ffmpeg")
    mapped_streams = [command[index + 1] for index, argument in enumerate(command) if argument == "-map"]
    assert mapped_streams == ["0:v:0", "0:a:0?"]
    assert "-sn" in command
    assert "-dn" in command
    assert "0" not in mapped_streams
