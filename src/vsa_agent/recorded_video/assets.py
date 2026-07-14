"""Local filesystem storage for recorded-video assets."""

from __future__ import annotations

import errno
import inspect
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Awaitable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Protocol

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, UploadSession

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ALLOWED_SOURCE_EXTENSIONS = frozenset({"mkv", "mp4"})
_WINDOWS_DISK_FULL = 112
_DISK_QUOTA_EXCEEDED = getattr(errno, "EDQUOT", 122)


class StorageUsage(NamedTuple):
    total: int
    used: int
    free: int


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
        self._publication_locks: dict[Path, threading.Lock] = {}
        self._publication_locks_guard = threading.RLock()

    async def create_session(self, session: UploadSession) -> Path:
        chunks = self._session_dir(session.session_id) / "chunks"
        try:
            chunks.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        return chunks.parent

    async def remove_session(self, session_id: str) -> None:
        """Remove one validated, store-owned upload session directory."""
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return
        try:
            shutil.rmtree(session_dir)
        except OSError as error:
            self._raise_storage_error(error)
            raise

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
                    self._raise_hard_link_error(error)
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
        temporary: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                for chunk in chunks:
                    with chunk.open("rb") as source:
                        shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            self._replace_published_file(temporary, destination)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return str(destination)

    async def write_atomic(self, destination: str | Path, data: bytes) -> str:
        with self._publication_locks_guard:
            return self._write_atomic(destination, data)

    def _write_atomic(self, destination: str | Path, data: bytes) -> str:
        target = self._contained_path(destination)
        temporary: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self._replace_published_file(temporary, target)
        except OSError as error:
            self._raise_storage_error(error)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return str(target)

    def iter_media_range(
        self,
        media_path: str | Path,
        start: int,
        end: int | None = None,
        *,
        chunk_size: int = 64 * 1024,
    ) -> Iterator[bytes]:
        """Yield a bounded byte range and close the file when iteration stops."""
        if start < 0 or (end is not None and end < start):
            raise ValueError("media byte range is invalid")
        if chunk_size <= 0:
            raise ValueError("media chunk size must be positive")
        path = self._contained_path(media_path)
        try:
            with path.open("rb") as media:
                media.seek(start)
                remaining = None if end is None else end - start
                while remaining is None or remaining > 0:
                    read_size = chunk_size if remaining is None else min(chunk_size, remaining)
                    chunk = media.read(read_size)
                    if not chunk:
                        break
                    yield chunk
                    if remaining is not None:
                        remaining -= len(chunk)
        except OSError as error:
            self._raise_storage_error(error)
            raise

    async def resolve_source_path(self, asset: Asset) -> Path:
        """Resolve an existing original source through the controlled asset layout."""
        extension = asset.source_extension.lower().removeprefix(".")
        if extension not in _ALLOWED_SOURCE_EXTENSIONS:
            raise self._unsafe_path_error(asset.source_extension)
        return self._resolve_asset_file(asset.asset_id, Path("source") / f"original.{extension}")

    async def resolve_playback_path(self, asset: Asset) -> Path:
        """Prefer a published browser playback proxy, then fall back to the source."""
        try:
            return self._resolve_asset_file(asset.asset_id, Path("playback") / "proxy.mp4")
        except FileNotFoundError:
            if asset.source_extension.lower().removeprefix(".") != "mp4":
                raise
            return await self.resolve_source_path(asset)

    async def resolve_thumbnail_path(self, asset_id: str, thumbnail_key: str) -> Path:
        """Resolve an existing segment thumbnail without allowing asset-root escapes."""
        if not thumbnail_key or Path(thumbnail_key).is_absolute():
            raise self._unsafe_path_error(thumbnail_key)
        return self._resolve_asset_file(asset_id, Path(thumbnail_key))

    async def free_bytes(self) -> int:
        return (await self.disk_usage()).free

    async def disk_usage(self) -> StorageUsage:
        try:
            usage = shutil.disk_usage(self.root)
            return StorageUsage(total=usage.total, used=usage.used, free=usage.free)
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

    def _asset_root(self, asset_id: str) -> Path:
        return self.root / "assets" / self._validate_component(asset_id, "asset_id")

    def _resolve_asset_file(self, asset_id: str, relative_path: Path) -> Path:
        asset_root = self._asset_root(asset_id)
        resolved = (asset_root / relative_path).resolve()
        if not resolved.is_relative_to(asset_root):
            raise self._unsafe_path_error(relative_path)
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        return resolved

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

    def _replace_published_file(self, temporary: Path, destination: Path) -> None:
        with self._publication_locks_guard:
            lock = self._publication_locks.setdefault(destination, threading.Lock())
        with lock:
            os.replace(temporary, destination)

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

    @classmethod
    def _raise_hard_link_error(cls, error: OSError) -> None:
        cls._raise_storage_error(error)
        raise RecordedVideoError(
            ErrorCode.CONFIGURATION,
            retryable=False,
            message="CONFIGURATION: local filesystem does not support required hard links",
        ) from error
