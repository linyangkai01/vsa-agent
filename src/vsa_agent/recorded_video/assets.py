"""Local filesystem storage for recorded-video assets."""

from __future__ import annotations

import errno
import inspect
import os
import re
import shutil
import tempfile
from collections.abc import Awaitable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, UploadSession

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ALLOWED_SOURCE_EXTENSIONS = frozenset({"mkv", "mp4"})
_WINDOWS_DISK_FULL = 112
_DISK_QUOTA_EXCEEDED = getattr(errno, "EDQUOT", 122)


class CleanupRepository(Protocol):
    def list_expired_unreferenced_sessions(
        self,
        now: datetime,
    ) -> Sequence[UploadSession] | Awaitable[Sequence[UploadSession]]: ...


class LocalAssetStore:
    """Store uploads and immutable asset files below one local data root."""

    def __init__(
        self,
        root: str | Path,
        *,
        cleanup_repository: CleanupRepository | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_repository = cleanup_repository

    async def create_session(self, session: UploadSession) -> Path:
        chunks = self._session_dir(session.session_id) / "chunks"
        try:
            chunks.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        return chunks.parent

    async def write_chunk(self, session: UploadSession, ordinal: int, data: bytes) -> str:
        if not 1 <= ordinal <= session.total_chunks:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message=f"chunk ordinal {ordinal} is outside 1..{session.total_chunks}",
            )
        chunk_path = self._session_dir(session.session_id) / "chunks" / f"{ordinal:06}.part"
        temporary: Path | None = None
        try:
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=chunk_path.parent,
                prefix=f".{chunk_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())

            while True:
                try:
                    os.link(temporary, chunk_path)
                    return str(chunk_path)
                except FileExistsError:
                    try:
                        existing = chunk_path.read_bytes()
                    except FileNotFoundError:
                        continue
                    if existing == data:
                        return str(chunk_path)
                    raise RecordedVideoError(
                        ErrorCode.CORRUPT_MEDIA,
                        retryable=False,
                        message=f"chunk {ordinal} already contains different content",
                    )
        except OSError as error:
            self._raise_storage_error(error)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def assemble_source(self, session: UploadSession, asset: Asset) -> str:
        if session.asset_id != asset.asset_id:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message="upload session and asset do not match",
            )
        extension = asset.source_extension.lower().removeprefix(".")
        if extension not in _ALLOWED_SOURCE_EXTENSIONS:
            raise self._unsafe_path_error(asset.source_extension)

        chunks = [
            self._session_dir(session.session_id) / "chunks" / f"{ordinal:06}.part"
            for ordinal in range(1, session.total_chunks + 1)
        ]
        missing = [path.name for path in chunks if not path.is_file()]
        if missing:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message=f"missing upload chunks: {', '.join(missing)}",
            )

        asset_id = self._validate_component(asset.asset_id, "asset_id")
        destination = self.root / "assets" / asset_id / "source" / f"original.{extension}"
        temporary = destination.with_name(f"{destination.name}.tmp")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as output:
                for chunk in chunks:
                    with chunk.open("rb") as source:
                        shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return str(destination)

    async def write_atomic(self, destination: str | Path, data: bytes) -> str:
        target = self._contained_path(destination)
        temporary = target.with_name(f"{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)

    async def open_media_range(self, media_path: str | Path, start: int, end: int | None = None) -> bytes:
        if start < 0 or (end is not None and end < start):
            raise ValueError("media byte range is invalid")
        path = self._contained_path(media_path)
        try:
            with path.open("rb") as media:
                media.seek(start)
                return media.read(None if end is None else end - start)
        except OSError as error:
            self._raise_storage_error(error)
            raise

    async def free_bytes(self) -> int:
        try:
            return shutil.disk_usage(self.root).free
        except OSError as error:
            self._raise_storage_error(error)
            raise

    async def cleanup_expired_sessions(self, now: datetime) -> list[str]:
        if self._cleanup_repository is None:
            raise RecordedVideoError(
                ErrorCode.CONFIGURATION,
                retryable=False,
                message="cleanup repository is required",
            )
        result = self._cleanup_repository.list_expired_unreferenced_sessions(now)
        candidates = await result if inspect.isawaitable(result) else result
        removed: list[str] = []
        for session in candidates:
            if session.expires_at > now:
                raise RecordedVideoError(
                    ErrorCode.CONFIGURATION,
                    retryable=False,
                    message=f"cleanup repository returned unexpired session: {session.session_id}",
                )
            session_dir = self._session_dir(session.session_id)
            if session_dir.exists():
                try:
                    shutil.rmtree(session_dir)
                except OSError as error:
                    self._raise_storage_error(error)
                    raise
                removed.append(session.session_id)
        return removed

    def _session_dir(self, session_id: str) -> Path:
        return self.root / "uploads" / self._validate_component(session_id, "session_id")

    def _validate_component(self, value: str, name: str) -> str:
        if _SAFE_COMPONENT.fullmatch(value) is None or value in {".", ".."}:
            raise RecordedVideoError(
                ErrorCode.CONFIGURATION,
                retryable=False,
                message=f"unsafe {name}",
            )
        return value

    def _contained_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        resolved = (self.root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if resolved == self.root or not resolved.is_relative_to(self.root):
            raise self._unsafe_path_error(path)
        return resolved

    @staticmethod
    def _unsafe_path_error(path: object) -> RecordedVideoError:
        return RecordedVideoError(
            ErrorCode.UNSUPPORTED_MEDIA,
            retryable=False,
            message=f"UNSAFE_FILENAME: {path}",
        )

    @staticmethod
    def _raise_storage_error(error: OSError) -> None:
        disk_full_errnos = {errno.ENOSPC, _DISK_QUOTA_EXCEEDED}
        if error.errno in disk_full_errnos or getattr(error, "winerror", None) == _WINDOWS_DISK_FULL:
            raise RecordedVideoError(
                ErrorCode.DISK_FULL,
                retryable=False,
                message="DISK_FULL: insufficient space for recorded-video asset",
            ) from error
