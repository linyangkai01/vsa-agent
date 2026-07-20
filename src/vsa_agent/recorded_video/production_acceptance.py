"""Production recorded-video acceptance orchestration primitives."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)
_READY_MARKER = "PASS: ES recorded-video runtime stack is ready"
_MANAGED_COMPONENTS = ("es", "api", "worker", "ui")


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    path: Path
    query: str
    sha256: str


@dataclass(frozen=True, slots=True)
class JobIdentity:
    asset_id: str
    job_id: str
    status_url: str


@dataclass(frozen=True, slots=True)
class RunHandle:
    run_id: str
    run_dir: Path
    process_pid: int
    launcher_log: Path | None = None


@dataclass(frozen=True, slots=True)
class CheckpointEvidence:
    job_id: str
    stage: str
    status: str
    output_manifest: str | None
    output_checksum: str | None
    attempt: int
    elapsed_ms: int | None


@dataclass(frozen=True, slots=True)
class AcceptanceState:
    cases: tuple[AcceptanceCase, ...] = ()
    jobs: tuple[JobIdentity, ...] = ()
    checkpoints: tuple[CheckpointEvidence, ...] = ()
    segment_ids: tuple[str, ...] = ()


class ValidationError(RuntimeError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class LauncherArgs:
    repo_root: Path
    api_port: int
    es_port: int
    ui_port: int
    index: str
    data_root: Path
    conda_env: str | None
    env: Mapping[str, str]

    def __post_init__(self) -> None:
        ports = (self.api_port, self.es_port, self.ui_port)
        if any(not _positive_integer(port) or port > 65535 for port in ports) or len(set(ports)) != 3:
            raise ValueError("launcher ports must be three distinct values between 1 and 65535")
        index = self.index.strip() if isinstance(self.index, str) else ""
        if not index or any(character.isspace() for character in index):
            raise ValueError("launcher index must be a non-empty value without whitespace")
        conda_env = self.conda_env.strip() if isinstance(self.conda_env, str) else self.conda_env
        if conda_env == "":
            raise ValueError("launcher conda environment must be non-empty when provided")
        if not isinstance(self.env, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in self.env.items()
        ):
            raise ValueError("launcher environment must contain string keys and values")
        object.__setattr__(self, "repo_root", Path(self.repo_root).resolve(strict=False))
        object.__setattr__(self, "data_root", Path(self.data_root).resolve(strict=False))
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "conda_env", conda_env)
        object.__setattr__(self, "env", dict(self.env))


class LauncherProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class ProcessRunner(Protocol):
    def start(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> LauncherProcess: ...

    def send_signal(self, pid: int, requested_signal: signal.Signals) -> None: ...

    def current_uid(self) -> int: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class _SubprocessRunner:
    def start(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab", buffering=0) as output:
            return subprocess.Popen(
                arguments,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    def send_signal(self, pid: int, requested_signal: signal.Signals) -> None:
        os.kill(pid, requested_signal)

    def current_uid(self) -> int:
        if not hasattr(os, "getuid"):
            raise ValidationError("launcher", "production launcher control requires Ubuntu process identity")
        return os.getuid()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Durably replace one JSON file without exposing partial contents."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_cases(video_paths: Sequence[Path], queries: Sequence[str]) -> tuple[AcceptanceCase, ...]:
    if len(video_paths) != 3:
        raise ValueError("production acceptance requires three distinct video files")

    try:
        resolved = tuple(Path(path).resolve(strict=True) for path in video_paths)
        if not all(path.is_file() for path in resolved):
            raise OSError("not a regular file")
        digests = tuple(_sha256(path) for path in resolved)
    except OSError:
        raise ValueError("production acceptance requires regular readable video files") from None
    if len(set(resolved)) != 3 or len(set(digests)) != 3:
        raise ValueError("production acceptance requires three distinct video files")

    if len(queries) not in (1, 3) or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("production acceptance requires one or three non-empty queries")
    normalized_queries = tuple(query.strip() for query in queries)
    mapped_queries = normalized_queries * 3 if len(normalized_queries) == 1 else normalized_queries

    return tuple(
        AcceptanceCase(path=path, query=query, sha256=digest)
        for path, query, digest in zip(resolved, mapped_queries, digests, strict=True)
    )


def _identity_error(message: str) -> ValidationError:
    return ValidationError("worker_identity", message)


def _load_process_manifest(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        if resolved.name != "processes.json" or not resolved.is_file():
            raise OSError("manifest is not a regular processes.json file")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise _identity_error(f"worker process manifest JSON is invalid: {error.msg}") from None
    except OSError as error:
        raise _identity_error(f"worker process manifest is unreadable: {error}") from None
    if not isinstance(payload, dict):
        raise _identity_error("worker process manifest root must be a JSON object")
    return payload


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _read_process_uid(proc_root: Path, worker_pid: int) -> int:
    status_path = proc_root / str(worker_pid) / "status"
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise _identity_error(f"worker process status is unreadable: {error}") from None
    for line in lines:
        if line.startswith("Uid:"):
            fields = line.split()
            if len(fields) >= 2:
                try:
                    return int(fields[1])
                except ValueError:
                    break
    raise _identity_error("worker process status has no valid UID")


def _read_process_arguments(proc_root: Path, worker_pid: int) -> tuple[str, ...]:
    command_path = proc_root / str(worker_pid) / "cmdline"
    try:
        raw = command_path.read_bytes()
    except OSError as error:
        raise _identity_error(f"worker process command line is unreadable: {error}") from None
    arguments = tuple(os.fsdecode(item) for item in raw.split(b"\0") if item)
    if not arguments:
        raise _identity_error("worker process command line is empty")
    return arguments


def _single_argument(arguments: tuple[str, ...], flag: str) -> str:
    positions = [index for index, value in enumerate(arguments) if value == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(arguments):
        raise _identity_error(f"worker supervisor command requires exactly one {flag}")
    return arguments[positions[0] + 1]


def _require_bound_path(arguments: tuple[str, ...], flag: str, expected: Path, label: str) -> None:
    observed = Path(_single_argument(arguments, flag)).resolve(strict=False)
    if observed != expected.resolve(strict=False):
        raise _identity_error(f"worker supervisor {label} is not bound to the active run")


def _validate_supervisor_command(arguments: tuple[str, ...], run_dir: Path) -> None:
    try:
        boundary = arguments.index("--")
    except ValueError:
        raise _identity_error("worker supervisor command has no workload boundary") from None
    supervisor = arguments[:boundary]
    workload = arguments[boundary + 1 :]
    if not any(Path(value).name == "runtime-log-supervisor.py" for value in supervisor):
        raise _identity_error("worker process is not the runtime log supervisor")
    if _single_argument(supervisor, "--component") != "worker":
        raise _identity_error("worker supervisor component identity is invalid")
    if not any(Path(value).name == "recorded-video-worker.py" for value in workload):
        raise _identity_error("worker supervisor workload command is invalid")
    _require_bound_path(workload, "--config", run_dir / "config.yaml", "runtime config path")
    _require_bound_path(supervisor, "--stack-log", run_dir / "stack.log", "stack log path")
    _require_bound_path(supervisor, "--component-log", run_dir / "worker.log", "component log path")
    _require_bound_path(supervisor, "--status-file", run_dir / "worker.status.json", "status path")


def validate_worker_identity(
    manifest_path: Path,
    run_id: str,
    worker_pid: int,
    current_uid: int,
    *,
    proc_root: Path = Path("/proc"),
) -> None:
    """Fail closed unless a PID is the active worker supervisor for one launcher run."""

    if not isinstance(run_id, str) or not run_id:
        raise _identity_error("active run ID is invalid")
    if not _positive_integer(worker_pid):
        raise _identity_error("worker PID must be a positive integer")
    if not isinstance(current_uid, int) or isinstance(current_uid, bool) or current_uid < 0:
        raise _identity_error("current UID is invalid")

    resolved_manifest = Path(manifest_path).resolve(strict=False)
    run_dir = resolved_manifest.parent
    if run_dir.name != run_id:
        raise _identity_error("worker manifest path does not match the active run ID")
    payload = _load_process_manifest(resolved_manifest)
    if payload.get("run_id") != run_id:
        raise _identity_error("worker process manifest run ID does not match the active run ID")
    processes = payload.get("processes")
    if not isinstance(processes, list):
        raise _identity_error("worker process manifest processes must be a JSON array")
    workers = [
        entry
        for entry in processes
        if isinstance(entry, dict) and entry.get("component") == "worker" and entry.get("exit_status") is None
    ]
    if len(workers) != 1:
        raise _identity_error("worker process manifest must contain exactly one active worker")
    worker = workers[0]
    if not _positive_integer(worker.get("pid")) or worker["pid"] != worker_pid:
        raise _identity_error("worker PID does not match the active manifest entry")
    safe_command = worker.get("command")
    if not isinstance(safe_command, str) or "recorded-video-worker.py" not in safe_command:
        raise _identity_error("worker command in the process manifest is invalid")

    observed_uid = _read_process_uid(Path(proc_root), worker_pid)
    if observed_uid != current_uid:
        raise _identity_error("worker process is not owned by the current UID")
    arguments = _read_process_arguments(Path(proc_root), worker_pid)
    _validate_supervisor_command(arguments, run_dir)


def _launcher_error(message: str) -> ValidationError:
    return ValidationError("launcher", message)


def _canonical_run_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise _launcher_error("launcher latest pointer does not contain a canonical UUID run ID") from None
    canonical = str(parsed)
    if value.lower() != canonical:
        raise _launcher_error("launcher latest pointer does not contain a canonical UUID run ID")
    return canonical


def _resolve_latest_run(repo_root: Path) -> Path | None:
    runtime_root = repo_root / ".runtime" / "es-stack"
    latest = runtime_root / "latest"
    if not latest.is_symlink() and not latest.exists():
        return None
    try:
        if latest.is_symlink() or latest.is_dir():
            candidate = latest.resolve(strict=True)
        elif latest.is_file():
            raw = latest.read_text(encoding="utf-8").strip()
            if not raw:
                raise OSError("latest pointer file is empty")
            pointer = Path(raw)
            candidate = (pointer if pointer.is_absolute() else latest.parent / pointer).resolve(strict=True)
        else:
            raise OSError("latest pointer has an unsupported file type")
    except OSError as error:
        raise _launcher_error(f"launcher latest pointer is unreadable: {error}") from None
    runs_root = (runtime_root / "runs").resolve(strict=False)
    if not candidate.is_dir() or candidate.parent != runs_root:
        raise _launcher_error("launcher latest pointer escaped the run directory")
    _canonical_run_id(candidate.name)
    return candidate


def _read_positive_pid(path: Path, label: str) -> int:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        raise _launcher_error(f"{label} is missing or invalid") from None
    if not _positive_integer(value):
        raise _launcher_error(f"{label} is missing or invalid")
    return value


def _active_component_pids(manifest_path: Path, run_id: str) -> dict[str, int]:
    payload = _load_process_manifest(manifest_path)
    if payload.get("run_id") != run_id:
        raise _identity_error("worker process manifest run ID does not match the active run ID")
    processes = payload.get("processes")
    if not isinstance(processes, list):
        raise _identity_error("worker process manifest processes must be a JSON array")
    active: dict[str, int] = {}
    for component in _MANAGED_COMPONENTS:
        matches = [
            entry
            for entry in processes
            if isinstance(entry, dict) and entry.get("component") == component and entry.get("exit_status") is None
        ]
        if len(matches) != 1 or not _positive_integer(matches[0].get("pid")):
            raise _identity_error(f"process manifest must contain exactly one active {component} process")
        active[component] = matches[0]["pid"]
    return active


class LauncherController:
    def __init__(
        self,
        arguments: LauncherArgs,
        *,
        runner: ProcessRunner | None = None,
        proc_root: Path = Path("/proc"),
        startup_timeout: float = 120.0,
        poll_interval: float = 0.1,
    ) -> None:
        if startup_timeout <= 0 or poll_interval <= 0:
            raise ValueError("launcher timeouts must be positive")
        self.arguments = arguments
        self._runner = runner or _SubprocessRunner()
        self._proc_root = Path(proc_root)
        self._startup_timeout = startup_timeout
        self._poll_interval = poll_interval
        self.acceptance_id = str(uuid.uuid4())
        self.acceptance_dir = self.arguments.repo_root / ".runtime" / "production-acceptance" / self.acceptance_id
        self._processes: dict[str, LauncherProcess] = {}
        self._handles: list[RunHandle] = []
        self._stopped_workers: set[str] = set()

    def _command(self) -> list[str]:
        command = [
            "bash",
            "scripts/es-runtime-stack.sh",
            "--api-port",
            str(self.arguments.api_port),
            "--es-port",
            str(self.arguments.es_port),
            "--ui-port",
            str(self.arguments.ui_port),
            "--index",
            self.arguments.index,
            "--data-root",
            str(self.arguments.data_root),
        ]
        if self.arguments.conda_env is not None:
            command.extend(("--conda-env", self.arguments.conda_env))
        return command

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(self.arguments.env)
        return environment

    def _abort_known_launcher(self, process: LauncherProcess) -> None:
        if process.poll() is not None:
            return
        try:
            self._runner.send_signal(process.pid, signal.SIGTERM)
        except OSError:
            LOGGER.exception("production_acceptance.launcher.abort_failed pid=%s", process.pid)

    def start(self) -> RunHandle:
        try:
            previous_run = _resolve_latest_run(self.arguments.repo_root)
        except ValidationError:
            previous_run = None
        self.acceptance_dir.mkdir(parents=True, exist_ok=True)
        launch_number = len(self._handles) + 1
        launcher_log = self.acceptance_dir / f"launcher-{launch_number}.log"
        command = self._command()
        LOGGER.info(
            "production_acceptance.launcher.start acceptance_id=%s launch=%d log=%s",
            self.acceptance_id,
            launch_number,
            launcher_log,
        )
        try:
            process = self._runner.start(
                command,
                cwd=self.arguments.repo_root,
                env=self._environment(),
                log_path=launcher_log,
            )
        except OSError as error:
            raise _launcher_error(f"failed to start runtime launcher: {error}") from None

        deadline = self._runner.monotonic() + self._startup_timeout
        pointer_error: ValidationError | None = None
        try:
            while self._runner.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    raise _launcher_error(
                        f"runtime launcher exited before publishing its run directory with status {return_code}; "
                        f"log={launcher_log}"
                    )
                try:
                    candidate = _resolve_latest_run(self.arguments.repo_root)
                    pointer_error = None
                except ValidationError as error:
                    pointer_error = error
                    self._runner.sleep(self._poll_interval)
                    continue
                if candidate is not None and candidate != previous_run and candidate.name not in self._processes:
                    run_id = _canonical_run_id(candidate.name)
                    launcher_pid = _read_positive_pid(candidate / "launcher.pid", "launcher PID file")
                    if launcher_pid != process.pid:
                        raise _launcher_error("launcher PID file does not match the process started by acceptance")
                    handle = RunHandle(
                        run_id=run_id,
                        run_dir=candidate,
                        process_pid=process.pid,
                        launcher_log=launcher_log,
                    )
                    self._processes[run_id] = process
                    self._handles.append(handle)
                    LOGGER.info(
                        "production_acceptance.launcher.bound acceptance_id=%s run_id=%s pid=%d",
                        self.acceptance_id,
                        run_id,
                        process.pid,
                    )
                    return handle
                self._runner.sleep(self._poll_interval)
        except Exception:
            self._abort_known_launcher(process)
            raise
        self._abort_known_launcher(process)
        if pointer_error is not None:
            raise _launcher_error(
                f"runtime launcher did not publish a valid run within {self._startup_timeout:g}s: "
                f"{pointer_error.message}"
            )
        raise _launcher_error(f"runtime launcher did not publish a new run within {self._startup_timeout:g}s")

    def _process(self, handle: RunHandle) -> LauncherProcess:
        process = self._processes.get(handle.run_id)
        if process is None or process.pid != handle.process_pid:
            raise _launcher_error("run handle is not owned by this acceptance controller")
        return process

    def wait_ready(self, handle: RunHandle) -> RunHandle:
        process = self._process(handle)
        deadline = self._runner.monotonic() + self._startup_timeout
        stack_log = handle.run_dir / "stack.log"
        while self._runner.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise _launcher_error(
                    f"runtime launcher exited before readiness with status {return_code}; log={handle.launcher_log}"
                )
            try:
                ready = _READY_MARKER in stack_log.read_text(encoding="utf-8")
            except OSError:
                ready = False
            if ready:
                manifest = handle.run_dir / "processes.json"
                active = _active_component_pids(manifest, handle.run_id)
                validate_worker_identity(
                    manifest,
                    handle.run_id,
                    active["worker"],
                    self._runner.current_uid(),
                    proc_root=self._proc_root,
                )
                LOGGER.info(
                    "production_acceptance.launcher.ready acceptance_id=%s run_id=%s worker_pid=%d",
                    self.acceptance_id,
                    handle.run_id,
                    active["worker"],
                )
                return handle
            self._runner.sleep(self._poll_interval)
        raise _launcher_error(f"runtime launcher did not become ready within {self._startup_timeout:g}s")

    def stop_worker(self, handle: RunHandle) -> None:
        if handle.run_id in self._stopped_workers:
            raise _launcher_error("worker was already stopped for this launcher run")
        manifest = handle.run_dir / "processes.json"
        active = _active_component_pids(manifest, handle.run_id)
        worker_pid = active["worker"]
        validate_worker_identity(
            manifest,
            handle.run_id,
            worker_pid,
            self._runner.current_uid(),
            proc_root=self._proc_root,
        )
        LOGGER.info(
            "production_acceptance.worker.term acceptance_id=%s run_id=%s worker_pid=%d",
            self.acceptance_id,
            handle.run_id,
            worker_pid,
        )
        try:
            self._runner.send_signal(worker_pid, signal.SIGTERM)
        except OSError as error:
            raise _launcher_error(f"failed to stop verified worker PID {worker_pid}: {error}") from None
        self._stopped_workers.add(handle.run_id)

    def wait_exit(self, handle: RunHandle, timeout: float) -> int:
        if timeout <= 0:
            raise ValueError("launcher exit timeout must be positive")
        process = self._process(handle)
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise _launcher_error(f"runtime launcher did not exit within {timeout:g}s") from None
        LOGGER.info(
            "production_acceptance.launcher.exit acceptance_id=%s run_id=%s status=%d",
            self.acceptance_id,
            handle.run_id,
            status,
        )
        return status

    def restart(self) -> RunHandle:
        if not self._handles:
            raise _launcher_error("cannot restart before the first launcher run")
        previous = self._process(self._handles[-1])
        if previous.poll() is None:
            raise _launcher_error("cannot restart while the previous launcher is still running")
        return self.start()
