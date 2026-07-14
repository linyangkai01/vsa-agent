from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, Job, JobStage, JobStatus, UploadSession
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.worker import RecordedVideoWorker, parse_worker_args

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _job(name: str, *, attempt: int = 0) -> Job:
    return Job(
        job_id=name,
        asset_id=f"asset-{name}",
        pipeline_version="pipeline-v1",
        status=JobStatus.QUEUED,
        attempt=attempt,
        created_at=NOW,
        updated_at=NOW,
    )


class MemoryRepository:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = deque(jobs)
        self.claims: list[tuple[str, str, int]] = []
        self.renewals: list[tuple[str, str, int]] = []
        self.retries: list[tuple[str, int, int, str]] = []
        self.failures: list[tuple[str, int, str]] = []

    async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
        del now
        if not self.jobs:
            return None
        queued = self.jobs.popleft()
        claimed = queued.model_copy(
            update={
                "status": JobStatus.RUNNING,
                "attempt": queued.attempt + 1,
                "lease_owner": owner,
                "lease_until": NOW + timedelta(seconds=90),
                "heartbeat_at": NOW,
            }
        )
        self.claims.append((claimed.job_id, owner, claimed.attempt))
        return claimed

    async def renew_lease(self, job_id: str, owner: str, now: datetime, *, attempt: int) -> Job:
        del now
        self.renewals.append((job_id, owner, attempt))
        return _job(job_id, attempt=attempt).model_copy(update={"status": JobStatus.RUNNING, "lease_owner": owner})

    async def schedule_retry(
        self,
        job_id: str,
        owner: str,
        next_run_at: datetime,
        error: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job:
        del owner
        self.retries.append((job_id, attempt, int((next_run_at - now).total_seconds()), error))
        return _job(job_id, attempt=attempt).model_copy(
            update={"status": JobStatus.RETRY_WAIT, "next_run_at": next_run_at, "last_error": error}
        )

    async def mark_failed(
        self,
        job_id: str,
        owner: str,
        error: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job:
        del owner, now
        self.failures.append((job_id, attempt, error))
        return _job(job_id, attempt=attempt).model_copy(update={"status": JobStatus.FAILED, "last_error": error})

    async def get_job(self, job_id: str) -> Job:
        return _job(job_id).model_copy(update={"stage": JobStage.ANALYZING})


class BlockingPipeline:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.active = 0
        self.max_active = 0

    async def run(self, job: Job) -> object:
        del job
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return object()


class FailingPipeline:
    async def run(self, job: Job) -> object:
        del job
        raise RecordedVideoError(
            ErrorCode.MODEL_TIMEOUT,
            retryable=True,
            message="MODEL_TIMEOUT: request failed with token=secret-value",
        )


@pytest.mark.asyncio
async def test_worker_limits_parallel_jobs_and_uses_unique_claim_owners() -> None:
    repository = MemoryRepository([_job(f"job-{index}") for index in range(6)])
    pipeline = BlockingPipeline()
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=3,
        lease_sec=90,
        max_attempts=4,
        clock=lambda: NOW,
    )

    running = asyncio.create_task(worker.run_until_idle())
    await pipeline.started.wait()
    await asyncio.sleep(0)
    assert pipeline.max_active == 3
    assert len(repository.claims) == 3

    pipeline.release.set()
    await running

    assert pipeline.max_active == 3
    owners = [owner for _, owner, _ in repository.claims]
    assert len(repository.claims) == 6
    assert len(set(owners)) == 6


@pytest.mark.asyncio
async def test_worker_schedules_attempt_backoff_and_fails_at_max_attempts() -> None:
    repository = MemoryRepository([_job("one", attempt=0), _job("two", attempt=1), _job("three", attempt=2)])
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=FailingPipeline(),
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=4,
        clock=lambda: NOW,
    )
    await worker.run_until_idle()

    assert [(attempt, delay) for _, attempt, delay, _ in repository.retries] == [(1, 30), (2, 120), (3, 600)]
    assert all(error == ErrorCode.MODEL_TIMEOUT.value for *_, error in repository.retries)

    terminal_repository = MemoryRepository([_job("terminal", attempt=3)])
    terminal_worker = RecordedVideoWorker(
        repository=terminal_repository,
        pipeline=FailingPipeline(),
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=4,
        clock=lambda: NOW,
    )
    await terminal_worker.run_once()

    assert terminal_repository.retries == []
    assert terminal_repository.failures == [("terminal", 4, ErrorCode.MODEL_TIMEOUT.value)]


@pytest.mark.asyncio
async def test_worker_renews_lease_every_third_and_preserves_attempt_fence() -> None:
    repository = MemoryRepository([_job("renew")])
    pipeline = BlockingPipeline()
    waits: list[int] = []
    renewal_waiting = asyncio.Event()
    release_wait = asyncio.Event()
    later_wait = asyncio.Event()

    async def wait(seconds: float) -> None:
        waits.append(int(seconds))
        if len(waits) == 1:
            renewal_waiting.set()
            await release_wait.wait()
        else:
            await later_wait.wait()

    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
        wait=wait,
    )
    running = asyncio.create_task(worker.run_once())
    await renewal_waiting.wait()
    release_wait.set()
    await asyncio.sleep(0)
    pipeline.release.set()
    await running

    assert waits[0] == 30
    assert repository.renewals == [("renew", repository.claims[0][1], 1)]


@pytest.mark.asyncio
async def test_stop_prevents_new_claims_and_waits_for_active_job() -> None:
    repository = MemoryRepository([_job("first"), _job("second")])
    pipeline = BlockingPipeline()
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
    )

    running = asyncio.create_task(worker.run_until_idle())
    await pipeline.started.wait()
    worker.stop()
    await asyncio.sleep(0)
    assert not running.done()
    pipeline.release.set()
    await running

    assert [job_id for job_id, _, _ in repository.claims] == ["first"]


@pytest.mark.asyncio
async def test_worker_emits_json_readiness_and_redacted_error_codes() -> None:
    lines: list[str] = []
    repository = MemoryRepository([_job("failed")])
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=FailingPipeline(),
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=1,
        clock=lambda: NOW,
        output=lines.append,
    )

    readiness = worker.readiness()
    await worker.run_once()
    events = [json.loads(line) for line in lines]

    assert readiness["ready"] is True
    assert readiness["worker_concurrency"] == 1
    assert {event["event"] for event in events} >= {"worker.readiness", "job.failed"}
    failed_event = next(event for event in events if event["event"] == "job.failed")
    assert failed_event["error_code"] == "MODEL_TIMEOUT"
    assert failed_event["stage"] == "analyzing"
    assert "secret-value" not in "\n".join(lines)


def test_worker_accepts_short_positive_lease_and_uses_one_second_minimum() -> None:
    worker = RecordedVideoWorker(
        repository=MemoryRepository([]),
        pipeline=FailingPipeline(),
        worker_concurrency=1,
        lease_sec=1,
        max_attempts=1,
        clock=lambda: NOW,
    )

    assert worker.readiness()["ready"] is True


@pytest.mark.asyncio
async def test_repository_mark_failed_is_attempt_fenced_and_marks_asset_failed(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3", lease_seconds=90, clock=lambda: NOW)
    await repository.initialize()
    source = b"video"
    asset = Asset(
        asset_id="asset-1",
        display_filename="video.mp4",
        safe_filename="video.mp4",
        size_bytes=len(source),
        sha256=hashlib.sha256(source).hexdigest(),
        mime_type="video/mp4",
        source_extension="mp4",
        timeline_origin=NOW,
        status=AssetStatus.UPLOADING,
        created_at=NOW,
        updated_at=NOW,
    )
    session = UploadSession(
        session_id="session-1",
        identifier="upload-1",
        asset_id=asset.asset_id,
        total_chunks=1,
        filename=asset.display_filename,
        temp_dir="tmp",
        status=AssetStatus.UPLOADING,
        expires_at=NOW + timedelta(days=1),
    )
    await repository.create_upload_session(asset, session)
    await repository.record_chunk(session.session_id, 1, "checksum", size_bytes=len(source), path="000001.part")
    created = await repository.complete_upload(asset.asset_id, "pipeline-v1", now=NOW)
    claimed = await repository.claim_due_job("worker:claim", NOW)
    assert claimed is not None and claimed.job_id == created.job_id

    failed = await repository.mark_failed(
        claimed.job_id,
        claimed.lease_owner or "",
        ErrorCode.CORRUPT_MEDIA.value,
        attempt=claimed.attempt,
        now=NOW + timedelta(seconds=1),
    )

    assert failed.status is JobStatus.FAILED
    assert failed.last_error == ErrorCode.CORRUPT_MEDIA.value
    assert (await repository.get_asset(asset.asset_id)).status is AssetStatus.FAILED
    with pytest.raises(PermissionError, match="lease|attempt|running"):
        await repository.mark_failed(
            claimed.job_id,
            claimed.lease_owner or "",
            ErrorCode.CORRUPT_MEDIA.value,
            attempt=claimed.attempt,
            now=NOW + timedelta(seconds=2),
        )


def test_worker_cli_requires_config_path() -> None:
    assert parse_worker_args(["--config", "worker.yaml"]).config == Path("worker.yaml")
    with pytest.raises(SystemExit):
        parse_worker_args([])


def test_worker_cli_runs_from_source_checkout() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/recorded-video-worker.py", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
