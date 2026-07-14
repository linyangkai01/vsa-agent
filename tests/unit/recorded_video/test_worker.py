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

import vsa_agent.recorded_video.errors as recorded_video_errors
from vsa_agent.recorded_video.errors import ErrorCode, LeaseLostError, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, Job, JobStage, JobStatus, UploadSession
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.worker import RecordedVideoWorker, parse_worker_args

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def test_lease_lost_error_preserves_permission_error_compatibility() -> None:
    assert issubclass(recorded_video_errors.LeaseLostError, PermissionError)


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
        self.releases: list[tuple[str, str, int]] = []

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

    async def release_claim(
        self,
        job_id: str,
        owner: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job:
        self.releases.append((job_id, owner, attempt))
        return _job(job_id, attempt=attempt - 1).model_copy(update={"status": JobStatus.RETRY_WAIT, "next_run_at": now})

    async def get_job(self, job_id: str) -> Job:
        return _job(job_id).model_copy(update={"stage": JobStage.ANALYZING})


class BlockingPipeline:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.active = 0
        self.max_active = 0

    async def run(self, job: Job) -> object:
        del job
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        finally:
            self.active -= 1
        return object()


class CountingPipeline:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls = 0
        self.error = error

    async def run(self, job: Job) -> object:
        del job
        self.calls += 1
        if self.error is not None:
            raise self.error
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
async def test_worker_fails_claim_already_over_max_attempts_without_starting_pipeline() -> None:
    repository = MemoryRepository([_job("already-exhausted", attempt=3)])
    pipeline = CountingPipeline()
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
    )

    result = await worker.run_once()

    assert pipeline.calls == 0
    assert result is not None and result.status is JobStatus.FAILED
    assert repository.failures == [("already-exhausted", 4, "MAX_ATTEMPTS")]


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
async def test_one_second_lease_renews_strictly_before_expiry_with_fractional_wait() -> None:
    renewed = asyncio.Event()

    class RenewalRepository(MemoryRepository):
        async def renew_lease(self, job_id: str, owner: str, now: datetime, *, attempt: int) -> Job:
            result = await super().renew_lease(job_id, owner, now, attempt=attempt)
            renewed.set()
            return result.model_copy(update={"stage": JobStage.ANALYZING})

    repository = RenewalRepository([_job("short-lease")])
    pipeline = BlockingPipeline()
    first_wait_started = asyncio.Event()
    release_first_wait = asyncio.Event()
    never = asyncio.Event()
    waits: list[float] = []

    async def wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 1:
            first_wait_started.set()
            await release_first_wait.wait()
            return
        await never.wait()

    lines: list[str] = []
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=1,
        max_attempts=3,
        clock=lambda: NOW,
        wait=wait,
        output=lines.append,
    )
    running = asyncio.create_task(worker.run_once())
    await first_wait_started.wait()
    release_first_wait.set()
    await renewed.wait()
    pipeline.release.set()
    await running

    assert waits[0] == pytest.approx(1 / 3)
    heartbeat = next(json.loads(line) for line in lines if '"event":"job.heartbeat"' in line)
    assert heartbeat["stage"] == JobStage.ANALYZING.value
    completed = next(json.loads(line) for line in lines if '"event":"job.completed"' in line)
    assert completed["stage"] == JobStage.ANALYZING.value


@pytest.mark.asyncio
async def test_renewal_fence_failure_cancels_pipeline_and_emits_lease_lost() -> None:
    class LeaseLosingRepository(MemoryRepository):
        async def renew_lease(self, job_id: str, owner: str, now: datetime, *, attempt: int) -> Job:
            del job_id, owner, now, attempt
            raise LeaseLostError("lease owner does not match")

    repository = LeaseLosingRepository([_job("lost")])
    pipeline = BlockingPipeline()
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()

    async def wait(seconds: float) -> None:
        wait_started.set()
        assert seconds < 1
        await release_wait.wait()

    lines: list[str] = []
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=1,
        max_attempts=3,
        clock=lambda: NOW,
        wait=wait,
        output=lines.append,
    )
    running = asyncio.create_task(worker.run_once())
    await pipeline.started.wait()
    await wait_started.wait()
    release_wait.set()
    await pipeline.cancelled.wait()
    assert await running is None

    assert repository.failures == []
    assert any(json.loads(line)["event"] == "job.lease_lost" for line in lines)


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
async def test_stop_while_claim_is_in_flight_releases_claim_without_starting_pipeline() -> None:
    class DelayedClaimRepository(MemoryRepository):
        def __init__(self) -> None:
            super().__init__([_job("raced")])
            self.claim_started = asyncio.Event()
            self.return_claim = asyncio.Event()

        async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
            self.claim_started.set()
            await self.return_claim.wait()
            return await super().claim_due_job(owner, now)

    repository = DelayedClaimRepository()
    pipeline = CountingPipeline()
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
    )
    running = asyncio.create_task(worker.run_once())
    await repository.claim_started.wait()
    worker.stop()
    repository.return_claim.set()

    assert await running is None
    assert pipeline.calls == 0
    assert repository.releases == [("raced", repository.claims[0][1], 1)]


@pytest.mark.asyncio
async def test_run_emits_heartbeat_while_queue_drain_is_still_busy_and_stops_cleanly() -> None:
    repository = MemoryRepository([_job("busy")])
    pipeline = BlockingPipeline()
    heartbeat_waiting = asyncio.Event()
    heartbeat_tick = asyncio.Event()
    heartbeat_emitted = asyncio.Event()
    never = asyncio.Event()
    heartbeat_wait_calls = 0

    async def renewal_wait(seconds: float) -> None:
        del seconds
        await never.wait()

    async def heartbeat_wait(seconds: float) -> None:
        nonlocal heartbeat_wait_calls
        assert seconds == pytest.approx(30)
        heartbeat_wait_calls += 1
        if heartbeat_wait_calls == 1:
            heartbeat_waiting.set()
            await heartbeat_tick.wait()
            return
        await never.wait()

    lines: list[str] = []

    def output(line: str) -> None:
        lines.append(line)
        if json.loads(line)["event"] == "worker.heartbeat":
            heartbeat_emitted.set()

    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
        wait=renewal_wait,
        heartbeat_wait=heartbeat_wait,
        output=output,
    )
    running = asyncio.create_task(worker.run())
    await pipeline.started.wait()
    await heartbeat_waiting.wait()
    heartbeat_tick.set()
    await heartbeat_emitted.wait()

    worker.stop()
    pipeline.release.set()
    await running

    heartbeat = next(json.loads(line) for line in lines if json.loads(line)["event"] == "worker.heartbeat")
    assert heartbeat["active_jobs"] == 1
    assert heartbeat["jobs"] == [{"attempt": 1, "job_id": "busy", "stage": "analyzing"}]
    assert json.loads(lines[-1])["event"] == "worker.stopped"


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


@pytest.mark.asyncio
async def test_filesystem_permission_error_is_recorded_as_permanent_failure() -> None:
    lines: list[str] = []
    repository = MemoryRepository([_job("permission")])
    pipeline = CountingPipeline(PermissionError("private filesystem path"))
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=1,
        lease_sec=90,
        max_attempts=3,
        clock=lambda: NOW,
        output=lines.append,
    )

    result = await worker.run_once()

    assert result is not None and result.status is JobStatus.FAILED
    assert repository.failures == [("permission", 1, "UNEXPECTED")]
    assert not any(json.loads(line)["event"] == "job.lease_lost" for line in lines)


def test_worker_accepts_one_second_lease() -> None:
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

    with pytest.raises(LeaseLostError, match="lease owner"):
        await repository.mark_failed(
            claimed.job_id,
            "wrong-owner",
            ErrorCode.CORRUPT_MEDIA.value,
            attempt=claimed.attempt,
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(LeaseLostError, match="attempt"):
        await repository.mark_failed(
            claimed.job_id,
            claimed.lease_owner or "",
            ErrorCode.CORRUPT_MEDIA.value,
            attempt=claimed.attempt + 1,
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(LeaseLostError, match="active lease"):
        await repository.mark_failed(
            claimed.job_id,
            claimed.lease_owner or "",
            ErrorCode.CORRUPT_MEDIA.value,
            attempt=claimed.attempt,
            now=NOW + timedelta(seconds=90),
        )

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
    with pytest.raises(LeaseLostError, match="lease|attempt|running"):
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
