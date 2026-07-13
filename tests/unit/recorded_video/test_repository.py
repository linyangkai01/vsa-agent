from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

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
    repository = JobRepository(tmp_path / "jobs.sqlite3", lease_seconds=30)
    await repository.initialize()
    return repository


async def _ready_job(
    repo: JobRepository,
    asset_id: str = "asset",
    *,
    pipeline_version: str = "v1",
    config_snapshot: dict[str, object] | None = None,
):
    await repo.create_upload_session(_asset(asset_id), _session(asset_id, identifier=f"identifier-{asset_id}"))
    return await repo.complete_upload(
        asset_id,
        pipeline_version,
        now=NOW,
        config_snapshot=config_snapshot or {},
    )


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
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]

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
async def test_complete_upload_is_idempotent_and_round_trips_config_snapshot(repo: JobRepository):
    await repo.create_upload_session(_asset(), _session())
    snapshot = {"vision": {"model": "qwen", "thresholds": [0.2, 0.8]}}

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
async def test_only_one_worker_claims_a_due_job_across_repository_instances(repo: JobRepository):
    created = await _ready_job(repo, config_snapshot={"nested": {"enabled": True}})
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
    assert claimed.model_dump(mode="json")["config_snapshot"] == {"nested": {"enabled": True}}


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
        await repo.renew_lease(claimed.job_id, "worker-2", NOW + timedelta(seconds=5))

    renewed = await repo.renew_lease(claimed.job_id, "worker-1", NOW + timedelta(seconds=5))
    assert renewed.heartbeat_at == NOW + timedelta(seconds=5)
    assert renewed.lease_until == NOW + timedelta(seconds=35)

    with pytest.raises(PermissionError, match="active lease"):
        await repo.renew_lease(claimed.job_id, "worker-1", NOW + timedelta(seconds=36))


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
async def test_all_explicit_repository_clocks_reject_naive_datetimes(repo: JobRepository):
    await repo.create_upload_session(_asset(), _session())
    naive = NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.complete_upload("asset", "v1", now=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.request_cancel("missing", naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repo.soft_delete_asset("asset", naive)
