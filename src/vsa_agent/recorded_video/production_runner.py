"""End-to-end production recovery acceptance orchestration."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from vsa_agent.recorded_video.production_acceptance import (
    AcceptanceState,
    JobIdentity,
    LauncherArgs,
    LauncherController,
    ProductionApiClient,
    RunHandle,
    ValidationError,
    assert_recovery,
    atomic_write_json,
    create_jobs_concurrently,
    parse_cases,
    read_job_snapshot,
    wait_for_recovery_baseline,
    wait_jobs_concurrently,
)
from vsa_agent.recorded_video.production_evidence import (
    AcceptanceEvidence,
    collect_business_evidence,
    load_runtime_evidence,
    render_acceptance_report,
    render_failure_report,
    scan_runtime_logs,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProductionAcceptanceOptions:
    repo_root: Path
    videos: tuple[Path, ...]
    queries: tuple[str, ...]
    config: Path
    index: str
    data_root: Path
    conda_env: str | None
    api_port: int
    es_port: int
    ui_port: int
    report: Path
    timeout: float = 900.0
    poll_interval: float = 0.25
    minimum_similarity: float = 0.2

    def __post_init__(self) -> None:
        repo_root = self.repo_root.resolve(strict=True)
        config = self.config.resolve(strict=True)
        expected_config = (repo_root / "config.yaml").resolve(strict=True)
        if config != expected_config:
            raise ValueError("--config must reference the repository config.yaml used by the stack launcher")
        if self.timeout <= 0 or self.poll_interval <= 0 or not 0.0 <= self.minimum_similarity <= 1.0:
            raise ValueError("acceptance timeouts and similarity threshold are invalid")
        object.__setattr__(self, "repo_root", repo_root)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "data_root", self.data_root.resolve(strict=False))
        object.__setattr__(self, "report", self.report.resolve(strict=False))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _snapshot_payload(snapshot: AcceptanceState) -> dict[str, object]:
    return {
        "cases": [{"path": str(case.path), "query": case.query, "sha256": case.sha256} for case in snapshot.cases],
        "jobs": {job_id: asdict(job) for job_id, job in snapshot.jobs.items()},
        "segment_ids": list(snapshot.segment_ids),
    }


def _write_state(
    path: Path,
    *,
    phase: str,
    controller: LauncherController,
    handles: list[RunHandle],
    jobs: tuple[JobIdentity, ...] = (),
    baseline: AcceptanceState | None = None,
) -> None:
    atomic_write_json(
        path,
        {
            "acceptance_id": controller.acceptance_id,
            "phase": phase,
            "updated_at": _timestamp(),
            "launcher_runs": [handle.run_id for handle in handles],
            "jobs": [asdict(job) for job in jobs],
            "baseline": _snapshot_payload(baseline) if baseline is not None else None,
        },
    )


def _configure_acceptance_logging(path: Path) -> tuple[logging.Handler, ...]:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter("[acceptance] %(levelname)s %(message)s"))
    logger = logging.getLogger("vsa_agent.recorded_video")
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    return file_handler, console_handler


def _stop_active_launchers(controller: LauncherController, handles: list[RunHandle], timeout: float) -> None:
    for handle in reversed(handles):
        try:
            controller.stop_launcher(handle)
            controller.wait_exit(handle, timeout=min(timeout, 120.0))
        except ValidationError:
            LOGGER.exception("production_acceptance.cleanup.launcher_failed run_id=%s", handle.run_id)


def _best_effort_delete(client: httpx.Client, ui_port: int, jobs: tuple[JobIdentity, ...]) -> None:
    for job in jobs:
        url = f"http://127.0.0.1:{ui_port}/api/v1/videos/{job.asset_id}"
        for _attempt in range(5):
            try:
                response = client.delete(url, timeout=10.0)
            except httpx.HTTPError:
                LOGGER.exception("production_acceptance.cleanup.asset_request_failed asset_id=%s", job.asset_id)
                break
            if response.status_code in {204, 404, 410}:
                LOGGER.info("production_acceptance.cleanup.asset_done asset_id=%s", job.asset_id)
                break
            if response.status_code != 202:
                LOGGER.error(
                    "production_acceptance.cleanup.asset_failed asset_id=%s status=%d",
                    job.asset_id,
                    response.status_code,
                )
                break
            time.sleep(0.25)


def run_production_acceptance(options: ProductionAcceptanceOptions) -> int:
    cases = parse_cases(options.videos, options.queries)
    controller = LauncherController(
        LauncherArgs(
            repo_root=options.repo_root,
            api_port=options.api_port,
            es_port=options.es_port,
            ui_port=options.ui_port,
            index=options.index,
            data_root=options.data_root,
            conda_env=options.conda_env,
            env={},
        ),
        startup_timeout=min(options.timeout, 180.0),
        poll_interval=min(options.poll_interval, 1.0),
    )
    controller.acceptance_dir.mkdir(parents=True, exist_ok=True)
    state_path = controller.acceptance_dir / "state.json"
    log_handlers = _configure_acceptance_logging(controller.acceptance_dir / "acceptance.log")
    handles: list[RunHandle] = []
    jobs: tuple[JobIdentity, ...] = ()
    baseline: AcceptanceState | None = None
    shared_client = httpx.Client(timeout=options.timeout, follow_redirects=False)
    api_client = ProductionApiClient(
        f"http://127.0.0.1:{options.api_port}",
        client=shared_client,
        request_timeout=options.timeout,
        poll_interval=options.poll_interval,
    )
    try:
        LOGGER.info("production_acceptance.phase.start acceptance_id=%s", controller.acceptance_id)
        first = controller.start()
        handles.append(first)
        controller.wait_ready(first)
        LOGGER.info("production_acceptance.phase.first_runtime_ready run_id=%s", first.run_id)
        _write_state(state_path, phase="first_runtime_ready", controller=controller, handles=handles)

        jobs = create_jobs_concurrently(api_client, cases)
        LOGGER.info("production_acceptance.phase.uploads_completed jobs=%s", ",".join(job.job_id for job in jobs))
        _write_state(
            state_path,
            phase="uploads_completed",
            controller=controller,
            handles=handles,
            jobs=jobs,
        )
        database = options.data_root / "recorded-video.sqlite3"
        baseline = wait_for_recovery_baseline(
            database,
            cases,
            jobs,
            timeout=options.timeout,
            poll_interval=options.poll_interval,
        )
        LOGGER.info(
            "production_acceptance.phase.checkpoint_captured checkpoints=%d",
            len(baseline.checkpoints),
        )
        _write_state(
            state_path,
            phase="checkpoint_captured",
            controller=controller,
            handles=handles,
            jobs=jobs,
            baseline=baseline,
        )

        controller.stop_worker(first)
        first_status = controller.wait_exit(first, timeout=120.0)
        if first_status == 0:
            raise ValidationError(
                "recovery",
                "first launcher exited successfully after Worker TERM; interruption was not proven",
            )
        _write_state(
            state_path,
            phase="worker_interrupted",
            controller=controller,
            handles=handles,
            jobs=jobs,
            baseline=baseline,
        )

        second = controller.restart()
        handles.append(second)
        controller.wait_ready(second)
        LOGGER.info("production_acceptance.phase.second_runtime_ready run_id=%s", second.run_id)
        public_after = wait_jobs_concurrently(api_client, jobs, options.timeout)
        persisted_after = {job.job_id: read_job_snapshot(database, job) for job in jobs}
        for job_id, public in public_after.items():
            persisted = persisted_after[job_id]
            if (public.status, public.stage, public.attempt) != (
                persisted.status,
                persisted.stage,
                persisted.attempt,
            ):
                raise ValidationError("recovery", f"API and SQLite state differ for recovered job {job_id}")
        assert_recovery(baseline, persisted_after)
        LOGGER.info("production_acceptance.phase.recovery_completed jobs=3")
        _write_state(
            state_path,
            phase="recovery_completed",
            controller=controller,
            handles=handles,
            jobs=jobs,
            baseline=baseline,
        )

        runtime = load_runtime_evidence(
            second.run_dir / "config.yaml",
            data_root=options.data_root,
            index=options.index,
        )
        business = collect_business_evidence(
            shared_client,
            ui_url=f"http://127.0.0.1:{options.ui_port}",
            api_url=f"http://127.0.0.1:{options.api_port}",
            runtime=runtime,
            data_root=options.data_root,
            cases=cases,
            jobs=jobs,
            minimum_similarity=options.minimum_similarity,
            timeout=options.timeout,
            poll_interval=options.poll_interval,
        )
        LOGGER.info(
            "production_acceptance.phase.business_evidence_completed documents=%d segments=%d",
            business.document_count,
            len(business.segment_ids),
        )
        controller.stop_launcher(second)
        second_status = controller.wait_exit(second, timeout=120.0)
        if second_status == 0:
            raise ValidationError("runtime", "second launcher shutdown did not report an interrupted lifecycle")
        secret_scan = scan_runtime_logs(handles, business)
        render_acceptance_report(
            AcceptanceEvidence(
                acceptance_id=controller.acceptance_id,
                launcher_runs=tuple(handles),
                runtime=runtime,
                business=business,
                timestamp_utc=_timestamp(),
                secret_scan=secret_scan,
            ),
            options.report,
        )
        _write_state(
            state_path,
            phase="passed",
            controller=controller,
            handles=handles,
            jobs=jobs,
            baseline=baseline,
        )
        LOGGER.info(
            "production_acceptance.pass acceptance_id=%s report=%s",
            controller.acceptance_id,
            options.report,
        )
        return 0
    except KeyboardInterrupt:
        error = ValidationError("runtime", "production acceptance was interrupted by the user")
        if handles and controller.is_running(handles[-1]):
            _best_effort_delete(shared_client, options.ui_port, jobs)
        render_failure_report(
            options.report,
            acceptance_id=controller.acceptance_id,
            error=error,
            launcher_runs=handles,
        )
        return 130
    except ValidationError as error:
        LOGGER.exception(
            "production_acceptance.fail acceptance_id=%s field=%s",
            controller.acceptance_id,
            error.field,
        )
        if handles and controller.is_running(handles[-1]):
            _best_effort_delete(shared_client, options.ui_port, jobs)
        render_failure_report(
            options.report,
            acceptance_id=controller.acceptance_id,
            error=error,
            launcher_runs=handles,
        )
        _write_state(
            state_path,
            phase=f"failed:{error.field}",
            controller=controller,
            handles=handles,
            jobs=jobs,
            baseline=baseline,
        )
        return 1
    except Exception:
        LOGGER.exception("production_acceptance.fail acceptance_id=%s field=internal", controller.acceptance_id)
        error = ValidationError("internal", "unexpected acceptance error; inspect acceptance.log")
        if handles and controller.is_running(handles[-1]):
            _best_effort_delete(shared_client, options.ui_port, jobs)
        render_failure_report(
            options.report,
            acceptance_id=controller.acceptance_id,
            error=error,
            launcher_runs=handles,
        )
        return 1
    finally:
        _stop_active_launchers(controller, handles, options.timeout)
        shared_client.close()
        logger = logging.getLogger("vsa_agent.recorded_video")
        for handler in log_handlers:
            logger.removeHandler(handler)
            handler.close()
