"""SQLite persistence and worker leases for recorded-video ingestion."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import AsyncIterator, Callable, Collection, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import TypeAdapter

from vsa_agent.recorded_video.errors import LeaseLostError
from vsa_agent.recorded_video.models import (
    Asset,
    AssetStatus,
    Job,
    JobStage,
    JobStatus,
    JobStep,
    PipelineVersion,
    Segment,
    UploadSession,
)

_PIPELINE_VERSION_ADAPTER = TypeAdapter(PipelineVersion)
_STAGE_ORDER = {stage: ordinal for ordinal, stage in enumerate(JobStage)}
_SCHEMA_VERSION = 5
_SNAPSHOT_SECTIONS = frozenset({"pipeline", "vision"})
_SNAPSHOT_SECTION_FIELDS = frozenset({"enabled", "model", "thresholds"})
_SNAPSHOT_TOP_LEVEL_FIELDS = frozenset({"pipeline_version", *_SNAPSHOT_SECTIONS})
_DELETION_STEPS = frozenset({"projection", "derived", "source", "upload", "sqlite"})

_MIGRATION_1 = (
    """
    CREATE TABLE assets (
        asset_id TEXT PRIMARY KEY,
        display_filename TEXT NOT NULL,
        safe_filename TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        sha256 TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        source_extension TEXT NOT NULL,
        duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
        width INTEGER CHECK (width IS NULL OR width >= 0),
        height INTEGER CHECK (height IS NULL OR height >= 0),
        timeline_origin TEXT NOT NULL,
        status TEXT NOT NULL,
        current_job_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        FOREIGN KEY (current_job_id) REFERENCES jobs(job_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE upload_sessions (
        session_id TEXT PRIMARY KEY,
        identifier TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        total_chunks INTEGER NOT NULL CHECK (total_chunks > 0),
        received_chunks INTEGER NOT NULL DEFAULT 0 CHECK (
            received_chunks >= 0 AND received_chunks <= total_chunks
        ),
        filename TEXT NOT NULL,
        temp_dir TEXT NOT NULL,
        status TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE upload_chunks (
        upload_chunk_id INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL,
        chunk_number INTEGER NOT NULL CHECK (chunk_number > 0),
        checksum TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        path TEXT,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES upload_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        pipeline_version TEXT NOT NULL CHECK (length(trim(pipeline_version)) > 0),
        status TEXT NOT NULL,
        stage TEXT,
        attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
        next_run_at TEXT,
        lease_owner TEXT,
        lease_until TEXT,
        heartbeat_at TEXT,
        config_snapshot TEXT NOT NULL,
        last_error TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE job_steps (
        job_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        output_manifest TEXT,
        output_checksum TEXT,
        model TEXT,
        elapsed_ms INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
        PRIMARY KEY (job_id, stage),
        FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE segments (
        segment_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        pipeline_version TEXT NOT NULL CHECK (length(trim(pipeline_version)) > 0),
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        start_offset_ms INTEGER NOT NULL CHECK (start_offset_ms >= 0),
        end_offset_ms INTEGER NOT NULL CHECK (end_offset_ms >= start_offset_ms),
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        thumbnail_key TEXT,
        model TEXT,
        prompt_version TEXT,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_upload_sessions_identifier ON upload_sessions(identifier)",
    "CREATE UNIQUE INDEX uq_upload_chunks_session_chunk ON upload_chunks(session_id, chunk_number)",
    "CREATE UNIQUE INDEX uq_jobs_asset_pipeline ON jobs(asset_id, pipeline_version)",
    "CREATE UNIQUE INDEX uq_segments_asset_pipeline_ordinal ON segments(asset_id, pipeline_version, ordinal)",
    "CREATE INDEX ix_jobs_due ON jobs(status, next_run_at, lease_until)",
)

_MIGRATION_2 = (
    "ALTER TABLE upload_chunks ADD COLUMN reservation_token TEXT",
    """
    ALTER TABLE upload_chunks
    ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'
    CHECK (status IN ('reserved', 'confirmed'))
    """,
)

_MIGRATION_3 = ("ALTER TABLE upload_chunks ADD COLUMN reservation_expires_at TEXT",)

_MIGRATION_4 = (
    """
    CREATE TABLE asset_deletion_steps (
        asset_id TEXT NOT NULL,
        step TEXT NOT NULL CHECK (step IN ('projection', 'derived', 'source', 'upload', 'sqlite')),
        completed_at TEXT NOT NULL,
        PRIMARY KEY (asset_id, step),
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
)

_MIGRATION_5 = (
    """
    CREATE TABLE asset_deletion_requests (
        asset_id TEXT PRIMARY KEY,
        requested_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE asset_deletion_step_claims (
        asset_id TEXT NOT NULL,
        step TEXT NOT NULL CHECK (step IN ('projection', 'derived', 'source', 'upload')),
        owner_token TEXT NOT NULL,
        claimed_at TEXT NOT NULL,
        lease_until TEXT NOT NULL,
        PRIMARY KEY (asset_id, step),
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )
    """,
)


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _to_iso(value: datetime | None, name: str = "datetime") -> str | None:
    if value is None:
        return None
    return _require_aware(value, name).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return _require_aware(parsed, "persisted datetime")


def _json_snapshot(snapshot: Mapping[str, Any], allowed_snapshot_models: Collection[str]) -> str:
    _validate_snapshot_metadata(snapshot, allowed_snapshot_models)
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _validate_snapshot_identifier(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"snapshot value must be a short identifier: {path}")
    if value.startswith("data:") or any(char not in "._:-" and not char.isalnum() for char in value):
        raise ValueError(f"snapshot value must be a short identifier: {path}")


def _validate_snapshot_model_reference(value: Any, path: str, allowed_snapshot_models: Collection[str]) -> None:
    if value not in allowed_snapshot_models:
        raise ValueError(f"snapshot model is not allowed: {path}")


def _validate_snapshot_section(value: Any, path: str, allowed_snapshot_models: Collection[str]) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"snapshot section must be an object: {path}")
    for key, item in value.items():
        if key not in _SNAPSHOT_SECTION_FIELDS:
            raise ValueError(f"snapshot key is not allowed: {path}.{key}")
        if key == "model":
            _validate_snapshot_model_reference(item, f"{path}.{key}", allowed_snapshot_models)
        elif key == "enabled":
            if not isinstance(item, bool):
                raise ValueError(f"snapshot value must be boolean: {path}.{key}")
        elif key == "thresholds":
            if not isinstance(item, list | tuple) or len(item) > 16:
                raise ValueError(f"snapshot thresholds must be a short list: {path}.{key}")
            if any(isinstance(threshold, bool) or not isinstance(threshold, int | float) for threshold in item):
                raise ValueError(f"snapshot thresholds must be numeric: {path}.{key}")
            if any(not math.isfinite(threshold) or not 0 <= threshold <= 1 for threshold in item):
                raise ValueError(f"snapshot thresholds must be between 0 and 1: {path}.{key}")


def _validate_snapshot_metadata(snapshot: Mapping[str, Any], allowed_snapshot_models: Collection[str]) -> None:
    if not isinstance(snapshot, Mapping):
        raise ValueError("config_snapshot must be an object")
    for key, value in snapshot.items():
        if key not in _SNAPSHOT_TOP_LEVEL_FIELDS:
            raise ValueError(f"snapshot key is not allowed: config_snapshot.{key}")
        if key == "pipeline_version":
            _validate_snapshot_identifier(value, "config_snapshot.pipeline_version")
        else:
            _validate_snapshot_section(value, f"config_snapshot.{key}", allowed_snapshot_models)


class JobRepository:
    """Concrete file-backed implementation of the recorded-video repository port."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        lease_seconds: int = 120,
        busy_timeout_ms: int = 5_000,
        clock: Callable[[], datetime] | None = None,
        allowed_snapshot_models: Collection[str] = (),
    ) -> None:
        self.database_path = Path(database_path)
        if str(database_path) == ":memory:" or self.database_path.as_posix().startswith("file:"):
            raise ValueError("JobRepository requires a file-backed SQLite database")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.lease_seconds = lease_seconds
        self.busy_timeout_ms = busy_timeout_ms
        self._clock = clock or (lambda: datetime.now(UTC))
        self.allowed_snapshot_models = frozenset(allowed_snapshot_models)

    def _now(self) -> datetime:
        return _require_aware(self._clock(), "clock")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(
            self.database_path,
            isolation_level=None,
            timeout=self.busy_timeout_ms / 1_000,
        )
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            await connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            await connection.close()

    @asynccontextmanager
    async def _transaction(self, connection: aiosqlite.Connection) -> AsyncIterator[None]:
        await connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            await connection.rollback()
            raise
        else:
            await connection.commit()

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._connect() as connection:
            async with self._transaction(connection):
                yield connection

    async def initialize(self) -> None:
        """Create or migrate the database; safe to call repeatedly."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            async with self._transaction(connection):
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                row = await self._fetchone(connection, "SELECT MAX(version) AS version FROM schema_migrations")
                version = int(row["version"] or 0) if row is not None else 0
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"database has newer schema migration {version}; supported version is {_SCHEMA_VERSION}"
                    )
                migrations = {
                    1: _MIGRATION_1,
                    2: _MIGRATION_2,
                    3: _MIGRATION_3,
                    4: _MIGRATION_4,
                    5: _MIGRATION_5,
                }
                for migration_version in range(version + 1, _SCHEMA_VERSION + 1):
                    for statement in migrations[migration_version]:
                        await connection.execute(statement)
                    await connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (migration_version, _to_iso(self._now())),
                    )

    async def create_upload_session(self, asset: Asset, session: UploadSession) -> UploadSession:
        if asset.asset_id != session.asset_id:
            raise ValueError("asset and upload session must refer to the same asset_id")

        async with self._write_transaction() as connection:
            await connection.execute(
                """
                INSERT INTO assets (
                    asset_id, display_filename, safe_filename, size_bytes, sha256, mime_type,
                    source_extension, duration_ms, width, height, timeline_origin, status,
                    current_job_id, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO NOTHING
                """,
                self._asset_parameters(asset),
            )
            try:
                await connection.execute(
                    """
                    INSERT INTO upload_sessions (
                        session_id, identifier, asset_id, total_chunks, received_chunks,
                        filename, temp_dir, status, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.identifier,
                        session.asset_id,
                        session.total_chunks,
                        session.received_chunks,
                        session.filename,
                        session.temp_dir,
                        session.status.value,
                        _to_iso(session.expires_at, "session.expires_at"),
                    ),
                )
            except sqlite3.IntegrityError:
                existing = await self._fetchone(
                    connection,
                    "SELECT * FROM upload_sessions WHERE identifier = ?",
                    (session.identifier,),
                )
                if existing is None or (
                    existing["session_id"] != session.session_id or existing["asset_id"] != session.asset_id
                ):
                    raise
                return self._row_to_upload_session(existing)
        return session

    async def delete_upload_session(self, session_id: str, asset_id: str) -> bool:
        """Remove a newly-created upload session and its otherwise unreferenced asset."""
        async with self._write_transaction() as connection:
            cursor = await connection.execute(
                "DELETE FROM upload_sessions WHERE session_id = ? AND asset_id = ?",
                (session_id, asset_id),
            )
            try:
                deleted = cursor.rowcount == 1
            finally:
                await cursor.close()
            if deleted:
                await connection.execute(
                    """
                    DELETE FROM assets
                    WHERE asset_id = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM upload_sessions WHERE upload_sessions.asset_id = assets.asset_id
                        )
                    """,
                    (asset_id,),
                )
            return deleted

    async def list_expired_unreferenced_sessions(self, now: datetime) -> list[UploadSession]:
        """Return expired sessions whose temporary chunks are no longer needed.

        Uploading sessions remain active. Non-uploading sessions are reclaimable
        only once every expected chunk is present; jobs reference the assembled
        asset by ``asset_id`` rather than this temporary directory.
        """
        cutoff = _to_iso(_require_aware(now, "now"), "now")
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT sessions.*
                FROM upload_sessions AS sessions
                WHERE sessions.expires_at <= ?
                    AND sessions.status != ?
                    AND sessions.received_chunks = sessions.total_chunks
                    AND (
                        SELECT COUNT(*)
                        FROM upload_chunks AS chunks
                        WHERE chunks.session_id = sessions.session_id
                            AND chunks.status = 'confirmed'
                    ) = sessions.total_chunks
                ORDER BY sessions.expires_at, sessions.session_id
                """,
                (cutoff, AssetStatus.UPLOADING.value),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return [self._row_to_upload_session(row) for row in rows]

    async def get_upload_context(self, session_id: str) -> tuple[UploadSession, Asset]:
        """Load the persisted upload session and its asset for an API request."""
        async with self._connect() as connection:
            session_row = await self._fetchone(
                connection,
                "SELECT * FROM upload_sessions WHERE session_id = ?",
                (session_id,),
            )
            if session_row is None:
                raise KeyError(f"unknown upload session: {session_id}")
            asset_row = await self._fetchone(
                connection,
                "SELECT * FROM assets WHERE asset_id = ?",
                (session_row["asset_id"],),
            )
            if asset_row is None:
                raise KeyError(f"unknown asset: {session_row['asset_id']}")
        return self._row_to_upload_session(session_row), self._row_to_asset(asset_row)

    async def stored_upload_bytes(self, session_id: str) -> int:
        """Return the durable byte count for chunks reserved by an upload session."""
        async with self._connect() as connection:
            session = await self._fetchone(
                connection,
                "SELECT session_id FROM upload_sessions WHERE session_id = ?",
                (session_id,),
            )
            if session is None:
                raise KeyError(f"unknown upload session: {session_id}")
            row = await self._fetchone(
                connection,
                "SELECT COALESCE(SUM(size_bytes), 0) AS stored_bytes FROM upload_chunks WHERE session_id = ?",
                (session_id,),
            )
        return int(row["stored_bytes"] if row is not None else 0)

    async def reserve_upload_chunk(
        self,
        session_id: str,
        *,
        identifier: str,
        chunk_number: int,
        total_chunks: int,
        checksum: str,
        size_bytes: int,
        max_upload_bytes: int,
        path: str,
    ) -> str | None:
        """Atomically bind an upload and reserve durable quota for one chunk.

        The initial session identifier is its session id. The first chunk replaces
        that placeholder with the client-supplied nvstreamer identifier and fixes
        the initially unknown total chunk count. Recording before filesystem I/O
        makes the size limit safe across concurrent API workers; callers must
        release their token-owned reservation when their write fails. Reservations
        expire after the repository lease so a crashed writer cannot permanently
        consume quota. A matching confirmed row returns ``None`` because no new
        filesystem write is owned.
        """
        if not identifier:
            raise ValueError("upload identifier is required")
        if total_chunks < 1:
            raise ValueError("total_chunks must be positive")
        if size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        if max_upload_bytes < 1:
            raise ValueError("max_upload_bytes must be positive")

        try:
            async with self._write_transaction() as connection:
                session = await self._fetchone(
                    connection,
                    "SELECT * FROM upload_sessions WHERE session_id = ?",
                    (session_id,),
                )
                if session is None:
                    raise KeyError(f"unknown upload session: {session_id}")

                chunk_count_row = await self._fetchone(
                    connection,
                    "SELECT COUNT(*) AS chunk_count FROM upload_chunks WHERE session_id = ?",
                    (session_id,),
                )
                is_unbound = int(chunk_count_row["chunk_count"]) == 0
                if is_unbound:
                    await connection.execute(
                        """
                        UPDATE upload_sessions
                        SET identifier = ?, total_chunks = ?
                        WHERE session_id = ?
                        """,
                        (identifier, total_chunks, session_id),
                    )
                elif session["identifier"] != identifier:
                    raise ValueError("upload identifier does not match session")
                elif session["total_chunks"] != total_chunks:
                    raise ValueError("total chunks do not match session")

                if not 1 <= chunk_number <= total_chunks:
                    raise ValueError(f"chunk_number must be between 1 and {total_chunks}")

                now = self._now()
                reservation_expires_at = _to_iso(now + timedelta(seconds=self.lease_seconds))
                existing = await self._fetchone(
                    connection,
                    """
                    SELECT checksum, size_bytes, path, status, reservation_token, reservation_expires_at
                    FROM upload_chunks
                    WHERE session_id = ? AND chunk_number = ?
                    """,
                    (session_id, chunk_number),
                )
                reservation_token = str(uuid.uuid4())
                if existing is not None:
                    if (
                        existing["checksum"] != checksum
                        or existing["size_bytes"] != size_bytes
                        or existing["path"] != path
                    ):
                        raise ValueError("chunk key already contains different content")
                    if existing["status"] == "confirmed":
                        return None
                    expires_at = _from_iso(existing["reservation_expires_at"])
                    if expires_at is not None and expires_at > now:
                        raise ValueError("chunk upload is already being uploaded")
                    cursor = await connection.execute(
                        """
                        UPDATE upload_chunks
                        SET reservation_token = ?, reservation_expires_at = ?, recorded_at = ?
                        WHERE session_id = ? AND chunk_number = ?
                            AND reservation_token = ? AND status = 'reserved'
                        """,
                        (
                            reservation_token,
                            reservation_expires_at,
                            _to_iso(now),
                            session_id,
                            chunk_number,
                            existing["reservation_token"],
                        ),
                    )
                    try:
                        reclaimed = cursor.rowcount == 1
                    finally:
                        await cursor.close()
                    if not reclaimed:
                        raise ValueError("chunk upload is already being uploaded")
                    return reservation_token

                total_row = await self._fetchone(
                    connection,
                    "SELECT COALESCE(SUM(size_bytes), 0) AS stored_bytes FROM upload_chunks WHERE session_id = ?",
                    (session_id,),
                )
                stored_bytes = int(total_row["stored_bytes"] if total_row is not None else 0)
                if stored_bytes + size_bytes > max_upload_bytes:
                    raise ValueError("maximum upload size exceeded")

                await connection.execute(
                    """
                    INSERT INTO upload_chunks (
                        session_id, chunk_number, checksum, size_bytes, path, recorded_at,
                        reservation_token, reservation_expires_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved')
                    """,
                    (
                        session_id,
                        chunk_number,
                        checksum,
                        size_bytes,
                        path,
                        _to_iso(now),
                        reservation_token,
                        reservation_expires_at,
                    ),
                )
                return reservation_token
        except sqlite3.IntegrityError as exc:
            raise ValueError("upload identifier belongs to a different session") from exc

    async def confirm_reserved_upload_chunk(
        self,
        session_id: str,
        chunk_number: int,
        reservation_token: str | None,
    ) -> bool:
        """Count a chunk only when the current reservation owner confirms its write."""
        if not reservation_token:
            return False
        async with self._write_transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE upload_chunks
                SET status = 'confirmed', reservation_expires_at = NULL
                WHERE session_id = ? AND chunk_number = ?
                    AND reservation_token = ? AND status = 'reserved'
                """,
                (session_id, chunk_number, reservation_token),
            )
            try:
                confirmed = cursor.rowcount == 1
            finally:
                await cursor.close()
            if confirmed:
                await self._refresh_received_chunks(connection, session_id)
            return confirmed

    async def release_reserved_upload_chunk(
        self,
        session_id: str,
        chunk_number: int,
        reservation_token: str | None,
    ) -> bool:
        """Release a reservation only while the caller still owns its pending token."""
        if not reservation_token:
            return False
        async with self._write_transaction() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM upload_chunks
                WHERE session_id = ? AND chunk_number = ?
                    AND reservation_token = ? AND status = 'reserved'
                """,
                (session_id, chunk_number, reservation_token),
            )
            try:
                released = cursor.rowcount == 1
            finally:
                await cursor.close()
            if released:
                await self._refresh_received_chunks(connection, session_id)
                await connection.execute(
                    """
                    UPDATE upload_sessions
                    SET identifier = session_id, total_chunks = 1
                    WHERE session_id = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM upload_chunks WHERE upload_chunks.session_id = upload_sessions.session_id
                        )
                    """,
                    (session_id,),
                )
            return released

    async def _refresh_received_chunks(self, connection: aiosqlite.Connection, session_id: str) -> None:
        await connection.execute(
            """
            UPDATE upload_sessions
            SET received_chunks = (
                SELECT COUNT(*)
                FROM upload_chunks
                WHERE session_id = ? AND status = 'confirmed'
            )
            WHERE session_id = ?
            """,
            (session_id, session_id),
        )

    async def record_chunk(
        self,
        session_id: str,
        chunk_number: int,
        checksum: str,
        *,
        size_bytes: int = 0,
        path: str | None = None,
    ) -> None:
        if size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")

        async with self._write_transaction() as connection:
            session = await self._fetchone(
                connection,
                "SELECT total_chunks FROM upload_sessions WHERE session_id = ?",
                (session_id,),
            )
            if session is None:
                raise KeyError(f"unknown upload session: {session_id}")
            if not 1 <= chunk_number <= session["total_chunks"]:
                raise ValueError(f"chunk_number must be between 1 and {session['total_chunks']}")

            existing = await self._fetchone(
                connection,
                "SELECT checksum, size_bytes, path FROM upload_chunks WHERE session_id = ? AND chunk_number = ?",
                (session_id, chunk_number),
            )
            if existing is not None:
                if existing["checksum"] != checksum or existing["size_bytes"] != size_bytes or existing["path"] != path:
                    raise ValueError("chunk key already contains different content")
                return

            await connection.execute(
                """
                    INSERT INTO upload_chunks (
                        session_id, chunk_number, checksum, size_bytes, path, recorded_at,
                        reservation_token, reservation_expires_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'confirmed')
                    """,
                (session_id, chunk_number, checksum, size_bytes, path, _to_iso(self._now())),
            )
            await connection.execute(
                """
                    UPDATE upload_sessions
                    SET received_chunks = (
                        SELECT COUNT(*) FROM upload_chunks WHERE session_id = ? AND status = 'confirmed'
                    )
                    WHERE session_id = ?
                    """,
                (session_id, session_id),
            )

    async def complete_upload(
        self,
        asset_id: str,
        pipeline_version: str,
        *,
        now: datetime | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> Job:
        normalized_pipeline_version = _PIPELINE_VERSION_ADAPTER.validate_python(pipeline_version)
        completed_at = _require_aware(now or self._now(), "now")
        snapshot = dict(config_snapshot or {})

        async with self._write_transaction() as connection:
            asset = await self._fetchone(connection, "SELECT status FROM assets WHERE asset_id = ?", (asset_id,))
            if asset is None:
                raise KeyError(f"unknown asset: {asset_id}")
            deletion_request = await self._fetchone(
                connection,
                "SELECT 1 FROM asset_deletion_requests WHERE asset_id = ?",
                (asset_id,),
            )
            if deletion_request is not None:
                raise ValueError("asset deletion is in progress")

            existing = await self._fetchone(
                connection,
                "SELECT * FROM jobs WHERE asset_id = ? AND pipeline_version = ?",
                (asset_id, normalized_pipeline_version),
            )
            if existing is not None:
                return self._row_to_job(existing)

            if asset["status"] == AssetStatus.DELETED.value:
                raise ValueError("cannot complete upload for a deleted asset")

            completed_session = await self._fetchone(
                connection,
                """
                    SELECT sessions.session_id
                    FROM upload_sessions AS sessions
                    LEFT JOIN upload_chunks AS chunks
                        ON chunks.session_id = sessions.session_id AND chunks.status = 'confirmed'
                    WHERE sessions.asset_id = ?
                    GROUP BY sessions.session_id, sessions.total_chunks
                    HAVING COUNT(chunks.upload_chunk_id) = sessions.total_chunks
                    LIMIT 1
                    """,
                (asset_id,),
            )
            if completed_session is None:
                raise ValueError(f"upload is incomplete for asset: {asset_id}")

            job = Job(
                job_id=str(uuid.uuid4()),
                asset_id=asset_id,
                pipeline_version=normalized_pipeline_version,
                status=JobStatus.QUEUED,
                next_run_at=completed_at,
                config_snapshot=snapshot,
                created_at=completed_at,
                updated_at=completed_at,
            )
            await connection.execute(
                """
                    INSERT INTO jobs (
                        job_id, asset_id, pipeline_version, status, stage, attempt, next_run_at,
                        lease_owner, lease_until, heartbeat_at, config_snapshot, last_error,
                        cancel_requested, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                self._job_parameters(job),
            )
            await connection.execute(
                """
                    UPDATE assets
                    SET status = ?, current_job_id = ?, updated_at = ?
                    WHERE asset_id = ?
                    """,
                (AssetStatus.READY.value, job.job_id, _to_iso(completed_at), asset_id),
            )
            await connection.execute(
                "UPDATE upload_sessions SET status = ? WHERE asset_id = ?",
                (AssetStatus.READY.value, asset_id),
            )
            return job

    async def get_asset(self, asset_id: str) -> Asset:
        """Load one durable asset by identifier."""
        async with self._connect() as connection:
            row = await self._fetchone(
                connection,
                "SELECT * FROM assets WHERE asset_id = ?",
                (asset_id,),
            )
        if row is None:
            raise KeyError(f"unknown asset: {asset_id}")
        return self._row_to_asset(row)

    async def list_ready_assets(self) -> list[Asset]:
        """Return assets exposed by the recorded-video read facade."""
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM assets
                WHERE status = ? AND deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM asset_deletion_requests
                        WHERE asset_deletion_requests.asset_id = assets.asset_id
                    )
                ORDER BY created_at, asset_id
                """,
                (AssetStatus.READY.value,),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return [self._row_to_asset(row) for row in rows]

    async def list_segments(self, asset_id: str) -> list[Segment]:
        """Return an asset's persisted timeline segments in playback order."""
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM segments
                WHERE asset_id = ?
                ORDER BY start_offset_ms, ordinal, segment_id
                """,
                (asset_id,),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return [self._row_to_segment(row) for row in rows]

    async def find_segment(self, asset_id: str, timestamp: datetime) -> Segment:
        """Find a segment using half-open intervals, with an inclusive final endpoint."""
        timestamp_iso = _to_iso(_require_aware(timestamp, "timestamp"), "timestamp")
        async with self._connect() as connection:
            row = await self._fetchone(
                connection,
                """
                WITH asset_segments AS (
                    SELECT segments.*, MAX(end_time) OVER () AS terminal_end_time
                    FROM segments
                    WHERE asset_id = ?
                )
                SELECT * FROM asset_segments
                WHERE start_time <= ?
                  AND (
                    end_time > ?
                    OR (end_time = ? AND end_time = terminal_end_time)
                  )
                ORDER BY start_time DESC, start_offset_ms DESC, ordinal DESC, segment_id DESC
                LIMIT 1
                """,
                (asset_id, timestamp_iso, timestamp_iso, timestamp_iso),
            )
        if row is None:
            raise KeyError(f"no segment for asset {asset_id} at {timestamp_iso}")
        return self._row_to_segment(row)

    async def get_job(self, job_id: str) -> Job:
        """Load one durable job by identifier."""
        async with self._connect() as connection:
            row = await self._fetchone(
                connection,
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            )
        if row is None:
            raise KeyError(f"unknown job: {job_id}")
        return self._row_to_job(row)

    async def list_job_steps(self, job_id: str) -> list[JobStep]:
        """Load durable stage checkpoints in pipeline order."""
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM job_steps WHERE job_id = ?",
                (job_id,),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        steps = [
            JobStep(
                job_id=row["job_id"],
                stage=JobStage(row["stage"]),
                status=JobStatus(row["status"]),
                output_manifest=row["output_manifest"],
                output_checksum=row["output_checksum"],
                model=row["model"],
                elapsed_ms=row["elapsed_ms"],
            )
            for row in rows
        ]
        return sorted(steps, key=lambda step: _STAGE_ORDER[step.stage])

    async def start_pipeline(self, job: Job) -> None:
        """Fence a pipeline attempt and hide its asset until publish succeeds."""
        if job.lease_owner is None:
            raise PermissionError("pipeline start requires a lease owner")
        async with self._write_transaction() as connection:
            started_at = self._now()
            await self._require_active_lease(connection, job, started_at)
            await connection.execute(
                """
                UPDATE assets SET status = ?, updated_at = ?
                WHERE asset_id = ? AND current_job_id = ? AND deleted_at IS NULL
                """,
                (AssetStatus.PROCESSING.value, _to_iso(started_at), job.asset_id, job.job_id),
            )

    async def assert_active_lease(self, job: Job) -> None:
        """Fence an external side effect against the current leased SQLite identity."""
        if job.lease_owner is None:
            raise PermissionError("active lease requires a lease owner")
        async with self._write_transaction() as connection:
            await self._require_active_lease(connection, job, self._now())

    async def assert_cancel_cleanup_lease(self, job: Job, now: datetime | None = None) -> None:
        """Fence cancellation cleanup without requiring the job to remain current."""
        if job.lease_owner is None:
            raise PermissionError("cancel cleanup requires a lease owner")
        checked_at = _require_aware(now or self._now(), "now")
        async with self._write_transaction() as connection:
            await self._require_cancel_cleanup_lease(connection, job, checked_at)

    async def reset_steps_from(self, job: Job, stage: JobStage) -> None:
        """Discard an invalid checkpoint and all outputs that depend on it."""
        if job.lease_owner is None:
            raise PermissionError("checkpoint reset requires a lease owner")
        affected = [candidate.value for candidate in JobStage if _STAGE_ORDER[candidate] >= _STAGE_ORDER[stage]]
        placeholders = ",".join("?" for _ in affected)
        async with self._write_transaction() as connection:
            reset_at = self._now()
            await self._require_active_lease(connection, job, reset_at)
            await connection.execute(
                f"DELETE FROM job_steps WHERE job_id = ? AND stage IN ({placeholders})",
                (job.job_id, *affected),
            )
            remaining_stages = []
            cursor = await connection.execute("SELECT stage FROM job_steps WHERE job_id = ?", (job.job_id,))
            try:
                remaining_stages = [JobStage(row["stage"]) for row in await cursor.fetchall()]
            finally:
                await cursor.close()
            latest = max(remaining_stages, key=_STAGE_ORDER.__getitem__).value if remaining_stages else None
            await connection.execute(
                "UPDATE jobs SET stage = ?, updated_at = ? WHERE job_id = ?",
                (latest, _to_iso(reset_at), job.job_id),
            )

    async def complete_pipeline(
        self,
        job: Job,
        asset: Asset,
        segments: Collection[Segment],
        step: JobStep,
    ) -> Job:
        """Atomically publish durable segments and the searchable terminal state."""
        if job.lease_owner is None:
            raise PermissionError("pipeline completion requires a lease owner")
        if asset.asset_id != job.asset_id or step.job_id != job.job_id:
            raise ValueError("pipeline completion identifiers do not match")
        if step.stage is not JobStage.PUBLISH or step.status is not JobStatus.COMPLETED:
            raise ValueError("pipeline completion requires a completed publish step")
        canonical_publish_manifest = f"derived/{job.pipeline_version}/attempts/{job.attempt}/manifest.json"
        if step.output_manifest != canonical_publish_manifest:
            raise ValueError("pipeline completion requires the canonical publish manifest key")
        async with self._write_transaction() as connection:
            completed_at = self._now()
            await self._require_active_lease(connection, job, completed_at)
            prerequisite_stages = tuple(stage.value for stage in JobStage if stage is not JobStage.PUBLISH)
            placeholders = ",".join("?" for _ in prerequisite_stages)
            cursor = await connection.execute(
                f"""
                SELECT stage FROM job_steps
                WHERE job_id = ? AND status = ? AND output_manifest IS NOT NULL
                    AND output_checksum IS NOT NULL AND stage IN ({placeholders})
                """,
                (job.job_id, JobStatus.COMPLETED.value, *prerequisite_stages),
            )
            try:
                completed_prerequisites = {row["stage"] for row in await cursor.fetchall()}
            finally:
                await cursor.close()
            if completed_prerequisites != set(prerequisite_stages):
                raise ValueError("pipeline completion requires all six prerequisite steps")
            existing = await self._fetchone(
                connection,
                "SELECT * FROM job_steps WHERE job_id = ? AND stage = ?",
                (job.job_id, JobStage.PUBLISH.value),
            )
            incoming = (
                step.status.value,
                step.output_manifest,
                step.output_checksum,
                step.model,
                step.elapsed_ms,
            )
            if existing is not None:
                stored = (
                    existing["status"],
                    existing["output_manifest"],
                    existing["output_checksum"],
                    existing["model"],
                    existing["elapsed_ms"],
                )
                if stored != incoming:
                    raise ValueError(f"checkpoint conflict for {job.job_id}:{JobStage.PUBLISH.value}")
            else:
                await connection.execute(
                    """
                    INSERT INTO job_steps (
                        job_id, stage, status, output_manifest, output_checksum, model, elapsed_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step.job_id,
                        step.stage.value,
                        step.status.value,
                        step.output_manifest,
                        step.output_checksum,
                        step.model,
                        step.elapsed_ms,
                    ),
                )
            for segment in segments:
                if segment.asset_id != asset.asset_id or segment.pipeline_version != job.pipeline_version:
                    raise ValueError("segment does not belong to the completing pipeline")
                await connection.execute(
                    """
                    INSERT INTO segments (
                        segment_id, asset_id, pipeline_version, ordinal, start_offset_ms, end_offset_ms,
                        start_time, end_time, description, thumbnail_key, model, prompt_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(segment_id) DO UPDATE SET
                        description = excluded.description,
                        thumbnail_key = excluded.thumbnail_key,
                        model = excluded.model,
                        prompt_version = excluded.prompt_version
                    """,
                    (
                        segment.segment_id,
                        segment.asset_id,
                        segment.pipeline_version,
                        segment.ordinal,
                        segment.start_offset_ms,
                        segment.end_offset_ms,
                        _to_iso(segment.start_time),
                        _to_iso(segment.end_time),
                        segment.description,
                        segment.thumbnail_key,
                        segment.model,
                        segment.prompt_version,
                    ),
                )
            await connection.execute(
                """
                UPDATE assets
                SET duration_ms = ?, width = ?, height = ?, status = ?, updated_at = ?
                WHERE asset_id = ? AND current_job_id = ? AND deleted_at IS NULL
                """,
                (
                    asset.duration_ms,
                    asset.width,
                    asset.height,
                    AssetStatus.READY.value,
                    _to_iso(completed_at),
                    asset.asset_id,
                    job.job_id,
                ),
            )
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, stage = ?, next_run_at = NULL, lease_owner = NULL,
                    lease_until = NULL, heartbeat_at = NULL, last_error = NULL,
                    updated_at = ?
                WHERE job_id = ? AND asset_id = ? AND pipeline_version = ?
                    AND status = ? AND lease_owner = ? AND attempt = ?
                RETURNING *
                """,
                (
                    JobStatus.COMPLETED.value,
                    JobStage.PUBLISH.value,
                    _to_iso(completed_at),
                    job.job_id,
                    job.asset_id,
                    job.pipeline_version,
                    JobStatus.RUNNING.value,
                    job.lease_owner,
                    job.attempt,
                ),
            )
            if row is None:
                raise PermissionError("job lost its active lease before completion")
            return self._row_to_job(row)

    async def is_asset_search_ready(
        self,
        asset_id: str,
        job_id: str,
        pipeline_version: str,
        attempt: int,
    ) -> bool:
        """Return whether a projected document identity is publishable by SQLite state."""
        async with self._connect() as connection:
            row = await self._fetchone(
                connection,
                """
                SELECT 1 AS ready
                FROM assets
                JOIN jobs ON jobs.job_id = assets.current_job_id
                JOIN job_steps ON job_steps.job_id = jobs.job_id AND job_steps.stage = ?
                WHERE assets.asset_id = ? AND assets.status = ? AND assets.deleted_at IS NULL
                    AND jobs.job_id = ? AND jobs.asset_id = assets.asset_id
                    AND jobs.pipeline_version = ? AND jobs.attempt = ? AND jobs.status = ?
                    AND job_steps.status = ?
                """,
                (
                    JobStage.PUBLISH.value,
                    asset_id,
                    AssetStatus.READY.value,
                    job_id,
                    pipeline_version,
                    attempt,
                    JobStatus.COMPLETED.value,
                    JobStatus.COMPLETED.value,
                ),
            )
        return row is not None

    async def retry_failed_job(self, job_id: str, now: datetime) -> Job:
        """Atomically make one failed job eligible for another worker attempt."""
        retried_at = _require_aware(now, "now")
        retried_iso = _to_iso(retried_at)

        async with self._write_transaction() as connection:
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, next_run_at = ?, lease_owner = NULL, lease_until = NULL,
                    heartbeat_at = NULL, last_error = NULL, cancel_requested = 0,
                    updated_at = ?
                WHERE job_id = ? AND status = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM asset_deletion_requests
                        WHERE asset_id = jobs.asset_id
                    )
                RETURNING *
                """,
                (
                    JobStatus.QUEUED.value,
                    retried_iso,
                    retried_iso,
                    job_id,
                    JobStatus.FAILED.value,
                ),
            )
            if row is not None:
                return self._row_to_job(row)
            current = await self._fetchone(
                connection,
                """
                SELECT jobs.status,
                    EXISTS (
                        SELECT 1 FROM asset_deletion_requests
                        WHERE asset_id = jobs.asset_id
                    ) AS deletion_requested
                FROM jobs WHERE job_id = ?
                """,
                (job_id,),
            )
            if current is None:
                raise KeyError(f"unknown job: {job_id}")
            if current["deletion_requested"]:
                raise ValueError("asset deletion is in progress")
            raise ValueError(f"only failed jobs can be retried; current status is {current['status']}")

    async def recover_expired_jobs(self, now: datetime) -> list[Job]:
        """Atomically release expired attempts without consuming a new attempt."""
        recovered_at = _require_aware(now, "now")
        async with self._write_transaction() as connection:
            rows = await self._recover_expired_jobs(connection, recovered_at)
        return [self._row_to_job(row) for row in rows]

    async def _recover_expired_jobs(
        self,
        connection: aiosqlite.Connection,
        recovered_at: datetime,
    ) -> list[aiosqlite.Row]:
        recovered_iso = _to_iso(recovered_at)
        cursor = await connection.execute(
            """
            UPDATE jobs
            SET status = CASE
                    WHEN cancel_requested = 1
                        OR asset_id IN (SELECT asset_id FROM asset_deletion_requests)
                    THEN 'running' ELSE 'queued'
                END,
                next_run_at = CASE
                    WHEN cancel_requested = 1
                        OR asset_id IN (SELECT asset_id FROM asset_deletion_requests)
                    THEN NULL ELSE ?
                END,
                lease_owner = NULL, lease_until = NULL, heartbeat_at = NULL,
                cancel_requested = CASE
                    WHEN cancel_requested = 1
                        OR asset_id IN (SELECT asset_id FROM asset_deletion_requests)
                    THEN 1 ELSE 0
                END,
                updated_at = ?
            WHERE status = ? AND lease_until IS NOT NULL AND lease_until <= ?
            RETURNING *
            """,
            (
                recovered_iso,
                recovered_iso,
                JobStatus.RUNNING.value,
                recovered_iso,
            ),
        )
        try:
            rows = list(await cursor.fetchall())
        finally:
            await cursor.close()
        return rows

    async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
        """Atomically claim one due job using the caller's timezone-aware clock."""
        if not owner.strip():
            raise ValueError("owner must not be empty")
        claimed_at = _require_aware(now, "now")
        claimed_iso = _to_iso(claimed_at)
        lease_until = _to_iso(claimed_at + timedelta(seconds=self.lease_seconds))
        due = """
            (
                (
                    status = 'running'
                    AND cancel_requested = 1
                    AND (lease_until IS NULL OR lease_until <= :now)
                )
                OR (
                    status = 'queued'
                    AND (next_run_at IS NULL OR next_run_at <= :now)
                    AND asset_id NOT IN (SELECT asset_id FROM asset_deletion_requests)
                )
            )
        """
        sql = f"""
            UPDATE jobs
            SET status = :running,
                attempt = CASE
                    WHEN status = 'running' AND cancel_requested = 1 THEN attempt
                    ELSE attempt + 1
                END,
                lease_owner = :owner,
                lease_until = :lease_until,
                heartbeat_at = :now,
                cancel_requested = CASE
                    WHEN status = 'running' AND cancel_requested = 1 THEN 1
                    ELSE 0
                END,
                updated_at = :now
            WHERE job_id = (
                SELECT job_id FROM jobs
                WHERE {due}
                ORDER BY
                    CASE WHEN status = 'running' AND cancel_requested = 1 THEN 0 ELSE 1 END,
                    COALESCE(next_run_at, lease_until, created_at), created_at, job_id
                LIMIT 1
            )
            AND {due}
            RETURNING *
        """
        parameters = {
            "running": JobStatus.RUNNING.value,
            "owner": owner,
            "lease_until": lease_until,
            "now": claimed_iso,
        }

        async with self._write_transaction() as connection:
            await self._recover_expired_jobs(connection, claimed_at)
            await connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?
                WHERE status = ? AND next_run_at IS NOT NULL AND next_run_at <= ?
                    AND asset_id NOT IN (SELECT asset_id FROM asset_deletion_requests)
                """,
                (
                    JobStatus.QUEUED.value,
                    claimed_iso,
                    JobStatus.RETRY_WAIT.value,
                    claimed_iso,
                ),
            )
            row = await self._fetchone(connection, sql, parameters)
            if row is None:
                return None
            return self._row_to_job(row)

    async def renew_lease(
        self,
        job_id: str,
        owner: str,
        now: datetime,
        *,
        attempt: int,
    ) -> Job:
        renewed_at = _require_aware(now, "now")
        renewed_iso = _to_iso(renewed_at)
        lease_until = _to_iso(renewed_at + timedelta(seconds=self.lease_seconds))

        async with self._write_transaction() as connection:
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET lease_until = ?, heartbeat_at = ?, updated_at = ?
                WHERE job_id = ? AND status = ? AND lease_owner = ?
                    AND attempt = ? AND lease_until > ? AND cancel_requested = 0
                RETURNING *
                """,
                (
                    lease_until,
                    renewed_iso,
                    renewed_iso,
                    job_id,
                    JobStatus.RUNNING.value,
                    owner,
                    attempt,
                    renewed_iso,
                ),
            )
            if row is not None:
                return self._row_to_job(row)
            await self._raise_lease_error(connection, job_id, owner, attempt, renewed_at)
            raise AssertionError("unreachable")

    async def release_claim(
        self,
        job_id: str,
        owner: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job:
        """Undo a claim that stopped before execution while fencing its exact lease."""
        released_at = _require_aware(now, "now")
        released_iso = _to_iso(released_at)

        async with self._write_transaction() as connection:
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, attempt = attempt - 1, next_run_at = ?,
                    lease_owner = NULL, lease_until = NULL, heartbeat_at = NULL,
                    updated_at = ?
                WHERE job_id = ? AND status = ? AND lease_owner = ? AND attempt = ?
                    AND attempt > 0 AND lease_until > ? AND cancel_requested = 0
                RETURNING *
                """,
                (
                    JobStatus.RETRY_WAIT.value,
                    released_iso,
                    released_iso,
                    job_id,
                    JobStatus.RUNNING.value,
                    owner,
                    attempt,
                    released_iso,
                ),
            )
            if row is not None:
                return self._row_to_job(row)
            await self._raise_lease_error(connection, job_id, owner, attempt, released_at)
            raise AssertionError("unreachable")

    async def checkpoint_step(self, job: Job, step: JobStep) -> None:
        if step.job_id != job.job_id:
            raise ValueError("job and checkpoint must refer to the same job_id")
        if job.lease_owner is None:
            raise PermissionError("checkpoint requires a lease owner")
        async with self._write_transaction() as connection:
            checkpoint_at = self._now()
            current = await self._require_active_lease(
                connection,
                job,
                checkpoint_at,
                allow_cancel_requested=True,
            )

            existing = await self._fetchone(
                connection,
                "SELECT * FROM job_steps WHERE job_id = ? AND stage = ?",
                (step.job_id, step.stage.value),
            )
            incoming_values = (
                step.status.value,
                step.output_manifest,
                step.output_checksum,
                step.model,
                step.elapsed_ms,
            )
            if existing is not None:
                stored_values = (
                    existing["status"],
                    existing["output_manifest"],
                    existing["output_checksum"],
                    existing["model"],
                    existing["elapsed_ms"],
                )
                if stored_values != incoming_values:
                    raise ValueError(f"checkpoint conflict for {step.job_id}:{step.stage.value}")
            else:
                current_stage = JobStage(current["stage"]) if current["stage"] else None
                if current_stage is not None and _STAGE_ORDER[step.stage] < _STAGE_ORDER[current_stage]:
                    raise ValueError(f"stage regression from {current_stage.value} to {step.stage.value}")

                await connection.execute(
                    """
                    INSERT INTO job_steps (
                        job_id, stage, status, output_manifest, output_checksum, model, elapsed_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step.job_id,
                        step.stage.value,
                        step.status.value,
                        step.output_manifest,
                        step.output_checksum,
                        step.model,
                        step.elapsed_ms,
                    ),
                )
            if existing is None:
                await connection.execute(
                    "UPDATE jobs SET stage = ?, updated_at = ? WHERE job_id = ?",
                    (step.stage.value, _to_iso(checkpoint_at), job.job_id),
                )

    async def schedule_retry(
        self,
        job_id: str,
        owner: str,
        next_run_at: datetime,
        error: str,
        *,
        attempt: int,
        now: datetime | None = None,
    ) -> Job:
        retry_at = _require_aware(next_run_at, "next_run_at")
        scheduled_at = _require_aware(now or self._now(), "now")

        async with self._write_transaction() as connection:
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, next_run_at = ?, lease_owner = NULL, lease_until = NULL,
                    heartbeat_at = NULL, last_error = ?, updated_at = ?
                WHERE job_id = ? AND status = ? AND lease_owner = ? AND attempt = ?
                    AND lease_until > ? AND cancel_requested = 0
                RETURNING *
                """,
                (
                    JobStatus.RETRY_WAIT.value,
                    _to_iso(retry_at),
                    error,
                    _to_iso(scheduled_at),
                    job_id,
                    JobStatus.RUNNING.value,
                    owner,
                    attempt,
                    _to_iso(scheduled_at),
                ),
            )
            if row is not None:
                return self._row_to_job(row)
            await self._raise_lease_error(connection, job_id, owner, attempt, scheduled_at)
            raise AssertionError("unreachable")

    async def mark_failed(
        self,
        job_id: str,
        owner: str,
        error: str,
        *,
        attempt: int,
        now: datetime | None = None,
    ) -> Job:
        """Persist a terminal failure while fencing the exact leased attempt."""
        if not error.strip():
            raise ValueError("error must not be empty")
        failed_at = _require_aware(now or self._now(), "now")

        async with self._write_transaction() as connection:
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, next_run_at = NULL, lease_owner = NULL, lease_until = NULL,
                    heartbeat_at = NULL, last_error = ?, updated_at = ?
                WHERE job_id = ? AND status = ? AND lease_owner = ? AND attempt = ?
                    AND lease_until > ? AND cancel_requested = 0
                RETURNING *
                """,
                (
                    JobStatus.FAILED.value,
                    error,
                    _to_iso(failed_at),
                    job_id,
                    JobStatus.RUNNING.value,
                    owner,
                    attempt,
                    _to_iso(failed_at),
                ),
            )
            if row is None:
                await self._raise_lease_error(connection, job_id, owner, attempt, failed_at)
                raise AssertionError("unreachable")
            await connection.execute(
                """
                UPDATE assets
                SET status = ?, updated_at = ?
                WHERE asset_id = ? AND current_job_id = ? AND deleted_at IS NULL
                """,
                (
                    AssetStatus.FAILED.value,
                    _to_iso(failed_at),
                    row["asset_id"],
                    job_id,
                ),
            )
            return self._row_to_job(row)

    async def list_asset_upload_session_ids(self, asset_id: str) -> list[str]:
        """Return only persisted session identifiers owned by one asset."""
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT session_id FROM upload_sessions WHERE asset_id = ? ORDER BY session_id",
                (asset_id,),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return [str(row["session_id"]) for row in rows]

    async def completed_deletion_steps(self, asset_id: str) -> set[str]:
        """Load durable deletion checkpoints for an asset."""
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT step FROM asset_deletion_steps WHERE asset_id = ?",
                (asset_id,),
            )
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return {str(row["step"]) for row in rows}

    async def prepare_asset_deletion(self, asset_id: str, now: datetime) -> tuple[Asset, bool]:
        """Cancel every active asset job and report whether a worker is still running."""
        requested_at = _require_aware(now, "now")
        requested_iso = _to_iso(requested_at)
        async with self._write_transaction() as connection:
            asset_row = await self._fetchone(
                connection,
                "SELECT * FROM assets WHERE asset_id = ?",
                (asset_id,),
            )
            if asset_row is None:
                raise KeyError(f"unknown asset: {asset_id}")
            asset = self._row_to_asset(asset_row)
            if asset.status in {AssetStatus.UPLOADING, AssetStatus.DELETED}:
                return asset, False

            await connection.execute(
                """
                INSERT INTO asset_deletion_requests(asset_id, requested_at)
                VALUES (?, ?)
                ON CONFLICT(asset_id) DO NOTHING
                """,
                (asset_id, requested_iso),
            )

            await self._transition_jobs_for_cancellation(
                connection,
                requested_iso,
                target_predicate="asset_id = ?",
                target_parameters=(asset_id,),
            )
            running = await self._fetchone(
                connection,
                "SELECT job_id FROM jobs WHERE asset_id = ? AND status = ? LIMIT 1",
                (asset_id, JobStatus.RUNNING.value),
            )
            return asset, running is not None

    async def claim_deletion_step(
        self,
        asset_id: str,
        step: str,
        owner_token: str,
        now: datetime,
        lease_until: datetime,
    ) -> bool:
        """Atomically claim one external deletion step unless it is complete or owned."""
        if step not in _DELETION_STEPS or step == "sqlite":
            raise ValueError(f"invalid external deletion step: {step}")
        claimed_at = _require_aware(now, "now")
        expires_at = _require_aware(lease_until, "lease_until")
        if expires_at <= claimed_at:
            raise ValueError("deletion step lease_until must be later than now")
        claimed_iso = _to_iso(claimed_at)
        expires_iso = _to_iso(expires_at)
        async with self._write_transaction() as connection:
            completed = await self._fetchone(
                connection,
                "SELECT 1 FROM asset_deletion_steps WHERE asset_id = ? AND step = ?",
                (asset_id, step),
            )
            if completed is not None:
                return False
            row = await self._fetchone(
                connection,
                """
                INSERT INTO asset_deletion_step_claims (
                    asset_id, step, owner_token, claimed_at, lease_until
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, step) DO UPDATE SET
                    owner_token = excluded.owner_token,
                    claimed_at = excluded.claimed_at,
                    lease_until = excluded.lease_until
                WHERE asset_deletion_step_claims.owner_token = excluded.owner_token
                    OR asset_deletion_step_claims.lease_until <= excluded.claimed_at
                RETURNING owner_token
                """,
                (asset_id, step, owner_token, claimed_iso, expires_iso),
            )
            return row is not None and row["owner_token"] == owner_token

    async def release_deletion_step(self, asset_id: str, step: str, owner_token: str) -> None:
        """Release a claim after an external operation fails so an immediate retry can resume."""
        if step not in _DELETION_STEPS or step == "sqlite":
            raise ValueError(f"invalid external deletion step: {step}")
        async with self._write_transaction() as connection:
            await connection.execute(
                """
                DELETE FROM asset_deletion_step_claims
                WHERE asset_id = ? AND step = ? AND owner_token = ?
                """,
                (asset_id, step, owner_token),
            )

    async def record_deletion_step(
        self,
        asset_id: str,
        step: str,
        owner_token: str,
        now: datetime,
    ) -> None:
        """Persist an idempotent checkpoint after one external cleanup succeeds."""
        if step not in _DELETION_STEPS or step == "sqlite":
            raise ValueError(f"invalid external deletion step: {step}")
        completed_at = _to_iso(_require_aware(now, "now"))
        async with self._write_transaction() as connection:
            claim = await self._fetchone(
                connection,
                """
                SELECT owner_token FROM asset_deletion_step_claims
                WHERE asset_id = ? AND step = ?
                """,
                (asset_id, step),
            )
            if claim is None or claim["owner_token"] != owner_token:
                raise PermissionError("deletion step claim is not owned by this request")
            await connection.execute(
                """
                INSERT INTO asset_deletion_steps(asset_id, step, completed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(asset_id, step) DO NOTHING
                """,
                (asset_id, step, completed_at),
            )
            await connection.execute(
                "DELETE FROM asset_deletion_step_claims WHERE asset_id = ? AND step = ?",
                (asset_id, step),
            )

    async def finalize_asset_deletion(self, asset_id: str, now: datetime) -> None:
        """Atomically remove child records and retain the soft-deleted asset tombstone."""
        deleted_at = _require_aware(now, "now")
        deleted_iso = _to_iso(deleted_at)
        async with self._write_transaction() as connection:
            current = await self._fetchone(
                connection,
                "SELECT status FROM assets WHERE asset_id = ?",
                (asset_id,),
            )
            if current is None:
                raise KeyError(f"unknown asset: {asset_id}")
            running = await self._fetchone(
                connection,
                "SELECT job_id FROM jobs WHERE asset_id = ? AND status = ? LIMIT 1",
                (asset_id, JobStatus.RUNNING.value),
            )
            if running is not None:
                raise ValueError("asset deletion is waiting for the running job safe point")

            await connection.execute("DELETE FROM segments WHERE asset_id = ?", (asset_id,))
            await connection.execute(
                "DELETE FROM job_steps WHERE job_id IN (SELECT job_id FROM jobs WHERE asset_id = ?)",
                (asset_id,),
            )
            await connection.execute("DELETE FROM jobs WHERE asset_id = ?", (asset_id,))
            await connection.execute("DELETE FROM upload_sessions WHERE asset_id = ?", (asset_id,))
            await connection.execute("DELETE FROM asset_deletion_step_claims WHERE asset_id = ?", (asset_id,))
            await connection.execute("DELETE FROM asset_deletion_requests WHERE asset_id = ?", (asset_id,))
            await connection.execute(
                """
                UPDATE assets
                SET status = ?, current_job_id = NULL,
                    deleted_at = COALESCE(deleted_at, ?), updated_at = ?
                WHERE asset_id = ?
                """,
                (AssetStatus.DELETED.value, deleted_iso, deleted_iso, asset_id),
            )
            await connection.execute(
                """
                INSERT INTO asset_deletion_steps(asset_id, step, completed_at)
                VALUES (?, 'sqlite', ?)
                ON CONFLICT(asset_id, step) DO NOTHING
                """,
                (asset_id, deleted_iso),
            )

    async def request_cancel(self, job_id: str, now: datetime) -> Job:
        requested_at = _require_aware(now, "now")
        requested_iso = _to_iso(requested_at)

        async with self._write_transaction() as connection:
            await self._transition_jobs_for_cancellation(
                connection,
                requested_iso,
                target_predicate="job_id = ?",
                target_parameters=(job_id,),
            )
            row = await self._fetchone(connection, "SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            if row is None:
                raise KeyError(f"unknown job: {job_id}")
            return self._row_to_job(row)

    async def finish_cancel(self, job: Job, now: datetime | None = None) -> Job | None:
        """Finalize cancellation only for the exact active leased attempt."""
        if job.lease_owner is None:
            raise PermissionError("cancellation requires a lease owner")
        cancelled_at = _require_aware(now or self._now(), "now")
        cancelled_iso = _to_iso(cancelled_at)
        async with self._write_transaction() as connection:
            await self._require_cancel_cleanup_lease(connection, job, cancelled_at)
            row = await self._fetchone(
                connection,
                """
                UPDATE jobs
                SET status = ?, next_run_at = NULL, lease_owner = NULL,
                    lease_until = NULL, heartbeat_at = NULL, cancel_requested = 0,
                    updated_at = ?
                WHERE job_id = ? AND status = ? AND lease_owner = ? AND attempt = ?
                    AND cancel_requested = 1
                RETURNING *
                """,
                (
                    JobStatus.CANCELLED.value,
                    cancelled_iso,
                    job.job_id,
                    JobStatus.RUNNING.value,
                    job.lease_owner,
                    job.attempt,
                ),
            )
            if row is None:
                raise LeaseLostError("job cancellation lost its attempt fence")
            await connection.execute(
                """
                UPDATE assets SET status = ?, updated_at = ?
                WHERE asset_id = ? AND current_job_id = ? AND deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM asset_deletion_requests
                        WHERE asset_deletion_requests.asset_id = assets.asset_id
                    )
                """,
                (AssetStatus.READY.value, cancelled_iso, job.asset_id, job.job_id),
            )
            return self._row_to_job(row)

    async def is_cancel_requested(self, job: Job, now: datetime | None = None) -> bool:
        """Read cancellation while fencing the exact active attempt."""
        if job.lease_owner is None:
            raise PermissionError("cancellation check requires a lease owner")
        checked_at = _require_aware(now or self._now(), "now")
        async with self._write_transaction() as connection:
            try:
                current = await self._require_active_lease(
                    connection,
                    job,
                    checked_at,
                    allow_cancel_requested=True,
                )
            except LeaseLostError as active_lease_error:
                cancellation = await self._fetchone(
                    connection,
                    "SELECT cancel_requested FROM jobs WHERE job_id = ?",
                    (job.job_id,),
                )
                if cancellation is None or not cancellation["cancel_requested"]:
                    raise active_lease_error
                await self._require_cancel_cleanup_lease(connection, job, checked_at)
                return True
            return bool(current["cancel_requested"])

    async def soft_delete_asset(self, asset_id: str, now: datetime) -> Asset:
        deleted_at = _require_aware(now, "now")
        deleted_iso = _to_iso(deleted_at)

        async with self._write_transaction() as connection:
            await self._transition_jobs_for_cancellation(
                connection,
                deleted_iso,
                target_predicate="asset_id = ?",
                target_parameters=(asset_id,),
            )
            row = await self._fetchone(
                connection,
                """
                UPDATE assets
                SET status = ?, deleted_at = COALESCE(deleted_at, ?), updated_at = ?
                WHERE asset_id = ?
                RETURNING *
                """,
                (AssetStatus.DELETED.value, deleted_iso, deleted_iso, asset_id),
            )
            if row is None:
                raise KeyError(f"unknown asset: {asset_id}")
            return self._row_to_asset(row)

    @staticmethod
    async def _fetchone(
        connection: aiosqlite.Connection,
        sql: str,
        parameters: tuple[Any, ...] | Mapping[str, Any] = (),
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(sql, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    @staticmethod
    async def _transition_jobs_for_cancellation(
        connection: aiosqlite.Connection,
        now_iso: str,
        *,
        target_predicate: str,
        target_parameters: tuple[Any, ...],
    ) -> None:
        await connection.execute(
            f"""
            UPDATE jobs
            SET status = ?, updated_at = ?
            WHERE ({target_predicate}) AND status = ?
            """,
            (JobStatus.QUEUED.value, now_iso, *target_parameters, JobStatus.RETRY_WAIT.value),
        )
        await connection.execute(
            f"""
            UPDATE jobs
            SET status = CASE
                    WHEN status = 'queued' THEN 'cancelled'
                    ELSE status
                END,
                cancel_requested = CASE
                    WHEN status = 'running' THEN 1
                    ELSE 0
                END,
                lease_owner = CASE
                    WHEN status = 'queued'
                        OR (status = 'running' AND (lease_until IS NULL OR lease_until <= ?))
                    THEN NULL ELSE lease_owner
                END,
                lease_until = CASE
                    WHEN status = 'queued'
                        OR (status = 'running' AND (lease_until IS NULL OR lease_until <= ?))
                    THEN NULL ELSE lease_until
                END,
                heartbeat_at = CASE
                    WHEN status = 'queued'
                        OR (status = 'running' AND (lease_until IS NULL OR lease_until <= ?))
                    THEN NULL ELSE heartbeat_at
                END,
                updated_at = ?
            WHERE ({target_predicate}) AND status IN ('queued', 'running')
            """,
            (now_iso, now_iso, now_iso, now_iso, *target_parameters),
        )

    @classmethod
    async def _require_active_lease(
        cls,
        connection: aiosqlite.Connection,
        job: Job,
        now: datetime,
        *,
        allow_cancel_requested: bool = False,
    ) -> aiosqlite.Row:
        current = await cls._fetchone(
            connection,
            """
            SELECT jobs.*, assets.current_job_id AS asset_current_job_id,
                assets.deleted_at AS asset_deleted_at
            FROM jobs JOIN assets ON assets.asset_id = jobs.asset_id
            WHERE jobs.job_id = ?
            """,
            (job.job_id,),
        )
        if current is None:
            raise KeyError(f"unknown job: {job.job_id}")
        if current["asset_id"] != job.asset_id:
            raise LeaseLostError("leased job asset identity does not match")
        if current["pipeline_version"] != job.pipeline_version:
            raise LeaseLostError("leased job pipeline identity does not match")
        if current["asset_current_job_id"] != job.job_id or current["asset_deleted_at"] is not None:
            raise LeaseLostError("asset current job does not match leased job")
        if current["lease_owner"] != job.lease_owner:
            raise LeaseLostError("job has no active lease: lease owner does not match")
        if current["attempt"] != job.attempt:
            raise LeaseLostError("job has no active lease: job attempt does not match")
        lease_until = _from_iso(current["lease_until"])
        if current["status"] != JobStatus.RUNNING.value or lease_until is None or lease_until <= now:
            raise LeaseLostError("job has no active lease")
        if current["cancel_requested"] and not allow_cancel_requested:
            raise LeaseLostError("job cancellation requested")
        return current

    @classmethod
    async def _require_cancel_cleanup_lease(
        cls,
        connection: aiosqlite.Connection,
        job: Job,
        now: datetime,
    ) -> aiosqlite.Row:
        current = await cls._fetchone(
            connection,
            """
            SELECT jobs.*, assets.deleted_at AS asset_deleted_at
            FROM jobs JOIN assets ON assets.asset_id = jobs.asset_id
            WHERE jobs.job_id = ?
            """,
            (job.job_id,),
        )
        if current is None:
            raise KeyError(f"unknown job: {job.job_id}")
        if current["asset_id"] != job.asset_id:
            raise LeaseLostError("cancel cleanup job asset identity does not match")
        if current["pipeline_version"] != job.pipeline_version:
            raise LeaseLostError("cancel cleanup job pipeline identity does not match")
        if current["asset_deleted_at"] is not None:
            raise LeaseLostError("cancel cleanup asset is already deleted")
        if current["lease_owner"] != job.lease_owner:
            raise LeaseLostError("cancel cleanup lease owner does not match")
        if current["attempt"] != job.attempt:
            raise LeaseLostError("cancel cleanup job attempt does not match")
        lease_until = _from_iso(current["lease_until"])
        if current["status"] != JobStatus.RUNNING.value or lease_until is None or lease_until <= now:
            raise LeaseLostError("job has no active cancel cleanup lease")
        if not current["cancel_requested"]:
            raise LeaseLostError("job has no cancellation cleanup request")
        return current

    @classmethod
    async def _raise_lease_error(
        cls,
        connection: aiosqlite.Connection,
        job_id: str,
        owner: str,
        attempt: int,
        now: datetime,
    ) -> None:
        current = await cls._fetchone(connection, "SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        if current is None:
            raise KeyError(f"unknown job: {job_id}")
        if current["lease_owner"] != owner:
            raise LeaseLostError("lease owner does not match")
        if current["attempt"] != attempt:
            raise LeaseLostError("job attempt does not match")
        lease_until = _from_iso(current["lease_until"])
        if current["status"] != JobStatus.RUNNING.value or lease_until is None or lease_until <= now:
            raise LeaseLostError("job has no active lease")
        if current["cancel_requested"]:
            raise LeaseLostError("job cancellation requested")
        raise LeaseLostError("job has no active lease")

    @staticmethod
    def _asset_parameters(asset: Asset) -> tuple[Any, ...]:
        return (
            asset.asset_id,
            asset.display_filename,
            asset.safe_filename,
            asset.size_bytes,
            asset.sha256,
            asset.mime_type,
            asset.source_extension,
            asset.duration_ms,
            asset.width,
            asset.height,
            _to_iso(asset.timeline_origin, "asset.timeline_origin"),
            asset.status.value,
            asset.current_job_id,
            _to_iso(asset.created_at, "asset.created_at"),
            _to_iso(asset.updated_at, "asset.updated_at"),
            _to_iso(asset.deleted_at, "asset.deleted_at"),
        )

    def _job_parameters(self, job: Job) -> tuple[Any, ...]:
        snapshot = job.model_dump(mode="json")["config_snapshot"]
        return (
            job.job_id,
            job.asset_id,
            job.pipeline_version,
            job.status.value,
            job.stage.value if job.stage else None,
            job.attempt,
            _to_iso(job.next_run_at, "job.next_run_at"),
            job.lease_owner,
            _to_iso(job.lease_until, "job.lease_until"),
            _to_iso(job.heartbeat_at, "job.heartbeat_at"),
            _json_snapshot(snapshot, self.allowed_snapshot_models),
            job.last_error,
            _to_iso(job.created_at, "job.created_at"),
            _to_iso(job.updated_at, "job.updated_at"),
        )

    @staticmethod
    def _row_to_upload_session(row: aiosqlite.Row) -> UploadSession:
        return UploadSession(
            session_id=row["session_id"],
            identifier=row["identifier"],
            asset_id=row["asset_id"],
            total_chunks=row["total_chunks"],
            received_chunks=row["received_chunks"],
            filename=row["filename"],
            temp_dir=row["temp_dir"],
            status=AssetStatus(row["status"]),
            expires_at=_from_iso(row["expires_at"]),
        )

    @staticmethod
    def _row_to_job(row: aiosqlite.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            asset_id=row["asset_id"],
            pipeline_version=row["pipeline_version"],
            status=JobStatus(row["status"]),
            stage=JobStage(row["stage"]) if row["stage"] else None,
            attempt=row["attempt"],
            next_run_at=_from_iso(row["next_run_at"]),
            lease_owner=row["lease_owner"],
            lease_until=_from_iso(row["lease_until"]),
            heartbeat_at=_from_iso(row["heartbeat_at"]),
            config_snapshot=json.loads(row["config_snapshot"]),
            last_error=row["last_error"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )

    @staticmethod
    def _row_to_asset(row: aiosqlite.Row) -> Asset:
        return Asset(
            asset_id=row["asset_id"],
            display_filename=row["display_filename"],
            safe_filename=row["safe_filename"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            mime_type=row["mime_type"],
            source_extension=row["source_extension"],
            duration_ms=row["duration_ms"],
            width=row["width"],
            height=row["height"],
            timeline_origin=_from_iso(row["timeline_origin"]),
            status=AssetStatus(row["status"]),
            current_job_id=row["current_job_id"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            deleted_at=_from_iso(row["deleted_at"]),
        )

    @staticmethod
    def _row_to_segment(row: aiosqlite.Row) -> Segment:
        return Segment(
            segment_id=row["segment_id"],
            asset_id=row["asset_id"],
            pipeline_version=row["pipeline_version"],
            ordinal=row["ordinal"],
            start_offset_ms=row["start_offset_ms"],
            end_offset_ms=row["end_offset_ms"],
            start_time=_from_iso(row["start_time"]),
            end_time=_from_iso(row["end_time"]),
            description=row["description"],
            thumbnail_key=row["thumbnail_key"],
            model=row["model"],
            prompt_version=row["prompt_version"],
        )
