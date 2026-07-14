"""Bounded, leased worker orchestration for recorded-video jobs."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import signal
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from vsa_agent.config import AppConfig, validate_recorded_video_runtime
from vsa_agent.recorded_video.errors import LeaseLostError, RecordedVideoError
from vsa_agent.recorded_video.models import Job
from vsa_agent.recorded_video.pipeline import PipelineCancelled

_RETRY_BACKOFF_SECONDS = (30, 120, 600)


class WorkerRepository(Protocol):
    async def claim_due_job(self, owner: str, now: datetime) -> Job | None: ...

    async def renew_lease(self, job_id: str, owner: str, now: datetime, *, attempt: int) -> Job: ...

    async def renew_cleanup_lease(
        self,
        job: Job,
        now: datetime,
        lease_until: datetime,
    ) -> Job: ...

    async def release_claim(
        self,
        job_id: str,
        owner: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job: ...

    async def schedule_retry(
        self,
        job_id: str,
        owner: str,
        next_run_at: datetime,
        error: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job: ...

    async def mark_failed(
        self,
        job_id: str,
        owner: str,
        error: str,
        *,
        attempt: int,
        now: datetime,
    ) -> Job: ...

    async def get_job(self, job_id: str) -> Job: ...


class PipelineRunner(Protocol):
    async def run(self, job: Job) -> object: ...


class RecordedVideoWorker:
    """Claim and execute jobs while preserving repository lease fencing."""

    def __init__(
        self,
        *,
        repository: WorkerRepository,
        pipeline: PipelineRunner,
        worker_concurrency: int,
        lease_sec: int,
        max_attempts: int,
        clock: Callable[[], datetime] | None = None,
        wait: Callable[[float], Awaitable[None]] | None = None,
        heartbeat_wait: Callable[[float], Awaitable[None]] | None = None,
        output: Callable[[str], None] | None = None,
        worker_id: str | None = None,
    ) -> None:
        if worker_concurrency <= 0:
            raise ValueError("worker_concurrency must be positive")
        if lease_sec <= 0:
            raise ValueError("lease_sec must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._repository = repository
        self._pipeline = pipeline
        self._worker_concurrency = worker_concurrency
        self._lease_sec = lease_sec
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: datetime.now(UTC))
        self._wait = wait or asyncio.sleep
        self._heartbeat_wait = heartbeat_wait or self._wait
        self._output = output or print
        self._worker_id = worker_id or str(uuid.uuid4())
        self._semaphore = asyncio.Semaphore(worker_concurrency)
        self._stopping = asyncio.Event()
        self._active_jobs: dict[str, tuple[str, int]] = {}

    @property
    def active_jobs(self) -> int:
        return len(self._active_jobs)

    def stop(self) -> None:
        """Stop accepting claims; active attempts retain their leases until they finish."""
        if not self._stopping.is_set():
            self._stopping.set()
            self._emit("worker.stopping", ready=False)

    def readiness(self) -> dict[str, Any]:
        ready = not self._stopping.is_set()
        payload = {
            "ready": ready,
            "worker_concurrency": self._worker_concurrency,
            "active_jobs": self.active_jobs,
        }
        self._emit("worker.readiness", **payload)
        return payload

    async def run_once(self) -> object | Job | None:
        """Claim and execute at most one due job."""
        if self._stopping.is_set():
            return None
        async with self._semaphore:
            if self._stopping.is_set():
                return None
            owner = f"{self._worker_id}:{uuid.uuid4()}"
            job = await self._repository.claim_due_job(owner, self._now())
            if job is None:
                return None
            if job.lease_owner != owner:
                raise RuntimeError("repository returned a claim with a different lease owner")
            if self._stopping.is_set():
                try:
                    await self._repository.release_claim(
                        job.job_id,
                        owner,
                        attempt=job.attempt,
                        now=self._now(),
                    )
                except LeaseLostError:
                    self._emit_job("job.lease_lost", job, error_code="LEASE_LOST")
                else:
                    self._emit_job("job.claim_released", job)
                return None
            self._active_jobs[job.job_id] = (owner, job.attempt)
            self._emit_job("job.claimed", job)
            try:
                if await self._cancel_requested(job):
                    try:
                        await self._run_cleanup_with_renewal(job)
                    except LeaseLostError:
                        raise
                    except Exception:
                        self._emit_job("job.cleanup_failed", job, error_code="CLEANUP_FAILED")
                        return None
                    raise PipelineCancelled(job)
                if job.attempt > self._max_attempts:
                    return await self._record_failure(job, "MAX_ATTEMPTS", retryable=False)
                result = await self._run_with_renewal(job)
            except asyncio.CancelledError:
                self._emit_job("job.interrupted", job, error_code="WORKER_CANCELLED")
                raise
            except PipelineCancelled:
                finish_cancel = getattr(self._repository, "finish_cancel", None)
                if finish_cancel is None:
                    raise
                cancelled = await finish_cancel(job, self._now())
                if cancelled is None:
                    raise RuntimeError("pipeline reported cancellation without a durable cancel request")
                self._emit_job("job.cancelled", cancelled)
                return cancelled
            except LeaseLostError:
                self._emit_job("job.lease_lost", job, error_code="LEASE_LOST")
                return None
            except RecordedVideoError as exc:
                return await self._record_failure(job, exc.code.value, retryable=exc.retryable)
            except Exception:
                return await self._record_failure(job, "UNEXPECTED", retryable=False)
            else:
                self._emit_job("job.completed", await self._latest_job_for_event(job))
                return result
            finally:
                self._active_jobs.pop(job.job_id, None)

    async def run_until_idle(self) -> list[object | Job]:
        """Drain all jobs currently claimable without polling or sleeping."""
        completed: list[object | Job] = []
        while not self._stopping.is_set():
            tasks = [asyncio.create_task(self.run_once()) for _ in range(self._worker_concurrency)]
            try:
                batch = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            claimed = [result for result in batch if result is not None]
            completed.extend(claimed)
            if not claimed:
                break
        return completed

    async def run(self) -> None:
        """Run until stopped, waiting between idle claim cycles without busy looping."""
        self.readiness()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self._stopping.is_set():
                await self.run_until_idle()
                if self._stopping.is_set():
                    break
                await self._wait_or_stop(self._heartbeat_interval, waiter=self._wait)
        except asyncio.CancelledError:
            self.stop()
            raise
        finally:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self._emit("worker.stopped", ready=False, active_jobs=self.active_jobs)

    async def _run_with_renewal(self, job: Job) -> object:
        pipeline_task = asyncio.create_task(self._pipeline.run(job))
        renewal_task = asyncio.create_task(self._renew_lease(job))
        try:
            done, _ = await asyncio.wait(
                {pipeline_task, renewal_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pipeline_task in done:
                return await pipeline_task
            renewal_error = renewal_task.exception()
            if renewal_error is None:
                raise RuntimeError("lease renewal stopped before the pipeline completed")
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
            if isinstance(renewal_error, LeaseLostError) and await self._cancel_requested(job):
                await self._run_cleanup_with_renewal(job)
                raise PipelineCancelled(job)
            raise renewal_error
        finally:
            for task in (pipeline_task, renewal_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pipeline_task, renewal_task, return_exceptions=True)

    async def _renew_lease(self, job: Job) -> None:
        owner = job.lease_owner
        if owner is None:
            raise RuntimeError("repository returned a claimed job without a lease owner")
        while True:
            await self._wait(self._renewal_interval)
            renewed = await self._repository.renew_lease(
                job.job_id,
                owner,
                self._now(),
                attempt=job.attempt,
            )
            self._emit_job("job.heartbeat", renewed)

    async def _run_cleanup_with_renewal(self, job: Job) -> None:
        cleanup = getattr(self._pipeline, "cleanup_after_cancel", None)
        if cleanup is None:
            raise RuntimeError("cancel cleanup requires pipeline cleanup support")
        cleanup_task = asyncio.create_task(cleanup(job))
        renewal_task = asyncio.create_task(self._renew_cleanup_lease(job))
        try:
            done, _ = await asyncio.wait(
                {cleanup_task, renewal_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if renewal_task in done:
                renewal_error = renewal_task.exception()
                if renewal_error is None:
                    raise RuntimeError("cleanup lease renewal stopped before cleanup completed")
                cleanup_task.cancel()
                await asyncio.gather(cleanup_task, return_exceptions=True)
                raise renewal_error
            await cleanup_task
        finally:
            for task in (cleanup_task, renewal_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(cleanup_task, renewal_task, return_exceptions=True)

    async def _renew_cleanup_lease(self, job: Job) -> None:
        while True:
            await self._wait(self._renewal_interval)
            now = self._now()
            renewed = await self._repository.renew_cleanup_lease(
                job,
                now,
                now + timedelta(seconds=self._lease_sec),
            )
            self._emit_job("job.heartbeat", renewed)

    async def _cancel_requested(self, job: Job) -> bool:
        check = getattr(self._repository, "is_cancel_requested", None)
        if check is None:
            return False
        try:
            return bool(await check(job, self._now()))
        except LeaseLostError:
            return False

    async def _record_failure(self, job: Job, error_code: str, *, retryable: bool) -> Job | None:
        owner = job.lease_owner
        if owner is None:
            return None
        now = self._now()
        event_job = await self._latest_job_for_event(job)
        try:
            if retryable and job.attempt < self._max_attempts:
                delay = _RETRY_BACKOFF_SECONDS[min(job.attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)]
                result = await self._repository.schedule_retry(
                    job.job_id,
                    owner,
                    now + timedelta(seconds=delay),
                    error_code,
                    attempt=job.attempt,
                    now=now,
                )
                self._emit_job("job.retry_scheduled", event_job, error_code=error_code, retry_delay_sec=delay)
                return result
            result = await self._repository.mark_failed(
                job.job_id,
                owner,
                error_code,
                attempt=job.attempt,
                now=now,
            )
            self._emit_job("job.failed", event_job, error_code=error_code)
            return result
        except LeaseLostError:
            self._emit_job("job.lease_lost", event_job, error_code="LEASE_LOST")
            return None

    @property
    def _renewal_interval(self) -> float:
        return max(0.05, self._lease_sec / 3)

    @property
    def _heartbeat_interval(self) -> float:
        return self._renewal_interval

    async def _heartbeat_loop(self) -> None:
        while not self._stopping.is_set():
            await self._wait_or_stop(self._heartbeat_interval, waiter=self._heartbeat_wait)
            if self._stopping.is_set():
                return
            jobs = await self._active_job_snapshot()
            self._emit(
                "worker.heartbeat",
                ready=True,
                active_jobs=len(jobs),
                worker_concurrency=self._worker_concurrency,
                jobs=jobs,
            )

    async def _latest_job_for_event(self, job: Job) -> Job:
        try:
            current = await self._repository.get_job(job.job_id)
        except (KeyError, OSError):
            return job
        return job.model_copy(update={"stage": current.stage})

    async def _active_job_snapshot(self) -> list[dict[str, Any]]:
        snapshot: list[dict[str, Any]] = []
        for job_id, (_, attempt) in list(self._active_jobs.items()):
            stage = None
            try:
                current = await self._repository.get_job(job_id)
                stage = current.stage.value if current.stage is not None else None
            except (KeyError, OSError):
                pass
            snapshot.append({"job_id": job_id, "attempt": attempt, "stage": stage})
        return snapshot

    async def _wait_or_stop(
        self,
        seconds: float,
        *,
        waiter: Callable[[float], Awaitable[None]],
    ) -> None:
        wait_task = asyncio.create_task(waiter(seconds))
        stop_task = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait({wait_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (wait_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(wait_task, stop_task, return_exceptions=True)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _emit_job(self, event: str, job: Job, **fields: Any) -> None:
        self._emit(
            event,
            job_id=job.job_id,
            asset_id=job.asset_id,
            attempt=job.attempt,
            stage=job.stage.value if job.stage is not None else None,
            **fields,
        )

    def _emit(self, event: str, **fields: Any) -> None:
        payload = {
            "timestamp": self._now().isoformat(),
            "level": "error" if "error_code" in fields else "info",
            "event": event,
            "worker_id": self._worker_id,
            **fields,
        }
        self._output(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def parse_worker_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the recorded-video processing worker")
    parser.add_argument("--config", type=Path, required=True, help="Path to the application YAML configuration")
    return parser.parse_args(argv)


WorkerFactory = Callable[[AppConfig], RecordedVideoWorker | Awaitable[RecordedVideoWorker]]


async def run_configured_worker(config_path: Path, worker_factory: WorkerFactory | None = None) -> int:
    """Load configuration and run a supplied production worker composition."""
    try:
        config = AppConfig.from_yaml(config_path)
        diagnostics = validate_recorded_video_runtime(config)
        if not config.recorded_video.enabled or not diagnostics.ok or worker_factory is None:
            raise ValueError("recorded-video worker dependencies are not ready")
        worker_or_awaitable = worker_factory(config)
        worker = await worker_or_awaitable if inspect.isawaitable(worker_or_awaitable) else worker_or_awaitable
    except Exception:
        print(
            json.dumps(
                {
                    "event": "worker.readiness",
                    "level": "error",
                    "ready": False,
                    "error_code": "CONFIGURATION",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(signum, lambda _signum, _frame: worker.stop())
    await worker.run()
    return 0


def main(argv: Sequence[str] | None = None, *, worker_factory: WorkerFactory | None = None) -> int:
    args = parse_worker_args(argv)
    return asyncio.run(run_configured_worker(args.config, worker_factory))


if __name__ == "__main__":
    sys.exit(main())
