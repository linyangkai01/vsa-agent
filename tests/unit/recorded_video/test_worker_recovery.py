from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

import vsa_agent.recorded_video.pipeline as pipeline_module
from tests.unit.recorded_video.test_pipeline import (
    FakeEmbeddingProvider,
    FakeProjectionStore,
    FakeVisionProvider,
    _claimed_job,
    _pipeline,
)
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.models import AssetStatus, JobStatus
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter
from vsa_agent.recorded_video.worker import RecordedVideoWorker

from .test_pipeline import NOW


@pytest.mark.asyncio
async def test_worker_startup_reclaims_expired_attempt_and_reuses_verified_checkpoint(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    repository, store, first_attempt = await _claimed_job(tmp_path, clock)
    vision = FakeVisionProvider()
    embedding = FakeEmbeddingProvider(failures=1)
    projection = FakeProjectionStore()
    pipeline = _pipeline(
        repository,
        store,
        vision=vision,
        embedding=embedding,
        projection=projection,
        clock=clock,
    )

    with pytest.raises(RuntimeError, match="temporary embedding failure"):
        await pipeline.run(first_attempt)

    clock[0] += timedelta(seconds=31)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )
    result = await worker.run_once()

    assert result is not None and result.status is JobStatus.COMPLETED
    assert len(vision.calls) == 1
    assert len(embedding.calls) == 2
    assert len(projection.calls) == 1
    assert (await repository.get_job(first_attempt.job_id)).attempt == 2


@pytest.mark.asyncio
async def test_recover_expired_jobs_is_atomic_and_does_not_consume_an_attempt(tmp_path: Path) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    contender = type(repository)(
        repository.database_path,
        lease_seconds=30,
        clock=lambda: clock[0],
    )
    clock[0] += timedelta(seconds=30)

    first, second = await asyncio.gather(
        repository.recover_expired_jobs(clock[0]),
        contender.recover_expired_jobs(clock[0]),
    )

    recovered = first + second
    assert len(recovered) == 1
    assert recovered[0].job_id == claimed.job_id
    assert recovered[0].status is JobStatus.QUEUED
    assert recovered[0].attempt == claimed.attempt
    assert recovered[0].lease_owner is None
    reclaimed = await repository.claim_due_job("worker-after-crash", clock[0])
    assert reclaimed is not None and reclaimed.attempt == claimed.attempt + 1


@pytest.mark.asyncio
async def test_startup_finalizes_crashed_cancel_and_rolls_back_only_that_attempt(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, claimed = await _claimed_job(tmp_path, clock)
    await repository.start_pipeline(claimed)
    projection = FakeProjectionStore()
    projection.documents["segment-old"] = {
        "_id": "segment-old",
        "asset_id": claimed.asset_id,
        "job_id": claimed.job_id,
        "job_attempt": claimed.attempt,
    }
    attempt_dir = store.root / "assets/asset-1/derived/pipeline-v1/attempts/1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    orphan_tmp = attempt_dir / ".crashed.tmp"
    orphan_tmp.write_bytes(b"partial")
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)
    pipeline = _pipeline(repository, store, projection=projection, clock=clock)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    assert await worker.run_once() is None

    assert (await repository.get_job(claimed.job_id)).status is JobStatus.CANCELLED
    assert (await repository.get_asset(claimed.asset_id)).status is AssetStatus.READY
    assert projection.documents == {}
    assert projection.deleted_projections == [(claimed.asset_id, claimed.job_id, claimed.attempt)]
    assert not orphan_tmp.exists()
    assert (store.root / "assets/asset-1/source/original.mp4").is_file()


@pytest.mark.asyncio
async def test_cancel_safe_point_rolls_back_attempt_and_cleans_only_orphan_temporary_files(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    repository, initial_store, queued_attempt = await _claimed_job(tmp_path, clock)
    clock[0] += timedelta(seconds=31)
    store = LocalAssetStore(initial_store.root, cleanup_repository=repository)
    source_path = store.root / "assets/asset-1/source/original.mp4"
    attempt_dir = store.root / "assets/asset-1/derived/pipeline-v1/attempts/2"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    orphan_tmp = attempt_dir / ".interrupted-write.tmp"
    orphan_tmp.write_bytes(b"partial")
    unrelated = attempt_dir / "diagnostic.txt"
    unrelated.write_text("preserve", encoding="utf-8")

    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            "UPDATE upload_sessions SET expires_at = ? WHERE asset_id = ?",
            ((clock[0] - timedelta(seconds=1)).isoformat(), queued_attempt.asset_id),
        )
        connection.commit()
    upload_dir = store.root / "uploads/session-1"
    (upload_dir / "chunks").mkdir(parents=True)
    (upload_dir / "chunks/000001.part").write_bytes(b"recorded-video")
    assert upload_dir.is_dir()

    class CancellingEmbedding(FakeEmbeddingProvider):
        async def embed(self, text, *, expected_dims, asset_id, job_id):
            vector = await super().embed(
                text,
                expected_dims=expected_dims,
                asset_id=asset_id,
                job_id=job_id,
            )
            await repository.request_cancel(job_id, clock[0] + timedelta(seconds=1))
            return vector

    projection = FakeProjectionStore()
    pipeline = _pipeline(
        repository,
        store,
        embedding=CancellingEmbedding(),
        projection=projection,
        segmenter=FixedDurationSegmenter(2),
        clock=clock,
    )
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    result = await worker.run_once()

    assert result is not None and result.status is JobStatus.CANCELLED
    assert issubclass(pipeline_module.PipelineCancelled, PermissionError)
    assert projection.calls == []
    assert projection.deleted_projections == [
        (queued_attempt.asset_id, queued_attempt.job_id, queued_attempt.attempt + 1)
    ]
    assert source_path.read_bytes() == b"recorded-video"
    assert not orphan_tmp.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"
    assert not upload_dir.exists()


@pytest.mark.asyncio
async def test_explicit_retry_reuses_job_and_deletion_fence_wins(tmp_path: Path) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    owner = claimed.lease_owner
    assert owner is not None
    failed = await repository.mark_failed(
        claimed.job_id,
        owner,
        "CORRUPT_MEDIA",
        attempt=claimed.attempt,
        now=clock[0] + timedelta(seconds=1),
    )

    retried = await repository.retry_failed_job(failed.job_id, clock[0] + timedelta(seconds=2))

    assert retried.job_id == claimed.job_id
    assert retried.asset_id == claimed.asset_id
    assert retried.pipeline_version == claimed.pipeline_version
    assert retried.status is JobStatus.QUEUED

    reclaimed = await repository.claim_due_job("retry-worker", clock[0] + timedelta(seconds=2))
    assert reclaimed is not None
    failed_again = await repository.mark_failed(
        reclaimed.job_id,
        reclaimed.lease_owner or "",
        "CORRUPT_MEDIA",
        attempt=reclaimed.attempt,
        now=clock[0] + timedelta(seconds=3),
    )
    await repository.prepare_asset_deletion(failed_again.asset_id, clock[0] + timedelta(seconds=4))
    with pytest.raises(ValueError, match="deletion is in progress"):
        await repository.retry_failed_job(failed_again.job_id, clock[0] + timedelta(seconds=5))
