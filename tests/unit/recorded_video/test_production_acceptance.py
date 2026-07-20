from __future__ import annotations

import hashlib
import importlib
import json
import os
import signal
import sqlite3
import subprocess
import threading
from pathlib import Path

import pytest


def _production_acceptance_module():
    try:
        return importlib.import_module("vsa_agent.recorded_video.production_acceptance")
    except ModuleNotFoundError:
        pytest.fail("production acceptance module does not exist")


def test_parse_cases_requires_three_distinct_video_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    third = tmp_path / "three.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    third.write_bytes(b"one")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="three distinct video files"):
        module.parse_cases([first, second, third], ["forklift"])


def test_parse_cases_maps_one_query_to_three_distinct_videos(tmp_path: Path) -> None:
    videos = []
    for index, suffix in enumerate((".mp4", ".mp4", ".mkv"), start=1):
        path = tmp_path / f"case-{index}{suffix}"
        path.write_bytes(f"video-{index}".encode())
        videos.append(path)

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, ["forklift near worker"])

    assert [case.path for case in cases] == [path.resolve() for path in videos]
    assert [case.query for case in cases] == ["forklift near worker"] * 3
    assert len({case.sha256 for case in cases}) == 3


def test_parse_cases_maps_three_queries_positionally(tmp_path: Path) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)
    queries = ["forklift", "worker fall", "smoke"]

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, queries)

    assert [case.query for case in cases] == queries


@pytest.mark.parametrize("queries", ([], ["one", "two"], ["  "]))
def test_parse_cases_rejects_invalid_query_cardinality_or_blanks(tmp_path: Path, queries: list[str]) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="one or three non-empty queries"):
        module.parse_cases(videos, queries)


def test_parse_cases_rejects_non_file_inputs_with_stable_error(tmp_path: Path) -> None:
    directory = tmp_path / "directory.mp4"
    directory.mkdir()
    second = tmp_path / "second.mp4"
    third = tmp_path / "third.mkv"
    second.write_bytes(b"second")
    third.write_bytes(b"third")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="regular readable video files"):
        module.parse_cases([directory, second, third], ["forklift"])


def test_validation_error_exposes_field_and_message() -> None:
    module = _production_acceptance_module()

    error = module.ValidationError("worker_identity", "worker manifest is invalid")

    assert str(error) == "worker manifest is invalid"
    assert error.field == "worker_identity"
    assert error.message == "worker manifest is invalid"


def test_atomic_write_json_replaces_existing_file_without_leaving_temporary_files(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    target = tmp_path / "acceptance-state.json"
    target.write_text('{"state":"old"}\n', encoding="utf-8")

    module.atomic_write_json(target, {"state": "ready", "jobs": ["job-1"]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "ready", "jobs": ["job-1"]}
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_atomic_write_json_preserves_previous_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _production_acceptance_module()
    target = tmp_path / "acceptance-state.json"
    target.write_text('{"state":"old"}\n', encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace denied")

    monkeypatch.setattr(module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace denied"):
        module.atomic_write_json(target, {"state": "new"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "old"}
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def _write_worker_manifest(path: Path, *, run_id: str, worker_pid: int, command: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "processes": [
                    {
                        "component": "worker",
                        "pid": worker_pid,
                        "command": command or "python scripts/recorded-video-worker.py --config <runtime-config>",
                        "started_at": "2026-07-21T00:00:00Z",
                        "exit_status": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_fake_proc(
    proc_root: Path,
    *,
    run_dir: Path,
    worker_pid: int,
    uid: int,
    command: list[str] | None = None,
) -> None:
    process_dir = proc_root / str(worker_pid)
    process_dir.mkdir(parents=True)
    (process_dir / "status").write_text(
        f"Name:\tpython\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )
    arguments = command or [
        "python",
        str(Path("scripts") / "runtime-log-supervisor.py"),
        "--label",
        "worker",
        "--stack-log",
        str(run_dir / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        str(Path("scripts") / "recorded-video-worker.py"),
        "--config",
        str(run_dir / "config.yaml"),
    ]
    (process_dir / "cmdline").write_bytes(b"\0".join(os.fsencode(item) for item in arguments) + b"\0")


def test_validate_worker_identity_rejects_malformed_manifest(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    manifest.parent.mkdir()
    manifest.write_text("{not-json", encoding="utf-8")

    with pytest.raises(module.ValidationError, match="JSON") as raised:
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")

    assert raised.value.field == "worker_identity"


def test_validate_worker_identity_rejects_foreign_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    _write_worker_manifest(manifest, run_id="run-b", worker_pid=101)

    with pytest.raises(module.ValidationError, match="run ID"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")


def test_validate_worker_identity_requires_one_active_worker(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"run_id": "run-a", "processes": []}), encoding="utf-8")

    with pytest.raises(module.ValidationError, match="one active worker"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")


def test_validate_worker_identity_rejects_foreign_uid(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=2000)

    with pytest.raises(module.ValidationError, match="current UID"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_wrong_worker_command(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101, command="python unrelated.py")
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000)

    with pytest.raises(module.ValidationError, match="worker command"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_log_path_from_another_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    command = [
        "python",
        "scripts/runtime-log-supervisor.py",
        "--stack-log",
        str(tmp_path / "run-b" / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        "scripts/recorded-video-worker.py",
        "--config",
        str(run_dir / "config.yaml"),
    ]
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000, command=command)

    with pytest.raises(module.ValidationError, match="stack log path"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_config_from_another_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    command = [
        "python",
        "scripts/runtime-log-supervisor.py",
        "--stack-log",
        str(run_dir / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        "scripts/recorded-video-worker.py",
        "--config",
        str(tmp_path / "run-b" / "config.yaml"),
    ]
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000, command=command)

    with pytest.raises(module.ValidationError, match="runtime config path"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_accepts_bound_worker_supervisor(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000)

    module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


_RUN_IDS = (
    "123e4567-e89b-42d3-a456-426614174001",
    "123e4567-e89b-42d3-a456-426614174002",
)


class _FakeLauncherProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-launcher", timeout)
        return self.returncode


class _FakeProcessRunner:
    def __init__(self, repo_root: Path, proc_root: Path, run_ids: tuple[str, ...] = _RUN_IDS) -> None:
        self.repo_root = repo_root
        self.proc_root = proc_root
        self.run_ids = list(run_ids)
        self.invocations: list[dict[str, object]] = []
        self.signals: list[tuple[int, signal.Signals]] = []
        self.processes: list[_FakeLauncherProcess] = []
        self.worker_to_process: dict[int, _FakeLauncherProcess] = {}
        self.now = 0.0

    def start(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> _FakeLauncherProcess:
        run_id = self.run_ids.pop(0)
        launcher_pid = 4000 + len(self.processes)
        worker_pid = 5000 + len(self.processes)
        process = _FakeLauncherProcess(launcher_pid)
        self.processes.append(process)
        self.worker_to_process[worker_pid] = process
        self.invocations.append({"arguments": list(arguments), "cwd": cwd, "env": dict(env), "log_path": log_path})

        run_dir = self.repo_root / ".runtime" / "es-stack" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "launcher.pid").write_text(str(launcher_pid), encoding="utf-8")
        (run_dir / "stack.log").write_text("[stack] PASS: ES recorded-video runtime stack is ready\n", encoding="utf-8")
        processes = [
            {
                "component": component,
                "pid": worker_pid if component == "worker" else worker_pid + offset,
                "command": "python scripts/recorded-video-worker.py --config <runtime-config>"
                if component == "worker"
                else component,
                "started_at": "2026-07-21T00:00:00Z",
                "exit_status": None,
            }
            for offset, component in enumerate(("es", "api", "worker", "ui"), start=1)
        ]
        (run_dir / "processes.json").write_text(
            json.dumps({"run_id": run_id, "processes": processes}), encoding="utf-8"
        )
        _write_fake_proc(self.proc_root, run_dir=run_dir, worker_pid=worker_pid, uid=1000)
        latest = self.repo_root / ".runtime" / "es-stack" / "latest"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(str(run_dir), encoding="utf-8")
        return process

    def send_signal(self, pid: int, requested_signal: signal.Signals) -> None:
        self.signals.append((pid, requested_signal))
        process = self.worker_to_process.get(pid)
        if process is not None:
            process.returncode = 128 + int(requested_signal)

    def current_uid(self) -> int:
        return 1000

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _fake_launcher_args(tmp_path: Path):
    module = _production_acceptance_module()
    return module.LauncherArgs(
        repo_root=tmp_path,
        api_port=8000,
        es_port=9200,
        ui_port=3000,
        index="vsa-video-embeddings",
        data_root=tmp_path / "video-data",
        conda_env="vsa-agent",
        env={"OPENAI_API_KEY": "test-secret"},
    )


def test_controller_start_binds_new_run_and_exact_production_arguments(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    proc_root = tmp_path / "proc"
    runner = _FakeProcessRunner(tmp_path, proc_root, (_RUN_IDS[0],))
    controller = module.LauncherController(
        _fake_launcher_args(tmp_path), runner=runner, proc_root=proc_root, startup_timeout=1.0
    )

    handle = controller.start()

    assert handle.run_id == _RUN_IDS[0]
    assert handle.run_dir == tmp_path / ".runtime" / "es-stack" / "runs" / _RUN_IDS[0]
    assert handle.process_pid == 4000
    assert runner.invocations[0]["arguments"] == [
        "bash",
        "scripts/es-runtime-stack.sh",
        "--api-port",
        "8000",
        "--es-port",
        "9200",
        "--ui-port",
        "3000",
        "--index",
        "vsa-video-embeddings",
        "--data-root",
        str(tmp_path / "video-data"),
        "--conda-env",
        "vsa-agent",
    ]
    assert runner.invocations[0]["cwd"] == tmp_path.resolve()


def test_controller_wait_ready_validates_full_stack_and_worker_identity(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    proc_root = tmp_path / "proc"
    runner = _FakeProcessRunner(tmp_path, proc_root, (_RUN_IDS[0],))
    controller = module.LauncherController(
        _fake_launcher_args(tmp_path), runner=runner, proc_root=proc_root, startup_timeout=1.0
    )
    handle = controller.start()

    assert controller.wait_ready(handle) == handle


def test_controller_rejects_worker_pid_from_a_foreign_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    proc_root = tmp_path / "proc"
    runner = _FakeProcessRunner(tmp_path, proc_root, ())
    controller = module.LauncherController(
        _fake_launcher_args(tmp_path), runner=runner, proc_root=proc_root, startup_timeout=1.0
    )
    handle = module.RunHandle(run_id=_RUN_IDS[0], run_dir=tmp_path / _RUN_IDS[0], process_pid=41)
    _write_worker_manifest(handle.run_dir / "processes.json", run_id=_RUN_IDS[1], worker_pid=101)

    with pytest.raises(module.ValidationError, match="run ID"):
        controller.stop_worker(handle)

    assert runner.signals == []


def test_controller_stops_only_the_verified_worker_once(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    proc_root = tmp_path / "proc"
    runner = _FakeProcessRunner(tmp_path, proc_root, (_RUN_IDS[0],))
    controller = module.LauncherController(
        _fake_launcher_args(tmp_path), runner=runner, proc_root=proc_root, startup_timeout=1.0
    )
    handle = controller.start()
    controller.wait_ready(handle)

    controller.stop_worker(handle)

    assert runner.signals == [(5000, signal.SIGTERM)]
    with pytest.raises(module.ValidationError, match="already stopped"):
        controller.stop_worker(handle)
    assert runner.signals == [(5000, signal.SIGTERM)]


def test_controller_restart_reuses_arguments_after_first_launcher_exits(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    proc_root = tmp_path / "proc"
    runner = _FakeProcessRunner(tmp_path, proc_root)
    controller = module.LauncherController(
        _fake_launcher_args(tmp_path), runner=runner, proc_root=proc_root, startup_timeout=1.0
    )
    first = controller.start()
    controller.wait_ready(first)
    controller.stop_worker(first)

    assert controller.wait_exit(first, timeout=1.0) == 143
    second = controller.restart()

    assert second.run_id != first.run_id
    assert runner.invocations[1]["arguments"] == runner.invocations[0]["arguments"]
    assert runner.invocations[1]["cwd"] == runner.invocations[0]["cwd"]


class _FakeHttpResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> object:
        return self._payload


class _QueuedHttpClient:
    def __init__(
        self,
        *,
        posts: list[_FakeHttpResponse] | None = None,
        gets: list[_FakeHttpResponse] | None = None,
    ) -> None:
        self.posts = list(posts or [])
        self.gets = list(gets or [])
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> _FakeHttpResponse:
        self.requests.append(("POST", url, kwargs))
        return self.posts.pop(0)

    def get(self, url: str, **kwargs: object) -> _FakeHttpResponse:
        self.requests.append(("GET", url, kwargs))
        if len(self.gets) > 1:
            return self.gets.pop(0)
        return self.gets[0]


def _acceptance_case(path: Path, query: str = "forklift"):
    module = _production_acceptance_module()
    return module.AcceptanceCase(path=path, query=query, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_production_api_client_rejects_complete_identity_mismatch(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    video = tmp_path / "one.mp4"
    video.write_bytes(b"video")
    asset_id = "123e4567-e89b-42d3-a456-426614174011"
    job_id = "123e4567-e89b-42d3-a456-426614174012"
    http = _QueuedHttpClient(
        posts=[
            _FakeHttpResponse(
                200,
                {
                    "url": "/api/v1/vst/v1/storage/file?upload_session_id=123e4567-e89b-42d3-a456-426614174010",
                    "asset_id": asset_id,
                    "upload_session_id": "123e4567-e89b-42d3-a456-426614174010",
                },
            ),
            _FakeHttpResponse(
                200,
                {"sensorId": asset_id, "streamId": asset_id, "bytes": 5, "chunkCount": 1},
            ),
            _FakeHttpResponse(
                202,
                {
                    "asset_id": "123e4567-e89b-42d3-a456-426614174099",
                    "job_id": job_id,
                    "status": "queued",
                    "status_url": f"/api/v1/jobs/{job_id}",
                },
            ),
        ]
    )
    client = module.ProductionApiClient("http://127.0.0.1:8000", client=http)

    with pytest.raises(module.ValidationError, match="asset identity"):
        client.create_and_complete(_acceptance_case(video))


def test_create_jobs_concurrently_uses_three_workers_and_preserves_case_order(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    barrier = threading.Barrier(3)
    thread_ids: set[int] = set()
    lock = threading.Lock()
    cases = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index]))
        cases.append(_acceptance_case(path, query=f"query-{index}"))

    class ConcurrentClient:
        def create_and_complete(self, case):
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait(timeout=2)
            index = int(case.path.stem.rsplit("-", 1)[1])
            return module.JobIdentity(
                asset_id=f"asset-{index}",
                job_id=f"job-{index}",
                status_url=f"/api/v1/jobs/job-{index}",
            )

    jobs = module.create_jobs_concurrently(ConcurrentClient(), tuple(cases))

    assert [job.job_id for job in jobs] == ["job-0", "job-1", "job-2"]
    assert len(thread_ids) == 3


def test_wait_job_times_out_without_accepting_non_terminal_progress() -> None:
    module = _production_acceptance_module()
    job = module.JobIdentity("asset-1", "job-1", "/api/v1/jobs/job-1")
    http = _QueuedHttpClient(
        gets=[
            _FakeHttpResponse(
                200,
                {
                    "asset_id": "asset-1",
                    "job_id": "job-1",
                    "status": "running",
                    "stage": "analyzing",
                    "attempt": 1,
                },
            )
        ]
    )
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    client = module.ProductionApiClient(
        "http://127.0.0.1:8000",
        client=http,
        monotonic=monotonic,
        sleep=sleep,
        poll_interval=0.1,
    )

    with pytest.raises(module.ValidationError, match="timed out"):
        client.wait_job(job, timeout=0.25)


def _checkpoint_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                attempt INTEGER NOT NULL
            );
            CREATE TABLE job_steps (
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                output_manifest TEXT,
                output_checksum TEXT,
                model TEXT,
                elapsed_ms INTEGER
            );
            CREATE TABLE segments (
                segment_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL
            );
            """
        )


def test_read_checkpoint_snapshot_is_ordered_and_uses_current_attempt(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    database = tmp_path / "recorded-video.sqlite3"
    _checkpoint_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO jobs(job_id, asset_id, status, stage, attempt) VALUES (?, ?, ?, ?, ?)",
            ("job-1", "asset-1", "running", "analyzing", 2),
        )
        connection.executemany(
            "INSERT INTO job_steps VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("job-1", "segmenting", "completed", "manifest.json", "sha-segment", None, 20),
                ("job-1", "probing", "completed", "manifest.json", "sha-probe", "ffprobe", 10),
            ],
        )

    checkpoints = module.read_checkpoint_snapshot(database, "job-1")

    assert [item.stage for item in checkpoints] == ["probing", "segmenting"]
    assert {item.attempt for item in checkpoints} == {2}
    assert checkpoints[0].output_checksum == "sha-probe"


def test_read_checkpoint_snapshot_rejects_missing_steps(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    database = tmp_path / "recorded-video.sqlite3"
    _checkpoint_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO jobs(job_id, asset_id, status, stage, attempt) VALUES (?, ?, ?, ?, ?)",
            ("job-1", "asset-1", "queued", None, 0),
        )

    with pytest.raises(module.ValidationError, match="checkpoint"):
        module.read_checkpoint_snapshot(database, "job-1")


def _job_snapshot(
    module,
    *,
    job_id: str,
    asset_id: str,
    attempt: int,
    checksum: str,
    segment_ids: tuple[str, ...],
    status: str = "completed",
):
    checkpoint = module.CheckpointEvidence(
        job_id=job_id,
        stage="analyzing",
        status="completed",
        output_manifest="derived/v1/attempts/1/manifest.json",
        output_checksum=checksum,
        attempt=attempt,
        elapsed_ms=10,
    )
    return module.JobSnapshot(
        asset_id=asset_id,
        job_id=job_id,
        status=status,
        stage="publish" if status == "completed" else "analyzing",
        attempt=attempt,
        checkpoints=(checkpoint,),
        segment_ids=segment_ids,
    )


def _recovery_state(module, *, checksum: str = "sha-a", attempt: int = 1):
    snapshots = {
        f"job-{index}": _job_snapshot(
            module,
            job_id=f"job-{index}",
            asset_id=f"asset-{index}",
            attempt=attempt,
            checksum=checksum,
            segment_ids=(f"segment-{index}",),
            status="running" if attempt == 1 else "completed",
        )
        for index in range(3)
    }
    return module.AcceptanceState(jobs=snapshots)


def test_assert_recovery_rejects_changed_completed_checkpoint() -> None:
    module = _production_acceptance_module()
    before = _recovery_state(module, checksum="sha-before", attempt=1)
    after = _recovery_state(module, checksum="sha-after", attempt=2)

    with pytest.raises(module.ValidationError, match="checksum"):
        module.assert_recovery(before, after.jobs)


def test_assert_recovery_rejects_duplicate_segments() -> None:
    module = _production_acceptance_module()
    before = _recovery_state(module, attempt=1)
    after = _recovery_state(module, attempt=2)
    duplicate = _job_snapshot(
        module,
        job_id="job-2",
        asset_id="asset-2",
        attempt=2,
        checksum="sha-a",
        segment_ids=("segment-2", "segment-1"),
    )
    after_jobs = dict(after.jobs)
    after_jobs["job-2"] = duplicate

    with pytest.raises(module.ValidationError, match="duplicate segment"):
        module.assert_recovery(before, after_jobs)


def test_assert_recovery_accepts_three_completed_jobs_with_stable_checkpoints() -> None:
    module = _production_acceptance_module()
    before = _recovery_state(module, attempt=1)
    after = _recovery_state(module, attempt=2)

    module.assert_recovery(before, after.jobs)
