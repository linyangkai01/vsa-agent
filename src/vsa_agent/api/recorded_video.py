"""Original UI compatible recorded-video upload endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict

from vsa_agent.config import get_config
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.models import Asset, AssetStatus, UploadSession
from vsa_agent.recorded_video.repository import JobRepository

router = APIRouter()
_ALLOWED_EXTENSIONS = frozenset({"mp4", "mkv"})
_SESSION_TTL = timedelta(days=1)


class CreateRecordedVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str


def _safe_filename(filename: str) -> tuple[str, str]:
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ValueError("filename must be a safe basename")
    if any(not (character.isalnum() or character in {".", "_", "-"}) for character in filename):
        raise ValueError("filename contains unsupported characters")
    suffix = Path(filename).suffix.lower().removeprefix(".")
    if suffix not in _ALLOWED_EXTENSIONS:
        raise ValueError("filename extension must be mp4 or mkv")
    return filename, suffix


def _repository_and_store() -> tuple[JobRepository, LocalAssetStore, int]:
    recorded_video = get_config().recorded_video
    store = LocalAssetStore(recorded_video.data_root)
    repository = JobRepository(recorded_video.data_root / "recorded-video.sqlite3")
    return repository, store, recorded_video.max_upload_bytes


def _header_int(request: Request, name: str) -> int:
    value = request.headers.get(name)
    try:
        return int(value) if value is not None else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc


def _chunk_headers(request: Request) -> tuple[str, int, int, bool, str]:
    identifier = request.headers.get("nvstreamer-identifier", "")
    filename = request.headers.get("nvstreamer-file-name", "")
    chunk_number = _header_int(request, "nvstreamer-chunk-number")
    total_chunks = _header_int(request, "nvstreamer-total-chunks")
    is_last_chunk = request.headers.get("nvstreamer-is-last-chunk", "").lower()
    if not identifier or not filename or is_last_chunk not in {"true", "false"}:
        raise HTTPException(status_code=400, detail="required nvstreamer headers are missing or invalid")
    if not 1 <= chunk_number <= total_chunks:
        raise HTTPException(status_code=400, detail="chunk number must be within total chunks")
    if (is_last_chunk == "true") != (chunk_number == total_chunks):
        raise HTTPException(status_code=400, detail="last chunk header does not match chunk number")
    return identifier, chunk_number, total_chunks, is_last_chunk == "true", filename


@router.post("/api/v1/videos")
async def create_recorded_video(payload: CreateRecordedVideoRequest) -> dict[str, str]:
    try:
        filename, extension = _safe_filename(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository, store, _ = _repository_and_store()
    await repository.initialize()
    now = datetime.now(UTC)
    asset_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    asset = Asset(
        asset_id=asset_id,
        display_filename=filename,
        safe_filename=filename,
        size_bytes=0,
        sha256="",
        mime_type="video/mp4" if extension == "mp4" else "video/x-matroska",
        source_extension=extension,
        timeline_origin=now,
        status=AssetStatus.UPLOADING,
        created_at=now,
        updated_at=now,
    )
    session = UploadSession(
        session_id=session_id,
        identifier=session_id,
        asset_id=asset_id,
        total_chunks=1,
        filename=filename,
        temp_dir=f"uploads/{session_id}",
        status=AssetStatus.UPLOADING,
        expires_at=now + _SESSION_TTL,
    )
    await repository.create_upload_session(asset, session)
    await store.create_session(session)
    return {
        "url": f"/api/v1/vst/v1/storage/file?upload_session_id={session_id}",
        "asset_id": asset_id,
        "upload_session_id": session_id,
    }


@router.post("/api/v1/vst/v1/storage/file")
async def upload_recorded_video_chunk(
    upload_session_id: str,
    request: Request,
    media_file: UploadFile = File(alias="mediaFile"),
) -> dict[str, str | int]:
    identifier, chunk_number, total_chunks, is_last_chunk, header_filename = _chunk_headers(request)
    repository, store, max_upload_bytes = _repository_and_store()
    await repository.initialize()
    try:
        session, asset = await repository.get_upload_context(upload_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="upload session not found") from exc
    if header_filename != session.filename or media_file.filename != session.filename:
        raise HTTPException(status_code=400, detail="chunk filename does not match upload session")

    content = await media_file.read()
    checksum = hashlib.sha256(content).hexdigest()
    path = str(store.root / "uploads" / upload_session_id / "chunks" / f"{chunk_number:06d}.part")
    try:
        created = await repository.reserve_upload_chunk(
            upload_session_id,
            identifier=identifier,
            chunk_number=chunk_number,
            total_chunks=total_chunks,
            checksum=checksum,
            size_bytes=len(content),
            max_upload_bytes=max_upload_bytes,
            path=path,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="upload session not found") from exc
    except ValueError as exc:
        if "maximum upload size" in str(exc):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        if "between" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        if created or not Path(path).is_file():
            await store.write_chunk(session, chunk_number, content)
    except Exception:
        if created:
            await repository.release_reserved_upload_chunk(
                upload_session_id,
                chunk_number,
                checksum,
                size_bytes=len(content),
                path=path,
            )
        raise

    session, asset = await repository.get_upload_context(upload_session_id)
    if not is_last_chunk or session.received_chunks != session.total_chunks:
        return {"chunkCount": session.received_chunks}

    file_path = await store.assemble_source(session, asset)
    return {
        "sensorId": asset.asset_id,
        "streamId": asset.asset_id,
        "filePath": file_path,
        "bytes": await repository.stored_upload_bytes(upload_session_id),
        "chunkCount": session.received_chunks,
    }
