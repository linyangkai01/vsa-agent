#!/usr/bin/env python3
"""Run one workload with redacted, prefixed, lifecycle-owned logging."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

_QUOTED_AUTHORIZATION = re.compile(r"(?i)([\"']authorization[\"']\s*:\s*[\"'])(?:bearer\s+)?[^\"']*([\"'])")
_AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+")
_QUOTED_SECRET = re.compile(
    r"(?i)([\"'](?:api[-_]?key|access[-_]?token|token|password)[\"']\s*:\s*[\"'])[^\"']*([\"'])"
)
_SECRET = re.compile(r"(?i)((?:api[-_]?key|access[-_]?token|token|password)\s*[:=]\s*)[^\s,;]+")
_DATA_IMAGE = re.compile(r"(?i)data:image/[^;\s\"']+;base64,[A-Za-z0-9+/=_-]*")
_QUOTED_IMAGE = re.compile(
    r"(?i)([\"'](?:image|image_url|input_image|b64_json)[\"']\s*:\s*[\"'])[A-Za-z0-9+/=_-]{64,}([\"'])"
)
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{64,}(?![A-Za-z0-9+/=_-])")
_STOP_GRACE_SEC = 2.0
_STATUS_REPLACE_RETRY_SEC = 0.5
_STATUS_REPLACE_RETRY_INTERVAL_SEC = 0.005
_STATUS_FAILURE_EXIT_CODE = 74
_WINDOWS_BOOTSTRAP = """
import pathlib
import os
import subprocess
import sys
import tempfile
import time

gate = pathlib.Path(sys.argv[1])
pid_path = pathlib.Path(sys.argv[2])
while not gate.exists():
    time.sleep(0.001)
try:
    gate.unlink()
except FileNotFoundError:
    pass
process = subprocess.Popen(sys.argv[3:])
descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{pid_path.name}.", suffix=".tmp", dir=pid_path.parent
)
temporary = pathlib.Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as pid_file:
        pid_file.write(str(process.pid))
        pid_file.flush()
    deadline = time.monotonic() + 0.5
    while True:
        try:
            os.replace(temporary, pid_path)
            break
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(0.005)
finally:
    temporary.unlink(missing_ok=True)
raise SystemExit(process.wait())
"""


class _WindowsJob:
    """Own one Windows process tree without requiring elevated privileges."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(handle)
            raise error
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._handle = handle

    def assign(self, process: subprocess.Popen[str]) -> None:
        from ctypes import wintypes

        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def protect_runtime_text(text: str) -> str:
    text = _QUOTED_AUTHORIZATION.sub(r"\1[REDACTED]\2", text)
    text = _AUTHORIZATION.sub(r"\1[REDACTED]", text)
    text = _QUOTED_SECRET.sub(r"\1[REDACTED]\2", text)
    text = _SECRET.sub(r"\1[REDACTED]", text)
    text = _DATA_IMAGE.sub("[REDACTED_IMAGE]", text)
    text = _QUOTED_IMAGE.sub(r"\1[REDACTED_IMAGE]\2", text)
    return _BASE64.sub("[REDACTED_BASE64]", text)


class _AppendWriter:
    def __init__(self, path: Path, *, shared: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._stream: BinaryIO = path.open("ab", buffering=0)
        self._lock_stream: BinaryIO | None = None
        self._shared = shared
        self._write_error: OSError | None = None
        if shared and os.name == "nt":
            lock_path = path.with_name(f"{path.name}.lock")
            self._lock_stream = lock_path.open("a+b", buffering=0)
            if self._lock_stream.seek(0, os.SEEK_END) == 0:
                self._lock_stream.write(b"\0")

    def write(
        self,
        text: str,
        *,
        cancelled: threading.Event | None = None,
        guard: Callable[[], None] | None = None,
    ) -> bool:
        data = text.encode("utf-8", errors="replace")
        with self.locked():
            if cancelled is not None and cancelled.is_set():
                return False
            if guard is not None:
                guard()
            self.write_locked(data)
        return True

    def write_locked(self, text: str | bytes) -> None:
        if self._write_error is not None:
            raise OSError(f"append writer is unavailable after write failure: {self._write_error}")
        data = text.encode("utf-8", errors="replace") if isinstance(text, str) else text
        try:
            view = memoryview(data)
            while view:
                written = os.write(self._stream.fileno(), view)
                view = view[written:]
        except OSError as error:
            self._write_error = error
            raise

    def find_event_locked(self, event: str, run_ids: set[str]) -> dict[str, object] | None:
        with self._path.open("rb") as stream:
            for raw_line in stream:
                try:
                    payload = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict) and payload.get("event") == event and payload.get("run_id") in run_ids:
                    return payload
        return None

    @contextmanager
    def locked(self) -> Iterator[None]:
        self._lock()
        try:
            yield
        finally:
            self._unlock()

    def close(self) -> None:
        self._stream.close()
        if self._lock_stream is not None:
            self._lock_stream.close()

    def _lock(self) -> None:
        if not self._shared:
            return
        if os.name == "nt":
            import msvcrt

            assert self._lock_stream is not None
            self._lock_stream.seek(0)
            msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX)

    def _unlock(self) -> None:
        if not self._shared:
            return
        if os.name == "nt":
            import msvcrt

            assert self._lock_stream is not None
            self._lock_stream.seek(0)
            msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)


class _StatusWriter:
    _TRANSITIONS = {
        None: {"starting"},
        "starting": {"running"},
        "running": {"stopping", "exited"},
        "stopping": {"exited"},
        "exited": set(),
    }

    def __init__(self, path: Path, *, component: str) -> None:
        self._path = path
        self._component = component
        self._supervisor_pid = int(os.environ.get("VSA_SUPERVISOR_REGISTERED_PID", os.getpid()))
        self._state: str | None = None

    @property
    def failure_marker(self) -> Path:
        return self._path.with_suffix(".status_failure.json")

    def write_failure_marker(self, state: str, error: str) -> None:
        payload = {
            "component": self._component,
            "status_file": self._path.as_posix(),
            "state": state,
            "error": error,
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        marker = self.failure_marker
        temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            deadline = time.monotonic() + _STATUS_REPLACE_RETRY_SEC
            while True:
                try:
                    os.replace(temporary, marker)
                    break
                except PermissionError:
                    if os.name != "nt" or time.monotonic() >= deadline:
                        raise
                    time.sleep(_STATUS_REPLACE_RETRY_INTERVAL_SEC)
        finally:
            temporary.unlink(missing_ok=True)

    def clear_failure_marker(self) -> None:
        _unlink_with_windows_retry(self.failure_marker)

    def write(self, state: str, *, workload_pid: int | None, exit_code: int | None) -> None:
        if state not in self._TRANSITIONS[self._state]:
            raise ValueError(f"invalid status transition: {self._state!r} -> {state!r}")
        payload = {
            "schema_version": 1,
            "run_id": self._path.parent.name,
            "component": self._component,
            "state": state,
            "supervisor_pid": self._supervisor_pid,
            "workload_pid": workload_pid,
            "exit_code": exit_code,
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            deadline = time.monotonic() + _STATUS_REPLACE_RETRY_SEC
            while True:
                try:
                    os.replace(temporary, self._path)
                    break
                except PermissionError:
                    if os.name != "nt" or time.monotonic() >= deadline:
                        raise
                    time.sleep(_STATUS_REPLACE_RETRY_INTERVAL_SEC)
        finally:
            temporary.unlink(missing_ok=True)
        self._state = state


class _StatusGuardError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _require_running_statuses(requirements: list[tuple[str, int, Path]], *, stack_writer: _AppendWriter) -> None:
    run_ids = {path.parent.name for _component, _expected_supervisor_pid, path in requirements}
    try:
        failure_event = stack_writer.find_event_locked("status_sidecar_write_failed", run_ids)
    except OSError as error:
        raise _StatusGuardError(f"unable to inspect stack status failures: {error}") from error
    if failure_event is not None:
        component = failure_event.get("component", "unknown")
        state = failure_event.get("state", "unknown")
        error = failure_event.get("error", "status sidecar write failed")
        raise _StatusGuardError(f"component={component} state={state} exit_code=null error={error}")
    for component, expected_supervisor_pid, path in requirements:
        marker = path.with_suffix(".status_failure.json")
        if marker.exists():
            try:
                marker_payload = json.loads(marker.read_text(encoding="utf-8"))
                marker_error = marker_payload.get("error", "status transition failure")
            except (OSError, json.JSONDecodeError, AttributeError):
                marker_error = "unreadable status failure marker"
            raise _StatusGuardError(
                f"component={component} status_file={path.as_posix()} state=status_failure "
                f"exit_code=null error={marker_error}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise _StatusGuardError(
                f"component={component} status_file={path.as_posix()} state=unknown "
                f"exit_code=null error=unreadable status sidecar: {error}"
            ) from error
        state = payload.get("state") if isinstance(payload, dict) else "unknown"
        exit_code = payload.get("exit_code") if isinstance(payload, dict) else None
        valid_running = bool(
            isinstance(payload, dict)
            and payload.get("schema_version") == 1
            and payload.get("run_id") == path.parent.name
            and payload.get("component") == component
            and payload.get("supervisor_pid") == expected_supervisor_pid
            and state == "running"
            and isinstance(payload.get("workload_pid"), int)
            and not isinstance(payload.get("workload_pid"), bool)
            and payload["workload_pid"] > 0
            and exit_code is None
            and isinstance(payload.get("updated_at"), str)
            and payload["updated_at"]
        )
        if valid_running:
            continue
        status = exit_code if state == "exited" and isinstance(exit_code, int) and 0 < exit_code <= 255 else 1
        raise _StatusGuardError(
            f"component={component} status_file={path.as_posix()} state={state} "
            f"exit_code={json.dumps(exit_code)} error=component is not running",
            exit_code=status,
        )


def _unlink_with_windows_retry(path: Path) -> None:
    deadline = time.monotonic() + _STATUS_REPLACE_RETRY_SEC
    while True:
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(_STATUS_REPLACE_RETRY_INTERVAL_SEC)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--stack-log", required=True, type=Path)
    parser.add_argument("--component-log", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--component")
    parser.add_argument(
        "--require-running-status",
        action="append",
        nargs=3,
        default=[],
        metavar=("COMPONENT", "SUPERVISOR_PID", "STATUS_FILE"),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a workload command is required after --")
    if (args.status_file is None) != (args.component is None):
        parser.error("--status-file and --component must be provided together")
    try:
        args.require_running_status = [
            (component, int(supervisor_pid), Path(status_file))
            for component, supervisor_pid, status_file in args.require_running_status
        ]
    except ValueError:
        parser.error("--require-running-status supervisor PID must be an integer")
    return args


def _windows_bash_command(command: list[str]) -> list[str]:
    if os.name != "nt":
        return command
    shell_name = Path(os.environ.get("SHELL", "")).name.lower()
    is_bash_runtime = bool(
        os.environ.get("MSYSTEM") or os.environ.get("BASH_ENV") or shell_name in {"bash", "bash.exe"}
    )
    if not is_bash_runtime:
        return command
    bash = shutil.which("bash")
    if bash is None and shell_name in {"bash", "bash.exe"}:
        bash = os.environ.get("SHELL")
    if bash is None:
        return command
    return [bash, "-c", 'exec "$@"', "runtime-log-supervisor", *command]


def _new_windows_start_gate() -> Path:
    descriptor, path = tempfile.mkstemp(prefix=".runtime-log-start-", suffix=".gate", dir=Path.cwd())
    os.close(descriptor)
    gate = Path(path)
    _unlink_with_windows_retry(gate)
    return gate


def _start_workload(command: list[str]) -> tuple[subprocess.Popen[str], _WindowsJob | None]:
    options: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name != "nt":
        options["start_new_session"] = True
        process = subprocess.Popen(command, **options)  # type: ignore[arg-type]
        process._vsa_workload_pid = process.pid  # type: ignore[attr-defined]
        return process, None

    options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    job = _WindowsJob()
    gate = _new_windows_start_gate()
    workload_pid_path = gate.with_suffix(".pid")
    bootstrap = [
        sys.executable,
        "-u",
        "-c",
        _WINDOWS_BOOTSTRAP,
        gate.as_posix(),
        workload_pid_path.as_posix(),
        *_windows_bash_command(command),
    ]
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(bootstrap, **options)  # type: ignore[arg-type]
        job.assign(process)
        gate.touch()
        deadline = time.monotonic() + _STOP_GRACE_SEC
        workload_pid: int | None = None
        while workload_pid is None:
            try:
                candidate = int(workload_pid_path.read_text(encoding="utf-8").strip())
            except (FileNotFoundError, ValueError):
                candidate = 0
            if candidate > 0:
                workload_pid = candidate
                break
            if process.poll() is not None:
                raise OSError(f"workload bootstrap exited before PID handoff: {process.returncode}")
            if time.monotonic() >= deadline:
                raise OSError("workload PID handoff timed out")
            time.sleep(0.005)
        process._vsa_workload_pid = workload_pid  # type: ignore[attr-defined]
        _unlink_with_windows_retry(workload_pid_path)
    except BaseException:
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
            process.wait()
        job.close()
        for path in (gate, workload_pid_path):
            try:
                _unlink_with_windows_retry(path)
            except OSError:
                pass
        raise
    assert process is not None
    return process, job


def _workload_pid(process: subprocess.Popen[str]) -> int:
    return int(getattr(process, "_vsa_workload_pid", process.pid))


def _signal_posix_group(pid: int, signal_number: int) -> None:
    try:
        os.killpg(pid, signal_number)
    except ProcessLookupError:
        pass


def _group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _request_stop(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError):
            pass
    else:
        _signal_posix_group(process.pid, signal.SIGTERM)


def _stop_workload_tree(process: subprocess.Popen[str], job: _WindowsJob | None) -> None:
    if os.name == "nt":
        if job is not None:
            job.close()
        elif process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=_STOP_GRACE_SEC)
        except subprocess.TimeoutExpired:
            process.kill()
        return

    _signal_posix_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + _STOP_GRACE_SEC
    while time.monotonic() < deadline and _group_exists(process.pid):
        time.sleep(0.05)
    if _group_exists(process.pid):
        _signal_posix_group(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=_STOP_GRACE_SEC)
    except subprocess.TimeoutExpired:
        process.kill()


def _normalized_exit_code(return_code: int) -> int:
    return 128 + abs(return_code) if return_code < 0 else return_code


def run(args: argparse.Namespace) -> int:
    stack_writer = _AppendWriter(args.stack_log, shared=True)
    component_writer = _AppendWriter(args.component_log, shared=False) if args.component_log else None
    status_writer = _StatusWriter(args.status_file, component=args.component) if args.status_file else None
    output: queue.Queue[str] = queue.Queue()
    reader_finished = threading.Event()
    interrupted = threading.Event()
    received_signal: list[int] = []
    process: subprocess.Popen[str] | None = None
    job: _WindowsJob | None = None
    publication_failure = 0
    publication_guard = (
        (lambda: _require_running_statuses(args.require_running_status, stack_writer=stack_writer))
        if args.require_running_status
        else None
    )

    def emit_supervisor_error(message: str) -> None:
        line = protect_runtime_text(f"{message}\n")
        prefixed = f"[{args.label}] {line}"
        if component_writer is not None:
            component_writer.write(line)
        stack_writer.write(prefixed)
        sys.stderr.write(prefixed)
        sys.stderr.flush()

    def write_status(state: str, *, workload_pid: int | None, exit_code: int | None) -> bool:
        if status_writer is None:
            return True

        def write_failure_event_locked(error: OSError | ValueError) -> None:
            payload = {
                "event": "status_sidecar_write_failed",
                "run_id": args.status_file.parent.name,
                "component": args.component,
                "state": state,
                "error": str(error),
            }
            stack_writer.write_locked(json.dumps(payload, separators=(",", ":")) + "\n")

        try:
            with stack_writer.locked():
                terminal = state in {"stopping", "exited"}
                if terminal:
                    try:
                        status_writer.write_failure_marker(state, f"pending {state} status transition")
                    except OSError as error:
                        try:
                            write_failure_event_locked(error)
                        except OSError:
                            pass
                        raise
                try:
                    status_writer.write(state, workload_pid=workload_pid, exit_code=exit_code)
                except (OSError, ValueError) as error:
                    if terminal:
                        try:
                            status_writer.write_failure_marker(state, str(error))
                        except OSError:
                            try:
                                write_failure_event_locked(error)
                            except OSError:
                                pass
                    raise
                if terminal:
                    status_writer.clear_failure_marker()
        except (OSError, ValueError) as error:
            emit_supervisor_error(f"status sidecar write failed: {args.status_file}: {error}")
            return False
        return True

    def handle_signal(signal_number: int, _frame: object) -> None:
        if not received_signal:
            received_signal.append(signal_number)
        interrupted.set()
        if process is not None:
            _request_stop(process)

    previous_handlers = {
        signal_number: signal.signal(signal_number, handle_signal) for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if not write_status("starting", workload_pid=None, exit_code=None):
            return _STATUS_FAILURE_EXIT_CODE
        try:
            process, job = _start_workload(args.command)
        except OSError as error:
            line = protect_runtime_text(f"unable to start workload: {error}\n")
            prefixed = f"[{args.label}] {line}"
            if component_writer is not None:
                component_writer.write(line)
            stack_writer.write(prefixed)
            sys.stdout.write(prefixed)
            sys.stdout.flush()
            return 127 if isinstance(error, FileNotFoundError) else 126

        workload_pid = _workload_pid(process)
        if not write_status("running", workload_pid=workload_pid, exit_code=None):
            _stop_workload_tree(process, job)
            return _STATUS_FAILURE_EXIT_CODE

        assert process.stdout is not None

        def read_output() -> None:
            try:
                for line in process.stdout:
                    output.put(line)
            finally:
                reader_finished.set()

        reader = threading.Thread(target=read_output, name="runtime-log-reader", daemon=True)
        reader.start()
        stopped = False
        stopping_written = False
        exited_written = False
        status_failed = False
        root_exit_seen_at: float | None = None
        return_code: int | None = None
        while not exited_written or not reader_finished.is_set() or not output.empty():
            if interrupted.is_set() and not stopping_written and not exited_written:
                stopping_written = True
                if not write_status("stopping", workload_pid=workload_pid, exit_code=None):
                    status_failed = True
                    _stop_workload_tree(process, job)
                    stopped = True

            observed_return_code = process.poll()
            if observed_return_code is not None and not exited_written:
                return_code = observed_return_code
                exited_written = True
                root_exit_seen_at = time.monotonic()
                if not write_status(
                    "exited",
                    workload_pid=workload_pid,
                    exit_code=_normalized_exit_code(observed_return_code),
                ):
                    status_failed = True
                    if not stopped:
                        _stop_workload_tree(process, job)
                        stopped = True

            try:
                line = output.get(timeout=0.05)
            except queue.Empty:
                line = None
            if line is not None:
                protected = protect_runtime_text(line)
                prefixed = f"[{args.label}] {protected}"
                try:
                    published = stack_writer.write(prefixed, cancelled=interrupted, guard=publication_guard)
                except _StatusGuardError as error:
                    publication_failure = error.exit_code
                    emit_supervisor_error(f"guarded publication rejected: {error}")
                    published = False
                if published:
                    if component_writer is not None:
                        component_writer.write(protected, cancelled=interrupted)
                    sys.stdout.write(prefixed)
                    sys.stdout.flush()

            if interrupted.is_set() and not stopped:
                _stop_workload_tree(process, job)
                stopped = True
            if (
                root_exit_seen_at is not None
                and not reader_finished.is_set()
                and time.monotonic() - root_exit_seen_at >= 0.25
                and not stopped
            ):
                _stop_workload_tree(process, job)
                stopped = True

        reader.join(timeout=1)
        if return_code is None:
            return_code = process.wait()
            if not write_status("exited", workload_pid=workload_pid, exit_code=_normalized_exit_code(return_code)):
                status_failed = True
        if status_failed:
            return _STATUS_FAILURE_EXIT_CODE
        if publication_failure:
            return publication_failure
        return 130 if received_signal else _normalized_exit_code(return_code)
    finally:
        for signal_number, previous in previous_handlers.items():
            signal.signal(signal_number, previous)
        if process is not None:
            workload_alive = process.poll() is None
            if os.name != "nt" and not workload_alive:
                workload_alive = _group_exists(process.pid)
            if workload_alive:
                _stop_workload_tree(process, job)
        if job is not None:
            job.close()
        if component_writer is not None:
            component_writer.close()
        stack_writer.close()


def main(argv: list[str] | None = None) -> int:
    return run(_parse_args(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
