from __future__ import annotations

import asyncio
import json
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
from vsa_agent.recorded_video.errors import LeaseLostError
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
    orphan_image = attempt_dir / "frame.tmp.jpg"
    orphan_image.write_bytes(b"partial-image")
    orphan_video = attempt_dir / "clip.tmp.mp4"
    orphan_video.write_bytes(b"partial-video")
    referenced_tmp = attempt_dir / "referenced.tmp.jpg"
    referenced_tmp.write_bytes(b"referenced")
    final_output = attempt_dir / "final.jpg"
    final_output.write_bytes(b"final")
    (attempt_dir / "manifest.json").write_text(
        json.dumps(
            {
                "stages": {
                    "extracting": {
                        "output": {
                            "artifacts": {
                                "derived/pipeline-v1/attempts/1/referenced.tmp.jpg": {},
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    other_attempt_tmp = store.root / "assets/asset-1/derived/pipeline-v1/attempts/2/keep.tmp.mp4"
    other_attempt_tmp.parent.mkdir(parents=True)
    other_attempt_tmp.write_bytes(b"other-attempt")
    pipeline = _pipeline(repository, store, projection=projection, clock=clock)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    # Complete startup recovery before the cancellation becomes reclaimable.
    assert await worker.run_once() is None
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)

    cancelled = await worker.run_once()

    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    assert (await repository.get_job(claimed.job_id)).status is JobStatus.CANCELLED
    assert (await repository.get_asset(claimed.asset_id)).status is AssetStatus.READY
    assert projection.documents == {}
    assert projection.deleted_projections == [(claimed.asset_id, claimed.job_id, claimed.attempt)]
    assert not orphan_tmp.exists()
    assert not orphan_image.exists()
    assert not orphan_video.exists()
    assert referenced_tmp.read_bytes() == b"referenced"
    assert final_output.read_bytes() == b"final"
    assert other_attempt_tmp.read_bytes() == b"other-attempt"
    assert (store.root / "assets/asset-1/source/original.mp4").is_file()


@pytest.mark.asyncio
async def test_cancel_cleanup_claim_is_exclusive_and_keeps_the_original_attempt(tmp_path: Path) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)
    contender = type(repository)(
        repository.database_path,
        lease_seconds=30,
        clock=lambda: clock[0],
    )

    first, second = await asyncio.gather(
        repository.claim_due_job("cleanup-owner-1", clock[0]),
        contender.claim_due_job("cleanup-owner-2", clock[0]),
    )

    cleanup_claims = [job for job in (first, second) if job is not None]
    assert len(cleanup_claims) == 1
    assert cleanup_claims[0].status is JobStatus.RUNNING
    assert cleanup_claims[0].attempt == claimed.attempt
    assert cleanup_claims[0].lease_owner in {"cleanup-owner-1", "cleanup-owner-2"}


@pytest.mark.asyncio
async def test_cleanup_failure_remains_reclaimable_after_lease_expiry(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, claimed = await _claimed_job(tmp_path, clock)
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)

    class FailsFirstCleanupProjection(FakeProjectionStore):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_failures = 1

        async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
            if self.cleanup_failures:
                self.cleanup_failures -= 1
                raise RuntimeError("cleanup unavailable")
            await super().delete_projection(asset_id, job_id, attempt)

    projection = FailsFirstCleanupProjection()
    pipeline = _pipeline(repository, store, projection=projection, clock=clock)
    first_worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    assert await first_worker.run_once() is None
    after_failure = await repository.get_job(claimed.job_id)
    assert after_failure.status is JobStatus.RUNNING
    assert after_failure.attempt == claimed.attempt
    assert after_failure.lease_owner is not None

    clock[0] += timedelta(seconds=31)
    restarted_worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )
    cancelled = await restarted_worker.run_once()

    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempt == claimed.attempt
    assert (await repository.get_job(claimed.job_id)).status is JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_blocked_cleanup_renews_lease_across_multiple_expiries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_calls = 0

    class BlockingCleanupPipeline:
        async def run(self, job) -> None:
            raise AssertionError("cancel cleanup must not run the active pipeline")

        async def cleanup_after_cancel(self, job) -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            cleanup_started.set()
            await release_cleanup.wait()

    renewals: list[tuple[object, object]] = []
    renew_cleanup_lease = repository.renew_cleanup_lease

    async def track_renewal(job, now, lease_until):
        renewals.append((now, lease_until))
        return await renew_cleanup_lease(job, now, lease_until)

    monkeypatch.setattr(repository, "renew_cleanup_lease", track_renewal)
    waits: list[float] = []

    async def advance_clock(seconds: float) -> None:
        await cleanup_started.wait()
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)
        if len(waits) == 7:
            release_cleanup.set()
        await asyncio.sleep(0)

    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=BlockingCleanupPipeline(),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
        wait=advance_clock,
    )

    cancelled = await asyncio.wait_for(worker.run_once(), timeout=1)

    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    assert cleanup_calls == 1
    assert waits == [pytest.approx(10)] * 7
    assert len(renewals) >= 6
    assert all(lease_until - now == timedelta(seconds=30) for now, lease_until in renewals)


@pytest.mark.asyncio
async def test_cleanup_renewal_loss_keeps_durable_marker_reclaimable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)
    cleanup_started = asyncio.Event()
    cleanup_cancelled = asyncio.Event()

    class BlockingCleanupPipeline:
        async def run(self, job) -> None:
            raise AssertionError("cancel cleanup must not run the active pipeline")

        async def cleanup_after_cancel(self, job) -> None:
            cleanup_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise

    async def lose_cleanup_lease(job, now, lease_until):
        del job, now, lease_until
        raise LeaseLostError("cleanup lease was reassigned")

    monkeypatch.setattr(repository, "renew_cleanup_lease", lose_cleanup_lease)

    async def advance_to_renewal(seconds: float) -> None:
        await cleanup_started.wait()
        clock[0] += timedelta(seconds=seconds)

    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=BlockingCleanupPipeline(),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
        wait=advance_to_renewal,
    )

    assert await asyncio.wait_for(worker.run_once(), timeout=1) is None
    await asyncio.wait_for(cleanup_cancelled.wait(), timeout=1)

    durable = await repository.get_job(claimed.job_id)
    assert durable.status is JobStatus.RUNNING
    with sqlite3.connect(repository.database_path) as connection:
        marker = connection.execute(
            "SELECT cancel_requested FROM jobs WHERE job_id = ?",
            (claimed.job_id,),
        ).fetchone()
    assert marker is not None and marker[0] == 1
    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("cleanup-reclaimer", clock[0])
    assert reclaimed is not None and reclaimed.job_id == claimed.job_id
    assert reclaimed.attempt == claimed.attempt


@pytest.mark.asyncio
async def test_exhausted_cancel_cleanup_bypasses_failure_and_pipeline_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET attempt = ? WHERE job_id = ?",
            (4, claimed.job_id),
        )
        connection.commit()
    claimed = await repository.get_job(claimed.job_id)
    await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=31)
    cleanup_calls: list[tuple[str, int]] = []

    class CleanupOnlyPipeline:
        async def run(self, job) -> None:
            raise AssertionError("cancel cleanup must not run the active pipeline")

        async def cleanup_after_cancel(self, job) -> None:
            cleanup_calls.append((job.job_id, job.attempt))

    async def unexpected_mark_failed(*_args, **_kwargs):
        raise AssertionError("cancel cleanup must not mark the job failed")

    monkeypatch.setattr(repository, "mark_failed", unexpected_mark_failed)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=CleanupOnlyPipeline(),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    cancelled = await worker.run_once()

    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempt == 4
    assert cleanup_calls == [(claimed.job_id, 4)]


@pytest.mark.asyncio
async def test_renewal_cancel_race_runs_cleanup_and_finishes_cancel(tmp_path: Path) -> None:
    clock = [NOW]
    repository, _store, claimed = await _claimed_job(tmp_path, clock)
    await repository.release_claim(
        claimed.job_id,
        claimed.lease_owner or "",
        attempt=claimed.attempt,
        now=clock[0],
    )
    pipeline_started = asyncio.Event()
    cleanup_calls: list[tuple[str, int]] = []

    class BlockedPipeline:
        async def run(self, job):
            pipeline_started.set()
            await asyncio.Event().wait()

        async def cleanup_after_cancel(self, job) -> None:
            cleanup_calls.append((job.job_id, job.attempt))

    cancel_sent = False

    async def renewal_barrier(_seconds: float) -> None:
        nonlocal cancel_sent
        await pipeline_started.wait()
        if not cancel_sent:
            cancel_sent = True
            await repository.request_cancel(claimed.job_id, clock[0] + timedelta(seconds=1))

    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=BlockedPipeline(),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
        wait=renewal_barrier,
    )

    result = await worker.run_once()

    assert result is not None and result.status is JobStatus.CANCELLED
    assert cleanup_calls == [(claimed.job_id, claimed.attempt)]


@pytest.mark.asyncio
async def test_projection_replay_keeps_stable_visible_segment_documents(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, first_attempt = await _claimed_job(tmp_path, clock)

    class CrashesAfterProjection(FakeProjectionStore):
        def __init__(self) -> None:
            super().__init__()
            self.crash_after_projection = True
            self.fail_cleanup = True

        async def project(self, documents, *, job_id=None, attempt=None):
            result = await super().project(documents, job_id=job_id, attempt=attempt)
            if self.crash_after_projection:
                self.crash_after_projection = False
                raise RuntimeError("crash after projection")
            return result

        async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
            if self.fail_cleanup:
                self.fail_cleanup = False
                raise RuntimeError("process died before projection rollback")
            await super().delete_projection(asset_id, job_id, attempt)

    projection = CrashesAfterProjection()
    pipeline = _pipeline(
        repository,
        store,
        projection=projection,
        segmenter=FixedDurationSegmenter(2),
        clock=clock,
    )

    with pytest.raises(RuntimeError, match="crash after projection"):
        await pipeline.run(first_attempt)
    first_ids = set(projection.documents)
    assert len(first_ids) == 3
    assert {document["job_attempt"] for document in projection.documents.values()} == {first_attempt.attempt}

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
    assert set(projection.documents) == first_ids
    assert len(projection.documents) == len(await repository.list_segments(first_attempt.asset_id)) == 3
    assert {document["job_attempt"] for document in projection.documents.values()} == {first_attempt.attempt + 1}
    assert {document["readiness"]["attempt"] for document in projection.documents.values()} == {
        first_attempt.attempt + 1
    }
    assert len(projection.calls) == 2


@pytest.mark.asyncio
async def test_deletion_requested_cancel_never_restores_ready_or_read_facade(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, claimed = await _claimed_job(tmp_path, clock)
    await repository.start_pipeline(claimed)
    _asset, running = await repository.prepare_asset_deletion(
        claimed.asset_id,
        clock[0] + timedelta(seconds=1),
    )
    assert running is True
    clock[0] += timedelta(seconds=31)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=_pipeline(repository, store, clock=clock),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    cancelled = await worker.run_once()

    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    assert (await repository.get_asset(claimed.asset_id)).status is not AssetStatus.READY
    assert await repository.list_ready_assets() == []
    await repository.finalize_asset_deletion(claimed.asset_id, clock[0] + timedelta(seconds=1))
    assert (await repository.get_asset(claimed.asset_id)).status is AssetStatus.DELETED


@pytest.mark.asyncio
async def test_deletion_cleans_noncurrent_pipeline_job_without_overwriting_newer_asset_state(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    repository, store, older = await _claimed_job(tmp_path, clock)
    newer = await repository.complete_upload(
        older.asset_id,
        "pipeline-v2",
        now=clock[0] + timedelta(seconds=1),
    )
    await repository.prepare_asset_deletion(older.asset_id, clock[0] + timedelta(seconds=2))
    expected_asset = await repository.get_asset(older.asset_id)
    assert expected_asset.current_job_id == newer.job_id
    assert (await repository.get_job(newer.job_id)).status is JobStatus.CANCELLED
    clock[0] += timedelta(seconds=31)
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=_pipeline(repository, store, clock=clock),
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=3,
        clock=lambda: clock[0],
    )

    cancelled = await worker.run_once()

    assert cancelled is not None and cancelled.job_id == older.job_id
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempt == older.attempt
    asset_after_cleanup = await repository.get_asset(older.asset_id)
    assert asset_after_cleanup.current_job_id == newer.job_id
    assert asset_after_cleanup.status is expected_asset.status
    await repository.finalize_asset_deletion(older.asset_id, clock[0] + timedelta(seconds=1))
    assert (await repository.get_asset(older.asset_id)).status is AssetStatus.DELETED


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
