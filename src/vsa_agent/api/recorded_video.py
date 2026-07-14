"""Original UI compatible recorded-video upload endpoints."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from vsa_agent.config import get_config
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, Job, UploadSession
from vsa_agent.recorded_video.ports import SearchProjectionStore
from vsa_agent.recorded_video.repository import JobRepository

router = APIRouter()
_ALLOWED_EXTENSIONS = frozenset({"mp4", "mkv"})
_SESSION_TTL = timedelta(days=1)
_PIPELINE_VERSION = "v1"


class DeletionRepository(Protocol):
    async def prepare_asset_deletion(self, asset_id: str, now: datetime) -> tuple[Asset, bool]: ...

    async def list_asset_upload_session_ids(self, asset_id: str) -> list[str]: ...

    async def completed_deletion_steps(self, asset_id: str) -> set[str]: ...

    async def claim_deletion_step(
        self,
        asset_id: str,
        step: str,
        owner_token: str,
        now: datetime,
        lease_until: datetime,
    ) -> bool: ...

    async def release_deletion_step(self, asset_id: str, step: str, owner_token: str) -> None: ...

    async def record_deletion_step(
        self,
        asset_id: str,
        step: str,
        owner_token: str,
        now: datetime,
    ) -> None: ...

    async def finalize_asset_deletion(self, asset_id: str, now: datetime) -> None: ...


class DeletionAssetStore(Protocol):
    async def remove_derived(self, asset_id: str) -> None: ...

    async def remove_source(self, asset_id: str) -> None: ...

    async def remove_upload_sessions(self, session_ids: Sequence[str]) -> None: ...


@dataclass(frozen=True)
class DeleteResult:
    pending: bool


class AssetNotFoundError(Exception):
    pass


class AssetDeletionConflictError(Exception):
    pass


class DeletionService:
    def __init__(self, repository: DeletionRepository, asset_store: DeletionAssetStore) -> None:
        self.repository = repository
        self.asset_store = asset_store

    async def delete(
        self,
        asset_id: str,
        projection_store: SearchProjectionStore,
    ) -> DeleteResult:
        now = datetime.now(UTC)
        try:
            asset, has_running_jobs = await self.repository.prepare_asset_deletion(asset_id, now)
        except KeyError as exc:
            raise AssetNotFoundError(asset_id) from exc
        if asset.status is AssetStatus.DELETED:
            return DeleteResult(pending=False)
        if asset.status is AssetStatus.UPLOADING:
            raise AssetDeletionConflictError("uploading assets cannot be deleted")
        if has_running_jobs:
            return DeleteResult(pending=True)

        completed = await self.repository.completed_deletion_steps(asset_id)
        upload_session_ids = await self.repository.list_asset_upload_session_ids(asset_id)
        owner_token = str(uuid.uuid4())
        external_steps = (
            ("projection", lambda: projection_store.delete_asset(asset_id)),
            ("derived", lambda: self.asset_store.remove_derived(asset_id)),
            ("source", lambda: self.asset_store.remove_source(asset_id)),
            ("upload", lambda: self.asset_store.remove_upload_sessions(upload_session_ids)),
        )
        for step, operation in external_steps:
            if step in completed:
                continue
            claimed_at = datetime.now(UTC)
            claimed = await self.repository.claim_deletion_step(
                asset_id,
                step,
                owner_token,
                claimed_at,
                claimed_at + timedelta(minutes=5),
            )
            if not claimed:
                if step in await self.repository.completed_deletion_steps(asset_id):
                    completed.add(step)
                    continue
                return DeleteResult(pending=True)
            try:
                await operation()
            except BaseException:
                await self.repository.release_deletion_step(asset_id, step, owner_token)
                raise
            await self.repository.record_deletion_step(
                asset_id,
                step,
                owner_token,
                datetime.now(UTC),
            )
            completed.add(step)
        await self.repository.finalize_asset_deletion(asset_id, datetime.now(UTC))
        return DeleteResult(pending=False)


class CreateRecordedVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str


class CompleteRecordedVideoRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


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


def _assembled_source_exists(store: LocalAssetStore, asset_id: str) -> bool:
    try:
        if str(uuid.UUID(asset_id)) != asset_id:
            return False
    except ValueError:
        return False
    source_root = store.root / "assets" / asset_id / "source"
    return any((source_root / f"original.{extension}").is_file() for extension in _ALLOWED_EXTENSIONS)


def _public_job(job: Job) -> dict[str, object]:
    return {
        "asset_id": job.asset_id,
        "job_id": job.job_id,
        "status": job.status.value,
        "stage": job.stage.value if job.stage else None,
        "attempt": job.attempt,
        "error": "Recorded video processing failed" if job.last_error else None,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "next_run_at": job.next_run_at,
        "heartbeat_at": job.heartbeat_at,
    }


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


def _recorded_video_http_exception(error: RecordedVideoError) -> HTTPException:
    status_code = {
        ErrorCode.CORRUPT_MEDIA: 409,
        ErrorCode.UNSUPPORTED_MEDIA: 409,
        ErrorCode.DISK_FULL: 507,
    }.get(error.code, 500)
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error.code.value, "error_message": str(error)},
    )


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
    try:
        await store.create_session(session)
    except Exception as exc:
        try:
            await store.remove_session(session_id)
        finally:
            await repository.delete_upload_session(session_id, asset_id)
        if isinstance(exc, RecordedVideoError):
            raise _recorded_video_http_exception(exc) from exc
        raise
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
        reservation_token = await repository.reserve_upload_chunk(
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

    session, asset = await repository.get_upload_context(upload_session_id)
    try:
        if reservation_token or not Path(path).is_file():
            await store.write_chunk(session, chunk_number, content)
        if reservation_token:
            confirmed = await repository.confirm_reserved_upload_chunk(
                upload_session_id,
                chunk_number,
                reservation_token,
            )
            if not confirmed:
                raise HTTPException(status_code=409, detail="chunk reservation is no longer owned; retry the upload")
    except Exception as exc:
        if reservation_token:
            await repository.release_reserved_upload_chunk(
                upload_session_id,
                chunk_number,
                reservation_token,
            )
        if isinstance(exc, RecordedVideoError):
            raise _recorded_video_http_exception(exc) from exc
        raise

    session, asset = await repository.get_upload_context(upload_session_id)
    if not is_last_chunk or session.received_chunks != session.total_chunks:
        return {"chunkCount": session.received_chunks}

    try:
        file_path = await store.assemble_source(session, asset)
    except RecordedVideoError as exc:
        raise _recorded_video_http_exception(exc) from exc
    return {
        "sensorId": asset.asset_id,
        "streamId": asset.asset_id,
        "filePath": file_path,
        "bytes": await repository.stored_upload_bytes(upload_session_id),
        "chunkCount": session.received_chunks,
    }


@router.post("/api/v1/videos/{asset_id}/complete", status_code=202)
async def complete_recorded_video(
    asset_id: str,
    payload: CompleteRecordedVideoRequest,
) -> dict[str, str]:
    del payload
    repository, store, _ = _repository_and_store()
    await repository.initialize()
    try:
        await repository.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    if not _assembled_source_exists(store, asset_id):
        raise HTTPException(status_code=409, detail="upload is not assembled")
    try:
        job = await repository.complete_upload(asset_id, _PIPELINE_VERSION)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "asset_id": job.asset_id,
        "job_id": job.job_id,
        "status": job.status.value,
        "status_url": f"/api/v1/jobs/{job.job_id}",
    }


@router.get("/api/v1/jobs/{job_id}")
async def get_recorded_video_job(job_id: str) -> dict[str, object]:
    repository, _, _ = _repository_and_store()
    await repository.initialize()
    try:
        job = await repository.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return _public_job(job)


@router.post("/api/v1/jobs/{job_id}/retry")
async def retry_recorded_video_job(job_id: str) -> dict[str, object]:
    repository, _, _ = _repository_and_store()
    await repository.initialize()
    try:
        job = await repository.retry_failed_job(job_id, datetime.now(UTC))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public_job(job)


@router.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_recorded_video_job(job_id: str) -> dict[str, object]:
    repository, _, _ = _repository_and_store()
    await repository.initialize()
    try:
        job = await repository.request_cancel(job_id, datetime.now(UTC))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return _public_job(job)


@router.delete("/api/v1/videos/{asset_id}")
async def delete_recorded_video(asset_id: str, request: Request) -> Response:
    repository, store, _ = _repository_and_store()
    await repository.initialize()
    projection_store = cast(
        SearchProjectionStore,
        getattr(request.app.state, "recorded_video_projection_store", None),
    )
    if projection_store is None:
        raise HTTPException(status_code=503, detail="recorded-video projection store is unavailable")
    try:
        result = await DeletionService(repository, store).delete(asset_id, projection_store)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except AssetDeletionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.pending:
        return JSONResponse(
            status_code=202,
            content={
                "asset_id": asset_id,
                "status": "pending",
                "pending": True,
                "retry_after_ms": 250,
            },
            headers={"Retry-After": "1"},
        )
    return Response(status_code=204)
