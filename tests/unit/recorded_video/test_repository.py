from __future__ import annotations

import asyncio
import base64
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

import vsa_agent.recorded_video.repository as repository_module
from vsa_agent.recorded_video.models import (
    Asset,
    AssetStatus,
    JobStage,
    JobStatus,
    JobStep,
    UploadSession,
)
from vsa_agent.recorded_video.repository import JobRepository

NOW = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
SNAPSHOT_MODEL = "qwen3-vl-flash-2025-10-15"


def _asset(asset_id: str = "asset") -> Asset:
    return Asset(
        asset_id=asset_id,
        display_filename=f"{asset_id}.mp4",
        safe_filename=f"{asset_id}.mp4",
        size_bytes=128,
        sha256="a" * 64,
        mime_type="video/mp4",
        source_extension="mp4",
        timeline_origin=NOW,
        status=AssetStatus.UPLOADING,
        created_at=NOW,
        updated_at=NOW,
    )


def _session(asset_id: str = "asset", *, identifier: str = "upload-identifier") -> UploadSession:
    return UploadSession(
        session_id=f"session-{asset_id}",
        identifier=identifier,
        asset_id=asset_id,
        total_chunks=2,
        filename=f"{asset_id}.mp4",
        temp_dir=f"uploads/session-{asset_id}",
        status=AssetStatus.UPLOADING,
        expires_at=NOW + timedelta(days=1),
    )


def _fetch_one(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Row:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(sql, parameters).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> JobRepository:
    repository = JobRepository(
        tmp_path / "jobs.sqlite3",
        lease_seconds=30,
        clock=lambda: NOW,
        allowed_snapshot_models={SNAPSHOT_MODEL},
    )
    await repository.initialize()
    return repository


async def _ready_job(
    repo: JobRepository,
    asset_id: str = "asset",
    *,
    pipeline_version: str = "v1",
    config_snapshot: dict[str, object] | None = None,
):
    session = _session(asset_id, identifier=f"identifier-{asset_id}")
    await repo.create_upload_session(_asset(asset_id), session)
    await _record_all_chunks(repo, session)
    return await repo.complete_upload(
        asset_id,
        pipeline_version,
        now=NOW,
        config_snapshot=config_snapshot or {},
    )


async def _record_all_chunks(repo: JobRepository, session: UploadSession) -> None:
    for chunk_number in range(1, session.total_chunks + 1):
        await repo.record_chunk(
            session.session_id,
            chunk_number,
            f"chunk-{chunk_number}",
            size_bytes=chunk_number,
            path=f"{chunk_number:06d}.part",
        )


@pytest.mark.asyncio
async def test_ready_asset_and_segment_read_boundaries_exclude_deleted_assets(repo: JobRepository) -> None:
    ready = _asset("ready")
    deleted = _asset("deleted")
    processing = _asset("processing")
    soft_deleted = _asset("soft-deleted")
    deleted.status = AssetStatus.DELETED
    deleted.deleted_at = NOW
    await repo.create_upload_session(ready, _session("ready", identifier="ready-upload"))
    await repo.create_upload_session(deleted, _session("deleted", identifier="deleted-upload"))
    await repo.create_upload_session(processing, _session("processing", identifier="processing-upload"))
    await repo.create_upload_session(soft_deleted, _session("soft-deleted", identifier="soft-deleted-upload"))
    await _record_all_chunks(repo, _session("ready", identifier="ready-upload"))
    await repo.complete_upload("ready", "v1", now=NOW)
    await _record_all_chunks(repo, _session("soft-deleted", identifier="soft-deleted-upload"))
    await repo.complete_upload("soft-deleted", "v1", now=NOW)

    with sqlite3.connect(repo.database_path) as connection:
        connection.execute(
            "UPDATE assets SET deleted_at = ? WHERE asset_id = ?",
            (NOW.isoformat(), "soft-deleted"),
        )
        connection.execute(
            """
            INSERT INTO segments (
                segment_id, asset_id, pipeline_version, ordinal, start_offset_ms, end_offset_ms,
                start_time, end_time, description, thumbnail_key, model, prompt_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "segment-1",
                "ready",
                "v1",
                0,
                0,
                1_000,
                NOW.isoformat(),
                (NOW + timedelta(seconds=1)).isoformat(),
                "yard",
                "derived/v1/thumbnails/segment-1.jpg",
                None,
                None,
            ),
        )
        connection.commit()

    assert [asset.asset_id for asset in await repo.list_ready_assets()] == ["ready"]
    assert [segment.segment_id for segment in await repo.list_segments("ready")] == ["segment-1"]
    assert (await repo.find_segment("ready", NOW)).segment_id == "segment-1"
    assert await repo.ready_storage_bytes() == ready.size_bytes


@pytest.mark.asyncio
async def test_initialize_enables_wal_and_applies_versioned_schema_idempotently(tmp_path: Path):
    db_path = tmp_path / "nested" / "jobs.sqlite3"
    repository = JobRepository(db_path)

    await repository.initialize()
    await repository.initialize()

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert {
            "assets",
            "upload_sessions",
            "upload_chunks",
            "jobs",
            "job_steps",
            "segments",
            "schema_migrations",
        } <= tables
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,), (2,), (3,)]

        indexes = {
            row[1]
            for table in ("upload_sessions", "upload_chunks", "jobs", "segments")
            for row in connection.execute(f"PRAGMA index_list({table})")
            if row[2]
        }
        assert {
            "uq_upload_sessions_identifier",
            "uq_upload_chunks_session_chunk",
            "uq_jobs_asset_pipeline",
            "uq_segments_asset_pipeline_ordinal",
        } <= indexes
        assert connection.execute("PRAGMA foreign_key_list(job_steps)").fetchall()
        assert connection.execute("PRAGMA foreign_key_list(upload_chunks)").fetchall()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_initialize_rolls_back_a_migration_that_fails_midway(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "failed-migration.sqlite3"
    repository = JobRepository(db_path, clock=lambda: NOW)
    migration = repository_module._MIGRATION_1
    monkeypatch.setattr(
        repository_module,
        "_MIGRATION_1",
        (
            "CREATE TABLE partial_migration (value TEXT)",
            "THIS IS NOT VALID SQL",
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        await repository.initialize()

    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    finally:
        connection.close()
    assert "partial_migration" not in tables
    assert "schema_migrations" not in tables

    monkeypatch.setattr(repository_module, "_MIGRATION_1", migration)
    await repository.initialize()
    assert _fetch_one(db_path, "SELECT MAX(version) AS version FROM schema_migrations")["version"] == 3


@pytest.mark.asyncio
async def test_initialize_rejects_a_database_from_a_future_schema_version(tmp_path: Path):
    db_path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations(version, applied_at)
            VALUES (4, '2026-07-13T04:00:00+00:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="newer schema migration"):
        await JobRepository(db_path, clock=lambda: NOW).initialize()

    assert _fetch_one(db_path, "SELECT MAX(version) AS version FROM schema_migrations")["version"] == 4


@pytest.mark.asyncio
async def test_upload_identifier_and_chunk_key_are_unique_and_chunks_are_idempotent(repo: JobRepository):
    await repo.create_upload_session(_asset(), _session())
    await repo.record_chunk("session-asset", 1, "chunk-a", size_bytes=4, path="000001.part")
    await repo.record_chunk("session-asset", 1, "chunk-a", size_bytes=4, path="000001.part")

    with pytest.raises(ValueError, match="different content"):
        await repo.record_chunk("session-asset", 1, "chunk-b", size_bytes=4, path="000001.part")
    with pytest.raises(sqlite3.IntegrityError):
        await repo.create_upload_session(_asset("asset-2"), _session("asset-2", identifier="upload-identifier"))

    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM upload_chunks")["value"] == 1
    assert (
        _fetch_one(
            repo.database_path,
            "SELECT received_chunks FROM upload_sessions WHERE session_id = ?",
            ("session-asset",),
        )["received_chunks"]
        == 1
    )


@pytest.mark.asyncio
async def test_upload_context_reserves_first_chunk_with_identifier_and_persisted_quota(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)

    reserved = await repo.reserve_upload_chunk(
        session.session_id,
        identifier="client-identifier",
        chunk_number=1,
        total_chunks=2,
        checksum="chunk-a",
        size_bytes=4,
        max_upload_bytes=8,
        path="000001.part",
    )
    restored_session, asset = await repo.get_upload_context(session.session_id)

    assert isinstance(reserved, str)
    assert restored_session.identifier == "client-identifier"
    assert restored_session.total_chunks == 2
    assert asset.asset_id == session.asset_id
    assert await repo.stored_upload_bytes(session.session_id) == 4
    with pytest.raises(ValueError, match="identifier does not match"):
        await repo.reserve_upload_chunk(
            session.session_id,
            identifier="different-identifier",
            chunk_number=2,
            total_chunks=2,
            checksum="chunk-b",
            size_bytes=4,
            max_upload_bytes=8,
            path="000002.part",
        )
    with pytest.raises(ValueError, match="maximum upload size"):
        await repo.reserve_upload_chunk(
            session.session_id,
            identifier="client-identifier",
            chunk_number=2,
            total_chunks=2,
            checksum="chunk-b",
            size_bytes=5,
            max_upload_bytes=8,
            path="000002.part",
        )


@pytest.mark.asyncio
async def test_in_flight_duplicate_cannot_take_reservation_from_original_owner(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)

    original_owner = await repo.reserve_upload_chunk(
        session.session_id,
        identifier="client-identifier",
        chunk_number=1,
        total_chunks=2,
        checksum="chunk-a",
        size_bytes=4,
        max_upload_bytes=8,
        path="000001.part",
    )

    with pytest.raises(ValueError, match="already being uploaded"):
        await repo.reserve_upload_chunk(
            session.session_id,
            identifier="client-identifier",
            chunk_number=1,
            total_chunks=2,
            checksum="chunk-a",
            size_bytes=4,
            max_upload_bytes=8,
            path="000001.part",
        )

    assert await repo.confirm_reserved_upload_chunk(session.session_id, 1, original_owner) is True
    restored_session, _ = await repo.get_upload_context(session.session_id)
    assert restored_session.received_chunks == 1
    assert await repo.stored_upload_bytes(session.session_id) == 4


@pytest.mark.asyncio
async def test_expired_chunk_reservation_can_be_reclaimed_without_old_token_access(tmp_path: Path):
    current_time = [NOW]
    repository = JobRepository(
        tmp_path / "jobs.sqlite3",
        lease_seconds=30,
        clock=lambda: current_time[0],
    )
    await repository.initialize()
    session = _session()
    await repository.create_upload_session(_asset(), session)

    original_owner = await repository.reserve_upload_chunk(
        session.session_id,
        identifier="client-identifier",
        chunk_number=1,
        total_chunks=2,
        checksum="chunk-a",
        size_bytes=4,
        max_upload_bytes=8,
        path="000001.part",
    )

    with pytest.raises(ValueError, match="already being uploaded"):
        await repository.reserve_upload_chunk(
            session.session_id,
            identifier="client-identifier",
            chunk_number=1,
            total_chunks=2,
            checksum="chunk-a",
            size_bytes=4,
            max_upload_bytes=8,
            path="000001.part",
        )

    current_time[0] = NOW + timedelta(seconds=31)
    replacement_owner = await repository.reserve_upload_chunk(
        session.session_id,
        identifier="client-identifier",
        chunk_number=1,
        total_chunks=2,
        checksum="chunk-a",
        size_bytes=4,
        max_upload_bytes=8,
        path="000001.part",
    )

    assert replacement_owner != original_owner
    assert await repository.confirm_reserved_upload_chunk(session.session_id, 1, original_owner) is False
    assert await repository.release_reserved_upload_chunk(session.session_id, 1, original_owner) is False
    assert await repository.confirm_reserved_upload_chunk(session.session_id, 1, replacement_owner) is True


@pytest.mark.asyncio
async def test_only_confirmed_chunk_reservations_count_toward_completion(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)

    reservation = await repo.reserve_upload_chunk(
        session.session_id,
        identifier="client-identifier",
        chunk_number=1,
        total_chunks=1,
        checksum="chunk-a",
        size_bytes=4,
        max_upload_bytes=8,
        path="000001.part",
    )

    restored_session, _ = await repo.get_upload_context(session.session_id)
    assert restored_session.received_chunks == 0
    with pytest.raises(ValueError, match="upload is incomplete"):
        await repo.complete_upload(session.asset_id, "v1", now=NOW)

    assert await repo.confirm_reserved_upload_chunk(session.session_id, 1, reservation) is True
    restored_session, _ = await repo.get_upload_context(session.session_id)
    assert restored_session.received_chunks == 1
    assert (await repo.complete_upload(session.asset_id, "v1", now=NOW)).status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_record_chunk_rejects_unknown_sessions_and_numbers_outside_the_session(repo: JobRepository):
    with pytest.raises(KeyError, match="unknown upload session"):
        await repo.record_chunk("missing-session", 1, "chunk")

    session = _session()
    await repo.create_upload_session(_asset(), session)
    for chunk_number in (0, session.total_chunks + 1):
        with pytest.raises(ValueError, match="between 1 and 2"):
            await repo.record_chunk(session.session_id, chunk_number, "chunk")

    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM upload_chunks")["value"] == 0


@pytest.mark.asyncio
async def test_complete_upload_requires_every_expected_chunk(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await repo.record_chunk(session.session_id, 1, "chunk-1")

    with pytest.raises(ValueError, match="upload is incomplete"):
        await repo.complete_upload("asset", "v1", now=NOW)

    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 0
    await repo.record_chunk(session.session_id, 2, "chunk-2")
    assert (await repo.complete_upload("asset", "v1", now=NOW)).status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_complete_upload_is_idempotent_and_round_trips_config_snapshot(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)
    snapshot = {"vision": {"model": SNAPSHOT_MODEL, "thresholds": [0.2, 0.8]}}

    first = await repo.complete_upload("asset", "v1", now=NOW, config_snapshot=snapshot)
    second = await repo.complete_upload(
        "asset",
        "v1",
        now=NOW + timedelta(seconds=1),
        config_snapshot={"ignored": True},
    )

    assert first.job_id == second.job_id
    assert first.model_dump(mode="json")["config_snapshot"] == snapshot
    assert second.model_dump(mode="json")["config_snapshot"] == snapshot
    assert second.next_run_at == NOW
    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 1


@pytest.mark.asyncio
async def test_complete_upload_normalizes_pipeline_version_before_lookup_and_validation(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)

    first = await repo.complete_upload("asset", " v1 ", now=NOW)
    second = await repo.complete_upload("asset", "v1", now=NOW + timedelta(seconds=1))

    assert first.job_id == second.job_id
    assert first.pipeline_version == "v1"
    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 1

    with pytest.raises(ValueError, match="at least 1 character"):
        await repo.complete_upload("missing-asset", "   ", now=NOW)


@pytest.mark.asyncio
async def test_equivalent_pipeline_versions_complete_once_across_repository_instances(repo: JobRepository):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)
    contender = JobRepository(repo.database_path)

    first, second = await asyncio.gather(
        repo.complete_upload("asset", " v1 ", now=NOW),
        contender.complete_upload("asset", "v1", now=NOW + timedelta(seconds=1)),
    )

    assert first.job_id == second.job_id
    assert first.pipeline_version == second.pipeline_version == "v1"
    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 1


@pytest.mark.parametrize("secret_key", ["openai_api_key", "providerApiKey", "api_key_v2"])
@pytest.mark.asyncio
async def test_complete_upload_rejects_unlisted_composite_api_key_names_before_json_persistence(
    repo: JobRepository,
    secret_key: str,
):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)
    snapshot = {"vision": {secret_key: "private-value"}}

    with pytest.raises(ValueError, match="snapshot key is not allowed"):
        await repo.complete_upload("asset", "v1", now=NOW, config_snapshot=snapshot)

    connection = sqlite3.connect(repo.database_path)
    try:
        persisted_json = connection.execute("SELECT config_snapshot FROM jobs").fetchall()
    finally:
        connection.close()
    assert persisted_json == []


@pytest.mark.parametrize("section", ["pipeline", "vision"])
@pytest.mark.parametrize(
    "model",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        base64.b64encode(b"\x00\x00\x00\x01\x67\x42\x00\x1e\x95\xa8\x28\x0f" + b"h264bytes" * 9).decode(),
        "unconfigured-model",
    ],
)
@pytest.mark.asyncio
async def test_complete_upload_rejects_unsafe_model_values_before_json_persistence(
    repo: JobRepository,
    section: str,
    model: str,
):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)

    with pytest.raises(ValueError, match="snapshot model is not allowed"):
        await repo.complete_upload(
            "asset",
            "v1",
            now=NOW,
            config_snapshot={section: {"model": model}},
        )

    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 0


@pytest.mark.asyncio
async def test_default_repository_rejects_models_but_accepts_model_free_snapshot(tmp_path: Path):
    allowed_models = {SNAPSHOT_MODEL}
    repository = JobRepository(tmp_path / "jobs.sqlite3", allowed_snapshot_models=allowed_models)
    allowed_models.add("later-model")
    await repository.initialize()
    session = _session()
    await repository.create_upload_session(_asset(), session)
    await _record_all_chunks(repository, session)

    assert repository.allowed_snapshot_models == frozenset({SNAPSHOT_MODEL})

    default_repository = JobRepository(repository.database_path)
    with pytest.raises(ValueError, match="snapshot model is not allowed"):
        await default_repository.complete_upload(
            "asset",
            "v1",
            now=NOW,
            config_snapshot={"vision": {"model": SNAPSHOT_MODEL}},
        )

    assert _fetch_one(repository.database_path, "SELECT COUNT(*) AS value FROM jobs")["value"] == 0

    created = await default_repository.complete_upload(
        "asset",
        "v1",
        now=NOW,
        config_snapshot={"vision": {"enabled": True, "thresholds": [0.2, 0.8]}},
    )
    assert created.model_dump(mode="json")["config_snapshot"] == {"vision": {"enabled": True, "thresholds": [0.2, 0.8]}}


@pytest.mark.parametrize(
    ("payload_key", "payload"),
    [
        ("image", "https://example.invalid/full-frame.png"),
        ("payload", "data:image/png;base64,iVBORw0KGgo="),
        (
            "input",
            base64.b64encode(b"\x00\x00\x00\x01\x67\x64\x00\x1f\xac\xd9\x40\x50" + b"h264-bytes" * 8).decode(),
        ),
    ],
)
@pytest.mark.asyncio
async def test_complete_upload_rejects_unlisted_image_and_media_payloads_before_json_persistence(
    repo: JobRepository,
    payload_key: str,
    payload: str,
):
    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)

    with pytest.raises(ValueError, match="snapshot key is not allowed|short identifier"):
        await repo.complete_upload(
            "asset",
            "v1",
            now=NOW,
            config_snapshot={"pipeline": {payload_key: payload}},
        )

    connection = sqlite3.connect(repo.database_path)
    try:
        persisted_json = connection.execute("SELECT config_snapshot FROM jobs").fetchall()
    finally:
        connection.close()
    assert persisted_json == []


@pytest.mark.asyncio
async def test_ordinary_write_paths_share_transaction_helper(repo: JobRepository, monkeypatch):
    original_write_transaction = JobRepository._write_transaction
    helper_calls = 0

    @asynccontextmanager
    async def tracked_write_transaction(self):
        nonlocal helper_calls
        helper_calls += 1
        async with original_write_transaction(self) as connection:
            yield connection

    monkeypatch.setattr(JobRepository, "_write_transaction", tracked_write_transaction)

    session = _session()
    await repo.create_upload_session(_asset(), session)
    await _record_all_chunks(repo, session)
    await repo.complete_upload("asset", "v1", now=NOW)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    await repo.checkpoint_step(
        claimed,
        JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.RUNNING),
    )

    assert helper_calls == 6


@pytest.mark.asyncio
async def test_only_one_worker_claims_a_due_job_across_repository_instances(repo: JobRepository):
    created = await _ready_job(repo, config_snapshot={"vision": {"enabled": True}})
    contender = JobRepository(repo.database_path, lease_seconds=30)

    first, second = await asyncio.gather(
        repo.claim_due_job("worker-1", NOW),
        contender.claim_due_job("worker-2", NOW),
    )

    claimed = first or second
    assert [first, second].count(None) == 1
    assert claimed is not None
    assert claimed.job_id == created.job_id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.lease_owner in {"worker-1", "worker-2"}
    assert claimed.heartbeat_at == NOW
    assert claimed.lease_until == NOW + timedelta(seconds=30)
    assert claimed.model_dump(mode="json")["config_snapshot"] == {"vision": {"enabled": True}}


@pytest.mark.asyncio
async def test_claim_recovers_expired_lease_and_rejects_naive_clock(repo: JobRepository):
    await _ready_job(repo)
    first = await repo.claim_due_job("worker-1", NOW)
    assert first is not None

    assert await repo.claim_due_job("worker-2", NOW + timedelta(seconds=29)) is None
    recovered = await repo.claim_due_job("worker-2", NOW + timedelta(seconds=30))

    assert recovered is not None
    assert recovered.job_id == first.job_id
    assert recovered.lease_owner == "worker-2"
    assert recovered.attempt == 2
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.claim_due_job("worker-3", NOW.replace(tzinfo=None))


@pytest.mark.asyncio
async def test_renew_lease_checks_owner_and_updates_heartbeat(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None

    with pytest.raises(PermissionError, match="lease owner"):
        await repo.renew_lease(
            claimed.job_id,
            "worker-2",
            NOW + timedelta(seconds=5),
            attempt=claimed.attempt,
        )

    renewed = await repo.renew_lease(
        claimed.job_id,
        "worker-1",
        NOW + timedelta(seconds=5),
        attempt=claimed.attempt,
    )
    assert renewed.heartbeat_at == NOW + timedelta(seconds=5)
    assert renewed.lease_until == NOW + timedelta(seconds=35)

    with pytest.raises(PermissionError, match="active lease"):
        await repo.renew_lease(
            claimed.job_id,
            "worker-1",
            NOW + timedelta(seconds=36),
            attempt=claimed.attempt,
        )


@pytest.mark.asyncio
async def test_renew_lease_requires_attempt_fencing_token(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None

    with pytest.raises(TypeError, match="attempt"):
        await repo.renew_lease(claimed.job_id, "worker-1", NOW + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_schedule_retry_requires_attempt_fencing_token(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None

    with pytest.raises(TypeError, match="attempt"):
        await repo.schedule_retry(
            claimed.job_id,
            "worker-1",
            NOW + timedelta(minutes=1),
            "temporary failure",
            now=NOW + timedelta(seconds=2),
        )


@pytest.mark.asyncio
async def test_worker_writes_are_fenced_by_attempt_even_when_owner_is_reused(repo: JobRepository):
    await _ready_job(repo)
    stale = await repo.claim_due_job("worker-1", NOW)
    assert stale is not None
    current = await repo.claim_due_job("worker-1", NOW + timedelta(seconds=30))
    assert current is not None and current.attempt == stale.attempt + 1

    with pytest.raises(PermissionError, match="attempt"):
        await repo.checkpoint_step(
            stale,
            JobStep(job_id=stale.job_id, stage=JobStage.PROBING, status=JobStatus.RUNNING),
        )
    with pytest.raises(PermissionError, match="attempt"):
        await repo.renew_lease(
            stale.job_id,
            "worker-1",
            NOW + timedelta(seconds=31),
            attempt=stale.attempt,
        )
    with pytest.raises(PermissionError, match="attempt"):
        await repo.schedule_retry(
            stale.job_id,
            "worker-1",
            NOW + timedelta(minutes=2),
            "stale worker",
            attempt=stale.attempt,
            now=NOW + timedelta(seconds=31),
        )
    with pytest.raises(PermissionError, match="active lease"):
        await repo.schedule_retry(
            current.job_id,
            "worker-1",
            NOW + timedelta(minutes=3),
            "expired worker",
            attempt=current.attempt,
            now=NOW + timedelta(seconds=60),
        )
    with pytest.raises(PermissionError, match="active lease"):
        await repo.schedule_retry(
            current.job_id,
            "worker-1",
            NOW + timedelta(minutes=3),
            "expired worker",
            attempt=current.attempt,
            now=NOW + timedelta(seconds=61),
        )


@pytest.mark.asyncio
async def test_checkpoint_uses_injected_clock_and_rejects_expired_or_naive_time(tmp_path: Path):
    current_time = [NOW]
    repository = JobRepository(
        tmp_path / "clocked.sqlite3",
        lease_seconds=30,
        clock=lambda: current_time[0],
    )
    await repository.initialize()
    await _ready_job(repository)
    claimed = await repository.claim_due_job("worker-1", NOW)
    assert claimed is not None
    step = JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.RUNNING)

    current_time[0] = NOW + timedelta(seconds=30)
    with pytest.raises(PermissionError, match="active lease"):
        await repository.checkpoint_step(claimed, step)

    current_time[0] = NOW + timedelta(seconds=31)
    with pytest.raises(PermissionError, match="active lease"):
        await repository.checkpoint_step(claimed, step)

    current_time[0] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.checkpoint_step(claimed, step)


@pytest.mark.asyncio
async def test_checkpoint_is_idempotent_and_persists_manifest(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    step = JobStep(
        job_id=claimed.job_id,
        stage=JobStage.ANALYZING,
        status=JobStatus.RUNNING,
        output_manifest="derived/v1/manifest.json",
        output_checksum="sha256:123",
        model="qwen",
        elapsed_ms=250,
    )

    await repo.checkpoint_step(claimed, step)
    await repo.checkpoint_step(claimed, step)

    stored = _fetch_one(
        repo.database_path,
        "SELECT * FROM job_steps WHERE job_id = ? AND stage = ?",
        (claimed.job_id, JobStage.ANALYZING.value),
    )
    assert stored["output_manifest"] == "derived/v1/manifest.json"
    assert stored["output_checksum"] == "sha256:123"
    assert stored["elapsed_ms"] == 250
    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM job_steps")["value"] == 1


@pytest.mark.asyncio
async def test_checkpoint_rejects_content_conflicts_and_stage_regression(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    analyzing = JobStep(
        job_id=claimed.job_id,
        stage=JobStage.ANALYZING,
        status=JobStatus.RUNNING,
        output_manifest="derived/v1/manifest.json",
        output_checksum="sha256:123",
        model="qwen",
        elapsed_ms=250,
    )
    await repo.checkpoint_step(claimed, analyzing)

    conflicts = {
        "status": JobStatus.COMPLETED,
        "output_manifest": "derived/v1/other.json",
        "output_checksum": "sha256:456",
        "model": "other-model",
        "elapsed_ms": 251,
    }
    for field, value in conflicts.items():
        with pytest.raises(ValueError, match="checkpoint conflict"):
            await repo.checkpoint_step(claimed, analyzing.model_copy(update={field: value}))

    with pytest.raises(ValueError, match="stage regression"):
        await repo.checkpoint_step(
            claimed,
            JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.COMPLETED),
        )

    stored = _fetch_one(
        repo.database_path,
        "SELECT stage, elapsed_ms FROM job_steps WHERE job_id = ?",
        (claimed.job_id,),
    )
    assert stored["stage"] == JobStage.ANALYZING.value
    assert stored["elapsed_ms"] == 250


@pytest.mark.asyncio
async def test_identical_older_checkpoint_replay_finalizes_cancel_without_stage_regression(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    probing = JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.COMPLETED)
    await repo.checkpoint_step(claimed, probing)
    await repo.checkpoint_step(
        claimed,
        JobStep(job_id=claimed.job_id, stage=JobStage.ANALYZING, status=JobStatus.RUNNING),
    )
    await repo.request_cancel(claimed.job_id, NOW + timedelta(seconds=1))

    await repo.checkpoint_step(claimed, probing)

    stored = _fetch_one(repo.database_path, "SELECT status, stage FROM jobs WHERE job_id = ?", (claimed.job_id,))
    assert stored["status"] == JobStatus.CANCELLED.value
    assert stored["stage"] == JobStage.ANALYZING.value


@pytest.mark.asyncio
async def test_retry_wait_is_claimed_only_when_due_and_preserves_checkpoint(repo: JobRepository):
    await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    step = JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.COMPLETED)
    await repo.checkpoint_step(claimed, step)

    retry_at = NOW + timedelta(minutes=2)
    scheduled = await repo.schedule_retry(
        claimed.job_id,
        "worker-1",
        retry_at,
        "temporary model timeout",
        attempt=claimed.attempt,
        now=NOW + timedelta(seconds=1),
    )

    assert scheduled.status is JobStatus.RETRY_WAIT
    assert scheduled.lease_owner is None
    assert await repo.claim_due_job("worker-2", retry_at - timedelta(microseconds=1)) is None
    retried = await repo.claim_due_job("worker-2", retry_at)
    assert retried is not None
    assert retried.attempt == 2
    assert _fetch_one(repo.database_path, "SELECT COUNT(*) AS value FROM job_steps")["value"] == 1


@pytest.mark.asyncio
async def test_retry_wait_claim_persists_each_allowed_state_transition(repo: JobRepository):
    created = await _ready_job(repo)
    connection = sqlite3.connect(repo.database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE job_status_audit (old_status TEXT NOT NULL, new_status TEXT NOT NULL);
            CREATE TRIGGER audit_job_status
            AFTER UPDATE OF status ON jobs
            WHEN OLD.status <> NEW.status
            BEGIN
                INSERT INTO job_status_audit(old_status, new_status)
                VALUES (OLD.status, NEW.status);
            END;
            """
        )
        connection.execute(
            "UPDATE jobs SET status = ?, next_run_at = ? WHERE job_id = ?",
            (JobStatus.RETRY_WAIT.value, NOW.isoformat(), created.job_id),
        )
        connection.execute("DELETE FROM job_status_audit")
        connection.commit()
    finally:
        connection.close()

    claimed = await repo.claim_due_job("worker-1", NOW)

    assert claimed is not None and claimed.status is JobStatus.RUNNING
    connection = sqlite3.connect(repo.database_path)
    try:
        transitions = connection.execute(
            "SELECT old_status, new_status FROM job_status_audit ORDER BY rowid"
        ).fetchall()
    finally:
        connection.close()
    assert transitions == [
        (JobStatus.RETRY_WAIT.value, JobStatus.QUEUED.value),
        (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
    ]


@pytest.mark.asyncio
async def test_retry_wait_cancel_persists_each_allowed_state_transition(repo: JobRepository):
    created = await _ready_job(repo)
    connection = sqlite3.connect(repo.database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE job_status_audit (old_status TEXT NOT NULL, new_status TEXT NOT NULL);
            CREATE TRIGGER audit_job_status
            AFTER UPDATE OF status ON jobs
            WHEN OLD.status <> NEW.status
            BEGIN
                INSERT INTO job_status_audit(old_status, new_status)
                VALUES (OLD.status, NEW.status);
            END;
            """
        )
        connection.execute(
            "UPDATE jobs SET status = ?, next_run_at = ? WHERE job_id = ?",
            (JobStatus.RETRY_WAIT.value, (NOW + timedelta(minutes=1)).isoformat(), created.job_id),
        )
        connection.execute("DELETE FROM job_status_audit")
        connection.commit()
    finally:
        connection.close()

    cancelled = await repo.request_cancel(created.job_id, NOW)

    assert cancelled.status is JobStatus.CANCELLED
    connection = sqlite3.connect(repo.database_path)
    try:
        transitions = connection.execute(
            "SELECT old_status, new_status FROM job_status_audit ORDER BY rowid"
        ).fetchall()
    finally:
        connection.close()
    assert transitions == [
        (JobStatus.RETRY_WAIT.value, JobStatus.QUEUED.value),
        (JobStatus.QUEUED.value, JobStatus.CANCELLED.value),
    ]


@pytest.mark.asyncio
async def test_cancel_is_immediate_when_queued_and_deferred_to_running_checkpoint(repo: JobRepository):
    queued = await _ready_job(repo, "queued-asset")
    cancelled = await repo.request_cancel(queued.job_id, NOW)
    assert cancelled.status is JobStatus.CANCELLED

    running = await _ready_job(repo, "running-asset")
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None and claimed.job_id == running.job_id
    requested = await repo.request_cancel(running.job_id, NOW + timedelta(seconds=1))
    assert requested.status is JobStatus.RUNNING

    await repo.checkpoint_step(
        claimed,
        JobStep(job_id=claimed.job_id, stage=JobStage.PROBING, status=JobStatus.RUNNING),
    )
    row = _fetch_one(repo.database_path, "SELECT status, lease_owner FROM jobs WHERE job_id = ?", (running.job_id,))
    assert row["status"] == JobStatus.CANCELLED.value
    assert row["lease_owner"] is None


@pytest.mark.asyncio
async def test_cancel_request_is_finalized_when_the_running_worker_lease_expires(repo: JobRepository):
    running = await _ready_job(repo)
    claimed = await repo.claim_due_job("worker-1", NOW)
    assert claimed is not None
    requested = await repo.request_cancel(running.job_id, NOW + timedelta(seconds=1))
    assert requested.status is JobStatus.RUNNING

    assert await repo.claim_due_job("worker-2", NOW + timedelta(seconds=30)) is None

    row = _fetch_one(
        repo.database_path,
        "SELECT status, cancel_requested, lease_owner FROM jobs WHERE job_id = ?",
        (running.job_id,),
    )
    assert row["status"] == JobStatus.CANCELLED.value
    assert row["cancel_requested"] == 0
    assert row["lease_owner"] is None


@pytest.mark.asyncio
async def test_soft_delete_marks_asset_and_cancels_queued_work(repo: JobRepository):
    job = await _ready_job(repo)

    deleted = await repo.soft_delete_asset("asset", NOW + timedelta(seconds=1))

    assert deleted.status is AssetStatus.DELETED
    assert deleted.deleted_at == NOW + timedelta(seconds=1)
    stored_job = _fetch_one(repo.database_path, "SELECT status FROM jobs WHERE job_id = ?", (job.job_id,))
    assert stored_job["status"] == JobStatus.CANCELLED.value
    assert await repo.claim_due_job("worker", NOW + timedelta(seconds=2)) is None


@pytest.mark.asyncio
async def test_list_expired_unreferenced_sessions_returns_only_completed_expired_uploads(
    repo: JobRepository,
):
    reclaimable = _session("reclaimable", identifier="reclaimable")
    reclaimable.expires_at = NOW - timedelta(seconds=1)
    reclaimable.status = AssetStatus.READY
    active = _session("active", identifier="active")
    active.expires_at = NOW - timedelta(seconds=1)
    incomplete = _session("incomplete", identifier="incomplete")
    incomplete.expires_at = NOW - timedelta(seconds=1)
    incomplete.status = AssetStatus.READY
    unexpired = _session("unexpired", identifier="unexpired")
    unexpired.status = AssetStatus.READY

    for session in (reclaimable, active, incomplete, unexpired):
        await repo.create_upload_session(_asset(session.asset_id), session)
    await _record_all_chunks(repo, reclaimable)
    await _record_all_chunks(repo, active)
    await repo.record_chunk(incomplete.session_id, 1, "chunk-1", path="000001.part")
    await _record_all_chunks(repo, unexpired)

    candidates = await repo.list_expired_unreferenced_sessions(NOW)

    assert [candidate.session_id for candidate in candidates] == [reclaimable.session_id]


@pytest.mark.asyncio
async def test_list_expired_unreferenced_sessions_requires_an_aware_clock(repo: JobRepository):
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.list_expired_unreferenced_sessions(NOW.replace(tzinfo=None))


@pytest.mark.asyncio
async def test_all_explicit_repository_clocks_reject_naive_datetimes(repo: JobRepository):
    await repo.create_upload_session(_asset(), _session())
    naive = NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.complete_upload("asset", "v1", now=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.request_cancel("missing", naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.soft_delete_asset("asset", naive)


@pytest.mark.asyncio
async def test_get_job_reads_persisted_job_and_rejects_unknown_id(repo: JobRepository):
    created = await _ready_job(repo)

    persisted = await repo.get_job(created.job_id)

    assert persisted == created
    with pytest.raises(KeyError, match="unknown job"):
        await repo.get_job("missing-job")


@pytest.mark.asyncio
async def test_get_asset_reads_persisted_asset_and_rejects_unknown_id(repo: JobRepository):
    session = _session()
    asset = _asset()
    await repo.create_upload_session(asset, session)

    persisted = await repo.get_asset(asset.asset_id)

    assert persisted == asset
    with pytest.raises(KeyError, match="unknown asset"):
        await repo.get_asset("missing-asset")


@pytest.mark.asyncio
async def test_retry_failed_job_atomically_requeues_and_clears_transient_state(repo: JobRepository):
    created = await _ready_job(repo)
    retry_at = NOW + timedelta(minutes=5)
    connection = sqlite3.connect(repo.database_path)
    try:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, stage = ?, lease_owner = ?, lease_until = ?, heartbeat_at = ?,
                last_error = ?, cancel_requested = 1
            WHERE job_id = ?
            """,
            (
                JobStatus.FAILED.value,
                JobStage.ANALYZING.value,
                "stale-worker",
                (NOW + timedelta(minutes=1)).isoformat(),
                NOW.isoformat(),
                "provider failed with token=secret-value",
                created.job_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    retried = await repo.retry_failed_job(created.job_id, retry_at)

    assert retried.status is JobStatus.QUEUED
    assert retried.stage is JobStage.ANALYZING
    assert retried.next_run_at == retry_at
    assert retried.lease_owner is None
    assert retried.lease_until is None
    assert retried.heartbeat_at is None
    assert retried.last_error is None
    stored = _fetch_one(
        repo.database_path,
        "SELECT cancel_requested FROM jobs WHERE job_id = ?",
        (created.job_id,),
    )
    assert stored["cancel_requested"] == 0


@pytest.mark.asyncio
async def test_retry_failed_job_only_allows_one_atomic_failed_transition(repo: JobRepository):
    created = await _ready_job(repo)
    connection = sqlite3.connect(repo.database_path)
    try:
        connection.execute(
            "UPDATE jobs SET status = ? WHERE job_id = ?",
            (JobStatus.FAILED.value, created.job_id),
        )
        connection.commit()
    finally:
        connection.close()
    contender = JobRepository(repo.database_path, clock=lambda: NOW)

    results = await asyncio.gather(
        repo.retry_failed_job(created.job_id, NOW),
        contender.retry_failed_job(created.job_id, NOW),
        return_exceptions=True,
    )

    assert sum(isinstance(result, type(created)) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert (await repo.get_job(created.job_id)).status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_retry_failed_job_rejects_non_failed_unknown_and_naive_time(repo: JobRepository):
    created = await _ready_job(repo)

    with pytest.raises(ValueError, match="failed"):
        await repo.retry_failed_job(created.job_id, NOW)
    with pytest.raises(KeyError, match="unknown job"):
        await repo.retry_failed_job("missing-job", NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.retry_failed_job(created.job_id, NOW.replace(tzinfo=None))
