"""Read-only VST-compatible facade for local recorded-video assets."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from starlette.types import Receive, Scope, Send

from vsa_agent.config import get_config
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, Segment
from vsa_agent.recorded_video.repository import JobRepository

router = APIRouter(prefix="/api/v1/vst", tags=["recorded-video-vst"])
_MILLISECONDS_PER_DAY = 86_400_000
_RANGE_UNIT_PATTERN = re.compile(r"(?P<unit>[!#$%&'*+.^_`|~0-9A-Za-z-]+)=")
_BYTE_RANGE_PATTERN = re.compile(r"(?:(?P<start>[0-9]+)-(?P<end>[0-9]*)|-(?P<suffix>[0-9]+))\Z")


class _MediaStreamingResponse(StreamingResponse):
    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        status_code: int = 200,
        media_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._media_content = content
        super().__init__(content, status_code=status_code, media_type=media_type, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._media_content.aclose()


def _repository_and_store() -> tuple[JobRepository, LocalAssetStore]:
    config = get_config().recorded_video
    return JobRepository(config.data_root / "recorded-video.sqlite3"), LocalAssetStore(config.data_root)


async def _ready_asset(repository: JobRepository, asset_id: str) -> Asset:
    try:
        asset = await repository.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    if asset.status is not AssetStatus.READY or asset.deleted_at is not None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


def _parse_timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{name} must include a timezone")
    return parsed


def _parse_byte_range(header: str, size: int) -> tuple[int, int] | None:
    unit_match = _RANGE_UNIT_PATTERN.match(header)
    if unit_match is None or unit_match.group("unit").casefold() != "bytes":
        return None
    value = header[unit_match.end() :]
    match = _BYTE_RANGE_PATTERN.fullmatch(value)
    if match is None:
        return None
    try:
        suffix_value = match.group("suffix")
        if suffix_value is not None:
            suffix = int(suffix_value)
            if suffix <= 0 or size <= 0:
                return None
            return max(size - suffix, 0), size - 1
        start = int(match.group("start"))
        if start >= size:
            return None
        end_value = match.group("end")
        end = size - 1 if not end_value else min(int(end_value), size - 1)
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _has_unsupported_range_unit(header: str) -> bool:
    match = _RANGE_UNIT_PATTERN.match(header)
    return match is not None and match.group("unit").casefold() != "bytes"


async def _media_chunks(
    store: LocalAssetStore,
    path: Path,
    start: int,
    end: int | None = None,
) -> AsyncIterator[bytes]:
    iterator = store.iter_media_range(path, start, end)
    try:
        async for chunk in iterate_in_threadpool(iterator):
            yield chunk
    finally:
        iterator.close()


def _stream_entry(asset: Asset) -> dict[str, object]:
    return {
        "isMain": True,
        "metadata": {"bitrate": "", "codec": asset.mime_type, "framerate": "", "govlength": "", "resolution": ""},
        "name": asset.display_filename,
        "streamId": asset.asset_id,
        "url": "",
        "vodUrl": "",
    }


def _timeline(segment: Segment, size_megabytes: float) -> dict[str, object]:
    return {
        "startTime": segment.start_time.isoformat(),
        "endTime": segment.end_time.isoformat(),
        "sizeInMegabytes": size_megabytes,
    }


def _timeline_sizes(asset: Asset, segments: list[Segment]) -> list[float]:
    durations = [max(segment.end_offset_ms - segment.start_offset_ms, 0) for segment in segments]
    total_duration = sum(durations)
    if total_duration <= 0:
        return [0.0] * len(segments)
    return [asset.size_bytes * duration / total_duration / 1_000_000 for duration in durations]


def _remaining_storage_days(assets: list[Asset], free_bytes: int) -> float:
    observed = [
        asset for asset in assets if asset.size_bytes > 0 and asset.duration_ms is not None and asset.duration_ms > 0
    ]
    observed_bytes = sum(asset.size_bytes for asset in observed)
    observed_duration_ms = sum(asset.duration_ms or 0 for asset in observed)
    if observed_bytes <= 0 or observed_duration_ms <= 0:
        return 0.0
    return free_bytes * observed_duration_ms / (observed_bytes * _MILLISECONDS_PER_DAY)


def _playback_offsets(asset: Asset, start: datetime, end: datetime) -> tuple[float, float]:
    start_offset = max((start - asset.timeline_origin).total_seconds(), 0.0)
    end_offset = max((end - asset.timeline_origin).total_seconds(), 0.0)
    if asset.duration_ms is not None:
        duration = asset.duration_ms / 1_000
        start_offset = min(start_offset, duration)
        end_offset = min(end_offset, duration)
    return start_offset, max(end_offset, start_offset)


def _format_offset(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


@router.get("/v1/replay/streams")
async def replay_streams() -> list[dict[str, list[dict[str, object]]]]:
    repository, _ = _repository_and_store()
    await repository.initialize()
    return [{asset.asset_id: [_stream_entry(asset)]} for asset in await repository.list_ready_assets()]


@router.get("/v1/sensor/list")
async def sensor_list() -> list[dict[str, str]]:
    repository, _ = _repository_and_store()
    await repository.initialize()
    return [
        {"name": asset.display_filename, "sensorId": asset.asset_id, "state": "online", "type": "recorded"}
        for asset in await repository.list_ready_assets()
    ]


@router.get("/v1/storage/size")
async def storage_size(timelines: bool = False) -> dict[str, object]:
    del timelines
    repository, store = _repository_and_store()
    await repository.initialize()
    assets = await repository.list_ready_assets()
    response: dict[str, object] = {}
    for asset in assets:
        segments = await repository.list_segments(asset.asset_id)
        timeline_sizes = _timeline_sizes(asset, segments)
        response[asset.asset_id] = {
            "sizeInMegabytes": asset.size_bytes / 1_000_000,
            "state": "ready",
            "timelines": [_timeline(segment, size) for segment, size in zip(segments, timeline_sizes, strict=True)],
        }
    usage = await store.disk_usage()
    response["total"] = {
        "remainingStorageDays": _remaining_storage_days(assets, usage.free),
        "sizeInMegabytes": usage.used / 1_000_000,
        "totalAvailableStorageSize": usage.free / 1_000_000,
        "totalDiskCapacity": usage.total / 1_000_000,
    }
    return response


@router.get("/v1/storage/file/{asset_id}/url")
async def storage_file_url(
    asset_id: str,
    request: Request,
    start_time: Annotated[str, Query(alias="startTime")],
    end_time: Annotated[str, Query(alias="endTime")],
) -> dict[str, str | float]:
    start = _parse_timestamp(start_time, "startTime")
    end = _parse_timestamp(end_time, "endTime")
    if end < start:
        raise HTTPException(status_code=400, detail="endTime must not precede startTime")
    repository, _ = _repository_and_store()
    await repository.initialize()
    asset = await _ready_asset(repository, asset_id)
    start_offset, end_offset = _playback_offsets(asset, start, end)
    url = request.url_for("vst_media", asset_id=asset_id).replace(
        fragment=f"t={_format_offset(start_offset)},{_format_offset(end_offset)}"
    )
    return {"videoUrl": str(url), "startTime": start_offset, "endTime": end_offset}


@router.get("/v1/storage/file/{asset_id}", name="vst_media")
async def media(asset_id: str, request: Request) -> Response:
    repository, store = _repository_and_store()
    await repository.initialize()
    asset = await _ready_asset(repository, asset_id)
    try:
        path = await store.resolve_playback_path(asset)
    except (FileNotFoundError, RecordedVideoError) as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    size = path.stat().st_size
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else asset.mime_type
    range_header = request.headers.get("range")
    if range_header is not None and _has_unsupported_range_unit(range_header):
        range_header = None
    if range_header is None:
        return _MediaStreamingResponse(
            _media_chunks(store, path, 0),
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
        )
    byte_range = _parse_byte_range(range_header, size)
    if byte_range is None:
        return Response(status_code=416, headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"})
    start, end = byte_range
    return _MediaStreamingResponse(
        _media_chunks(store, path, start, end + 1),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )


@router.get("/v1/replay/stream/{asset_id}/picture")
async def replay_picture(asset_id: str, start_time: Annotated[str, Query(alias="startTime")]) -> Response:
    timestamp = _parse_timestamp(start_time, "startTime")
    repository, store = _repository_and_store()
    await repository.initialize()
    await _ready_asset(repository, asset_id)
    try:
        segment = await repository.find_segment(asset_id, timestamp)
        if segment.thumbnail_key is None:
            raise KeyError("segment has no thumbnail")
        thumbnail = await store.resolve_thumbnail_path(asset_id, segment.thumbnail_key)
    except (FileNotFoundError, KeyError, RecordedVideoError):
        raise HTTPException(status_code=404, detail="thumbnail not found") from None
    return Response(content=thumbnail.read_bytes(), media_type="image/jpeg")
