"""Read-only VST-compatible facade for local recorded-video assets."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from vsa_agent.config import get_config
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.models import Asset, AssetStatus, Segment
from vsa_agent.recorded_video.repository import JobRepository

router = APIRouter(prefix="/api/v1/vst", tags=["recorded-video-vst"])


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
    if not header.startswith("bytes=") or "," in header:
        return None
    value = header.removeprefix("bytes=").strip()
    if value.count("-") != 1:
        return None
    start_value, end_value = value.split("-", maxsplit=1)
    try:
        if not start_value:
            suffix = int(end_value)
            if suffix <= 0 or size <= 0:
                return None
            return max(size - suffix, 0), size - 1
        start = int(start_value)
        if start < 0 or start >= size:
            return None
        end = size - 1 if not end_value else min(int(end_value), size - 1)
        if end < start:
            return None
        return start, end
    except ValueError:
        return None


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
    repository, _ = _repository_and_store()
    await repository.initialize()
    assets = await repository.list_ready_assets()
    response: dict[str, object] = {}
    for asset in assets:
        segments = await repository.list_segments(asset.asset_id)
        timeline_size = asset.size_bytes / 1_000_000 / len(segments) if segments else 0
        response[asset.asset_id] = {
            "sizeInMegabytes": asset.size_bytes / 1_000_000,
            "state": "ready",
            "timelines": [_timeline(segment, timeline_size) for segment in segments],
        }
    total_bytes = await repository.ready_storage_bytes()
    total_megabytes = total_bytes / 1_000_000
    response["total"] = {
        "remainingStorageDays": 0,
        "sizeInMegabytes": total_megabytes,
        "totalAvailableStorageSize": total_megabytes,
        "totalDiskCapacity": total_megabytes,
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    size = path.stat().st_size
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else asset.mime_type
    range_header = request.headers.get("range")
    if range_header is None:
        content = await store.open_media_range(path, 0)
        return Response(content=content, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    byte_range = _parse_byte_range(range_header, size)
    if byte_range is None:
        return Response(status_code=416, headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"})
    start, end = byte_range
    content = await store.open_media_range(path, start, end + 1)
    return Response(
        content=content,
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
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="thumbnail not found") from None
    return Response(content=thumbnail.read_bytes(), media_type="image/jpeg")
