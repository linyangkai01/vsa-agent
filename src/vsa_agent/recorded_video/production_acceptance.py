"""Production recorded-video acceptance orchestration primitives."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
