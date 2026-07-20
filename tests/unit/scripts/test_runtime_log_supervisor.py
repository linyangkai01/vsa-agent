from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

SUPERVISOR = Path("scripts/runtime-log-supervisor.py")


def _load_supervisor_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("runtime_log_supervisor_under_test", SUPERVISOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _windows_process_is_running(pid: int) -> bool:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _run_supervisor(
    tmp_path: Path,
    workload: str,
    *,
    label: str = "worker",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    stack_log = tmp_path / "stack.log"
    component_log = tmp_path / f"{label}.log"
    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--label",
            label,
            "--stack-log",
            str(stack_log),
            "--component-log",
            str(component_log),
            "--",
            sys.executable,
            "-c",
            workload,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed, stack_log, component_log


def test_runtime_log_supervisor_merges_redacts_and_prefixes_output(tmp_path: Path) -> None:
    workload = """
import sys

print("ordinary stdout", flush=True)
print("Authorization: Bearer header-secret", file=sys.stderr, flush=True)
print('{"api_key":"json-secret","image":"data:image/png;base64,QUJDREVGR0g="}', flush=True)
raise SystemExit(23)
"""

    completed, stack_log, component_log = _run_supervisor(tmp_path, workload)

    assert completed.returncode == 23
    component = component_log.read_text(encoding="utf-8")
    stack = stack_log.read_text(encoding="utf-8")
    assert "ordinary stdout" in component
    assert "[worker]" not in component
    assert "[worker] ordinary stdout" in stack
    assert "[worker] ordinary stdout" in completed.stdout
    assert completed.stderr == ""
    for secret in ("header-secret", "json-secret", "QUJDREVGR0g="):
        assert secret not in component
        assert secret not in stack
        assert secret not in completed.stdout
    assert "[REDACTED]" in component
    assert "[REDACTED_IMAGE]" in component


def test_runtime_log_supervisor_preserves_one_complete_long_line(tmp_path: Path) -> None:
    long_line = "visible-" + (("x" * 32 + ":") * 4096) + "-complete"
    workload = 'print("visible-" + (("x" * 32 + ":") * 4096) + "-complete", flush=True)'

    completed, stack_log, component_log = _run_supervisor(tmp_path, workload, label="api")

    assert completed.returncode == 0, completed.stderr
    assert component_log.read_text(encoding="utf-8") == f"{long_line}\n"
    assert stack_log.read_text(encoding="utf-8") == f"[api] {long_line}\n"
    assert completed.stdout == f"[api] {long_line}\n"


def test_windows_pid_handoff_allows_delayed_fake_bootstrap_within_startup_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(module.os, "name", "nt")
    gate = tmp_path / "delayed.gate"
    workload_pid_path = gate.with_suffix(".pid")
    clock_calls = 0
    sleep_calls = 0

    class FakeProcess:
        pid = 4321
        returncode = None
        killed = False
        waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 0

    class FakeJob:
        closed = False

        def assign(self, _process: FakeProcess) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    job = FakeJob()

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        workload_pid_path.write_text("", encoding="utf-8")
        return process

    def fake_monotonic() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return {1: 0.0, 2: 1.0, 3: 2.5}.get(clock_calls, 100.0)

    def fake_sleep(_delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            workload_pid_path.write_text("8765", encoding="utf-8")

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_WindowsJob", lambda: job)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)

    started, observed_job = module._start_workload(["ignored-workload"])

    assert started is process
    assert observed_job is job
    assert module._workload_pid(process) == 8765
    assert sleep_calls == 2
    assert not process.killed
    assert not process.waited
    assert not job.closed
    assert not workload_pid_path.exists()


def test_windows_startup_cleanup_preserves_primary_error_and_runs_every_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(module.os, "name", "nt")
    gate = tmp_path / "failed.gate"
    workload_pid_path = gate.with_suffix(".pid")
    events: list[object] = []

    class FakeProcess:
        pid = 4321
        returncode = 17

        def poll(self) -> int:
            return self.returncode

        def kill(self) -> None:
            events.append("process.kill")

        def wait(self, timeout: float | None = None) -> int:
            events.append(("process.wait", timeout))
            raise subprocess.TimeoutExpired(["fake-bootstrap"], timeout)

    class FakeJob:
        def assign(self, _process: FakeProcess) -> None:
            return None

        def close(self) -> None:
            events.append("job.close")
            raise OSError("job close failed")

    def fake_unlink(path: Path) -> None:
        events.append(("unlink", path))
        if path == gate:
            raise PermissionError("gate unlink failed")

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(module, "_WindowsJob", FakeJob)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(module, "_unlink_with_windows_retry", fake_unlink)

    with pytest.raises(OSError, match="workload bootstrap exited before PID handoff: 17") as raised:
        module._start_workload(["ignored-workload"])

    assert events == [
        "process.kill",
        ("process.wait", module._STOP_GRACE_SEC),
        "job.close",
        ("unlink", gate),
        ("unlink", workload_pid_path),
    ]
    notes = getattr(raised.value, "__notes__", [])
    assert any("process.wait" in note and "timed out" in note for note in notes)
    assert any("job.close" in note and "job close failed" in note for note in notes)
    assert any("unlink" in note and "gate unlink failed" in note for note in notes)


def test_append_writer_rechecks_cancellation_after_guard(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    output = tmp_path / "stack.log"
    writer = module._AppendWriter(output, shared=False)
    cancelled = threading.Event()

    def cancel_during_guard() -> None:
        cancelled.set()

    try:
        published = writer.write("PASS: guarded publication\n", cancelled=cancelled, guard=cancel_during_guard)
    finally:
        writer.close()

    assert published is False
    assert output.read_bytes() == b""


def test_status_sidecar_writer_uses_atomic_replaces_and_valid_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    status_file = tmp_path / "worker.status.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = module.os.replace

    def recording_replace(source: Path, target: Path) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", recording_replace)
    writer = module._StatusWriter(status_file, component="worker")

    writer.write("starting", workload_pid=None, exit_code=None)
    writer.write("running", workload_pid=4321, exit_code=None)
    writer.write("exited", workload_pid=4321, exit_code=23)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "run_id": tmp_path.name,
        "component": "worker",
        "state": "exited",
        "supervisor_pid": os.getpid(),
        "workload_pid": 4321,
        "exit_code": 23,
        "updated_at": payload["updated_at"],
    }
    assert payload["updated_at"].endswith("Z")
    assert [target for _, target in replacements] == [status_file, status_file, status_file]
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows replace sharing contract")
def test_status_sidecar_retries_transient_windows_replace_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    status_file = tmp_path / "api.status.json"
    real_replace = module.os.replace
    attempts = 0
    sleeps: list[float] = []

    def transiently_denied_replace(source: Path, target: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(13, "transient Windows sharing denial", source, target)
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", transiently_denied_replace)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    writer = module._StatusWriter(status_file, component="api")

    writer.write("starting", workload_pid=None, exit_code=None)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["state"] == "starting"
    assert attempts == 2
    assert sleeps
    assert not list(tmp_path.glob("*.tmp"))


def test_status_sidecar_uses_explicit_launcher_registered_supervisor_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setenv("VSA_SUPERVISOR_REGISTERED_PID", "4242")
    status_file = tmp_path / "es.status.json"

    writer = module._StatusWriter(status_file, component="es")
    writer.write("starting", workload_pid=None, exit_code=None)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["supervisor_pid"] == 4242


def test_windows_workload_pid_handoff_files_use_retrying_unlink_helper() -> None:
    source = SUPERVISOR.read_text(encoding="utf-8")

    assert "def _unlink_with_windows_retry(" in source
    assert "workload_pid_path.unlink(" not in source
    assert "_unlink_with_windows_retry(workload_pid_path)" in source
    assert "_unlink_with_windows_retry(gate)" in source


def test_windows_bootstrap_publishes_pid_with_same_directory_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "bootstrap.gate"
    pid_path = tmp_path / "bootstrap.pid"
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    class FakeProcess:
        pid = 4242

        def wait(self) -> int:
            return 0

    def observe_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        source_path = Path(source)
        target_path = Path(target)
        assert target_path == pid_path
        assert source_path.parent == pid_path.parent
        assert source_path != pid_path
        assert not pid_path.exists()
        replacements.append((source_path, target_path))
        real_replace(source, target)

    gate.touch()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(module.os, "replace", observe_replace)
    monkeypatch.setattr(sys, "argv", ["bootstrap", str(gate), str(pid_path), "ignored-workload"])

    with pytest.raises(SystemExit) as exited:
        exec(module._WINDOWS_BOOTSTRAP, {"__name__": "__main__"})

    assert exited.value.code == 0
    assert replacements
    assert pid_path.read_text(encoding="utf-8") == "4242"
    assert not list(tmp_path.glob(".bootstrap.pid.*.tmp"))


def test_windows_bootstrap_removes_pid_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "bootstrap.gate"
    pid_path = tmp_path / "bootstrap.pid"

    class FakeProcess:
        pid = 4242

        def wait(self) -> int:
            return 0

    def denied_replace(*_args: object) -> None:
        raise OSError("PID handoff replace denied")

    gate.touch()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(module.os, "replace", denied_replace)
    monkeypatch.setattr(sys, "argv", ["bootstrap", str(gate), str(pid_path), "ignored-workload"])

    with pytest.raises(OSError, match="PID handoff replace denied"):
        exec(module._WINDOWS_BOOTSTRAP, {"__name__": "__main__"})

    assert not pid_path.exists()
    assert not list(tmp_path.glob(".bootstrap.pid.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows replace sharing contract")
def test_windows_bootstrap_retries_transient_pid_replace_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "bootstrap.gate"
    pid_path = tmp_path / "bootstrap.pid"
    attempts = 0
    real_replace = os.replace

    class FakeProcess:
        pid = 4242

        def wait(self) -> int:
            return 0

    def transiently_denied_replace(source: object, target: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("PID handoff target is being read")
        real_replace(source, target)

    gate.touch()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(module.os, "replace", transiently_denied_replace)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(sys, "argv", ["bootstrap", str(gate), str(pid_path), "ignored-workload"])

    with pytest.raises(SystemExit) as exited:
        exec(module._WINDOWS_BOOTSTRAP, {"__name__": "__main__"})

    assert exited.value.code == 0
    assert attempts == 2
    assert pid_path.read_text(encoding="utf-8") == "4242"
    assert not list(tmp_path.glob(".bootstrap.pid.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows PID handoff contract")
def test_windows_pid_handoff_waits_for_nonempty_pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "bootstrap.gate"
    workload_pid_path = gate.with_suffix(".pid")
    published = threading.Event()
    publisher: threading.Thread | None = None

    class FakeProcess:
        pid = 1
        returncode = None
        killed = False
        waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 1

    class FakeJob:
        closed = False

        def assign(self, process: FakeProcess) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    job = FakeJob()

    def delayed_popen(*args: object, **kwargs: object) -> FakeProcess:
        nonlocal publisher
        workload_pid_path.write_text("", encoding="utf-8")

        def publish_pid() -> None:
            time.sleep(0.02)
            workload_pid_path.write_text("4242", encoding="utf-8")
            published.set()

        publisher = threading.Thread(target=publish_pid)
        publisher.start()
        return process

    monkeypatch.setattr(module, "_WindowsJob", lambda: job)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(module.subprocess, "Popen", delayed_popen)
    monkeypatch.setattr(module.os, "name", "nt")

    try:
        started, observed_job = module._start_workload(["ignored-workload"])
    finally:
        assert publisher is not None
        publisher.join(timeout=1)

    assert published.is_set()
    assert started is process
    assert observed_job is job
    assert module._workload_pid(process) == 4242
    assert not workload_pid_path.exists()


def test_status_sidecar_records_real_workload_exit_before_log_drain(tmp_path: Path) -> None:
    status_file = tmp_path / "api.status.json"
    workload_pid_file = tmp_path / "workload.pid"
    observed_running = tmp_path / "running.observed"
    stack_log = tmp_path / "stack.log"
    component_log = tmp_path / "api.log"
    workload = """
import json
import os
import pathlib
import subprocess
import sys
import time

status_file, pid_file, observed = map(pathlib.Path, sys.argv[1:4])
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    try:
        payload = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        time.sleep(0.005)
        continue
    if payload.get("state") == "running" and payload.get("workload_pid") == os.getpid():
        observed.write_text("running", encoding="utf-8")
        break
    time.sleep(0.005)
else:
    raise SystemExit(41)
pid_file.write_text(str(os.getpid()), encoding="utf-8")
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
print("drain-held-open", flush=True)
raise SystemExit(23)
"""
    process = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--label",
            "api",
            "--stack-log",
            str(stack_log),
            "--component-log",
            str(component_log),
            "--status-file",
            str(status_file),
            "--component",
            "api",
            "--",
            sys.executable,
            "-c",
            workload,
            str(status_file),
            str(workload_pid_file),
            str(observed_running),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    saw_exited_while_supervisor_alive = False
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if status_file.exists():
                try:
                    payload = json.loads(status_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.005)
                    continue
                if payload["state"] == "exited":
                    saw_exited_while_supervisor_alive = process.poll() is None
                    break
            assert process.poll() is None
            time.sleep(0.005)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert process.returncode == 23, stderr
    assert observed_running.read_text(encoding="utf-8") == "running"
    assert payload["state"] == "exited"
    assert payload["supervisor_pid"] == process.pid
    assert payload["workload_pid"] == int(workload_pid_file.read_text(encoding="utf-8"))
    assert payload["exit_code"] == 23
    assert saw_exited_while_supervisor_alive
    assert "[api] drain-held-open" in stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows deterministic guarded publication probe")
def test_guarded_pass_rejects_terminal_sidecar_while_component_supervisor_drains(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stack_log = run_dir / "stack.log"
    status_file = run_dir / "api.status.json"
    component_trigger = tmp_path / "component.trigger"
    pass_ready = tmp_path / "pass.ready"
    pass_release = tmp_path / "pass.release"
    component_workload = """
import pathlib
import subprocess
import sys
import time

trigger = pathlib.Path(sys.argv[1])
while not trigger.exists():
    time.sleep(0.005)
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
print("drain-held-open", flush=True)
raise SystemExit(17)
"""
    component = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--label",
            "api",
            "--stack-log",
            str(stack_log),
            "--component-log",
            str(run_dir / "api.log"),
            "--status-file",
            str(status_file),
            "--component",
            "api",
            "--",
            sys.executable,
            "-c",
            component_workload,
            str(component_trigger),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    guarded = None
    try:
        payload = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if status_file.exists():
                try:
                    payload = json.loads(status_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.005)
                    continue
                if payload.get("state") == "running":
                    break
            assert component.poll() is None
            time.sleep(0.005)
        assert payload is not None
        assert payload["state"] == "running"
        pass_workload = (
            "import pathlib,sys,time; ready,release=map(pathlib.Path,sys.argv[1:3]); "
            "ready.touch(); "
            "exec('while not release.exists():\\n time.sleep(0.005)'); "
            "print('PASS: guarded publication', flush=True)"
        )
        guarded = subprocess.Popen(
            [
                sys.executable,
                str(SUPERVISOR),
                "--label",
                "stack",
                "--stack-log",
                str(stack_log),
                "--require-running-status",
                "api",
                str(component.pid),
                str(status_file),
                "--",
                sys.executable,
                "-c",
                pass_workload,
                str(pass_ready),
                str(pass_release),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while not pass_ready.exists() and time.monotonic() < deadline:
            assert guarded.poll() is None
            time.sleep(0.005)
        assert pass_ready.exists()
        component_trigger.touch()
        saw_exited_while_draining = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                payload = json.loads(status_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.005)
                continue
            if payload.get("state") == "exited":
                saw_exited_while_draining = component.poll() is None
                break
            assert component.poll() is None
            time.sleep(0.005)
        assert saw_exited_while_draining
        assert payload["exit_code"] == 17
        pass_release.touch()
        guarded_stdout, guarded_stderr = guarded.communicate(timeout=10)
        component.communicate(timeout=10)
    finally:
        component_trigger.touch()
        pass_release.touch()
        for process in (guarded, component):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    assert guarded.returncode == 17, guarded_stderr
    assert "PASS:" not in guarded_stdout
    assert "PASS:" not in guarded_stderr
    assert "PASS:" not in stack_log.read_text(encoding="utf-8")


def test_status_sidecar_starting_write_failure_does_not_start_workload(tmp_path: Path) -> None:
    blocked_status = tmp_path / "blocked.status.json"
    blocked_status.mkdir()
    workload_marker = tmp_path / "workload.started"

    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--label",
            "worker",
            "--stack-log",
            str(tmp_path / "stack.log"),
            "--status-file",
            str(blocked_status),
            "--component",
            "worker",
            "--",
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')",
            str(workload_marker),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode != 0
    assert "status sidecar write failed" in completed.stderr
    assert not workload_marker.exists()


def test_status_sidecar_running_write_failure_stops_started_workload_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    real_start_workload = module._start_workload
    started: list[tuple[object, object]] = []

    class FailingStatusWriter:
        def __init__(self, _path: Path, *, component: str) -> None:
            assert component == "worker"
            self.states: list[str] = []

        def write(self, state: str, *, workload_pid: int | None, exit_code: int | None) -> None:
            self.states.append(state)
            if state == "running":
                raise OSError("sidecar disk failure")

    writer = FailingStatusWriter(tmp_path / "ignored", component="worker")

    def recording_start(command: list[str]):
        result = real_start_workload(command)
        started.append(result)
        return result

    monkeypatch.setattr(module, "_StatusWriter", lambda *args, **kwargs: writer)
    monkeypatch.setattr(module, "_start_workload", recording_start)
    args = module._parse_args(
        [
            "--label",
            "worker",
            "--stack-log",
            str(tmp_path / "stack.log"),
            "--status-file",
            str(tmp_path / "worker.status.json"),
            "--component",
            "worker",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
    )

    return_code = module.run(args)

    assert return_code != 0
    assert writer.states == ["starting", "running"]
    assert len(started) == 1
    process, _job = started[0]
    assert process.poll() is not None


def test_terminal_status_write_failure_leaves_fail_closed_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    real_write = module._StatusWriter.write

    def fail_terminal_write(self: object, state: str, *, workload_pid: int | None, exit_code: int | None) -> None:
        if state == "exited":
            raise OSError("terminal sidecar failure")
        real_write(self, state, workload_pid=workload_pid, exit_code=exit_code)

    monkeypatch.setattr(module._StatusWriter, "write", fail_terminal_write)
    status_file = tmp_path / "worker.status.json"
    args = module._parse_args(
        [
            "--label",
            "worker",
            "--stack-log",
            str(tmp_path / "stack.log"),
            "--status-file",
            str(status_file),
            "--component",
            "worker",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(17)",
        ]
    )

    return_code = module.run(args)

    assert return_code != 0
    marker = status_file.with_suffix(".status_failure.json")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["component"] == "worker"
    assert payload["state"] == "exited"
    assert "terminal sidecar failure" in payload["error"]


def test_terminal_marker_creation_failure_blocks_guarded_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_supervisor_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stack_log = run_dir / "stack.log"
    status_file = run_dir / "api.status.json"

    def fail_marker(self: object, state: str, error: str) -> None:
        raise OSError(f"marker create failed for {state}: {error}")

    class FakeProcess:
        pid = 4321
        stdout = iter(["PASS: stale running sidecar\n"])

        def poll(self) -> int:
            return 17

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 17

    monkeypatch.setattr(module._StatusWriter, "write_failure_marker", fail_marker)
    monkeypatch.setattr(module, "_start_workload", lambda _command: (FakeProcess(), None))
    args = module._parse_args(
        [
            "--label",
            "api",
            "--stack-log",
            str(stack_log),
            "--status-file",
            str(status_file),
            "--component",
            "api",
            "--require-running-status",
            "api",
            str(os.getpid()),
            str(status_file),
            "--",
            "ignored",
        ]
    )

    return_code = module.run(args)

    stack = stack_log.read_text(encoding="utf-8")
    failure_events = [
        json.loads(line)
        for line in stack.splitlines()
        if line.startswith("{") and json.loads(line).get("event") == "status_sidecar_write_failed"
    ]
    assert return_code != 0
    assert failure_events == [
        {
            "event": "status_sidecar_write_failed",
            "run_id": "run",
            "component": "api",
            "state": "exited",
            "error": "marker create failed for exited: pending exited status transition",
        }
    ]
    assert "PASS:" not in stack


def test_supervisor_finally_stops_live_workload_when_terminal_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_supervisor_module()
    stopped: list[tuple[object, object]] = []

    class FailingWriter:
        def __init__(self, _path: Path, *, shared: bool) -> None:
            self.shared = shared

        def write(
            self,
            _text: str,
            *,
            cancelled: object | None = None,
            guard: object | None = None,
        ) -> bool:
            raise OSError("terminal writer failed")

        def close(self) -> None:
            pass

    class FakeProcess:
        pid = 4321
        stdout = iter(["visible\n"])

        def poll(self) -> None:
            return None

    class FakeJob:
        def close(self) -> None:
            pass

    process = FakeProcess()
    job = FakeJob()
    monkeypatch.setattr(module, "_AppendWriter", FailingWriter)
    monkeypatch.setattr(module, "_start_workload", lambda *args, **kwargs: (process, job))
    monkeypatch.setattr(module, "_stop_workload_tree", lambda owned, owner: stopped.append((owned, owner)))
    args = module._parse_args(["--label", "stack", "--stack-log", str(tmp_path / "stack.log"), "--", "ignored"])

    with pytest.raises(OSError, match="terminal writer failed"):
        module.run(args)

    assert stopped == [(process, job)]


def test_windows_sync_workload_without_status_file_uses_assignment_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(module.os, "name", "nt")
    observed: dict[str, object] = {}
    gate = tmp_path / "sync.gate"
    workload_pid_path = gate.with_suffix(".pid")

    class FakeProcess:
        pid = 4321
        _handle = 123
        returncode = None
        killed = False
        waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 1

    def fake_popen(command: list[str], **options: object) -> FakeProcess:
        observed["command"] = command
        observed["options"] = options
        workload_pid_path.write_text("8765", encoding="utf-8")
        return FakeProcess()

    class FakeJob:
        assigned: object | None = None

        def assign(self, process: object) -> None:
            self.assigned = process

        def close(self) -> None:
            pass

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    job_holder = FakeJob()
    monkeypatch.setattr(module, "_WindowsJob", lambda: job_holder)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)

    process, job = module._start_workload(["python", "-c", "print('ok')"])

    assert process.pid == 4321
    assert job is job_holder
    assert job_holder.assigned is process
    assert module._WINDOWS_BOOTSTRAP in observed["command"]
    assert process._vsa_workload_pid == 8765
    assert not workload_pid_path.exists()


def test_windows_pid_handoff_unlink_failure_does_not_stop_started_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(module.os, "name", "nt")
    gate = tmp_path / "unlink.gate"
    workload_pid_path = gate.with_suffix(".pid")

    class FakeProcess:
        pid = 4321
        _handle = 123
        returncode = None
        killed = False
        waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 1

    class FakeJob:
        closed = False

        def assign(self, _process: object) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    job = FakeJob()

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        workload_pid_path.write_text("8765", encoding="utf-8")
        return process

    def failing_unlink(path: Path) -> None:
        if path == workload_pid_path:
            raise PermissionError("PID handoff unlink denied")
        path.unlink(missing_ok=True)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_WindowsJob", lambda: job)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(module, "_unlink_with_windows_retry", failing_unlink)

    started, observed_job = module._start_workload(["ignored"])

    assert started is process
    assert observed_job is job
    assert module._workload_pid(process) == 8765
    assert not process.killed
    assert not process.waited
    assert not job.closed


def test_windows_pid_handoff_retries_transient_read_denial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(module.os, "name", "nt")
    gate = tmp_path / "read.gate"
    workload_pid_path = gate.with_suffix(".pid")
    real_read_text = Path.read_text
    read_attempts = 0

    class FakeProcess:
        pid = 4321
        _handle = 123
        returncode = None
        killed = False
        waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 1

    class FakeJob:
        closed = False

        def assign(self, _process: object) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    job = FakeJob()

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        workload_pid_path.write_text("8765", encoding="utf-8")
        return process

    def transiently_denied_read(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal read_attempts
        if path == workload_pid_path:
            read_attempts += 1
            if read_attempts == 1:
                raise PermissionError(13, "PID handoff read denied", path)
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_WindowsJob", lambda: job)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(Path, "read_text", transiently_denied_read)

    started, observed_job = module._start_workload(["ignored"])

    assert started is process
    assert observed_job is job
    assert module._workload_pid(process) == 8765
    assert read_attempts == 2
    assert not process.killed
    assert not process.waited
    assert not job.closed
    assert not workload_pid_path.exists()


def test_windows_bash_command_wraps_when_bash_env_marks_bash_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_supervisor_module()
    bash_path = r"D:\working\Git\usr\bin\bash.exe"
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.setenv("BASH_ENV", "D:/WorkPlace/vsa-agent/harness-env.sh")
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: bash_path if name == "bash" else None,
    )

    wrapped = module._windows_bash_command(["python", "scripts/runtime-doctor.py"])

    assert wrapped == [
        bash_path,
        "-c",
        'exec "$@"',
        "runtime-log-supervisor",
        "python",
        "scripts/runtime-doctor.py",
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_job_close_kills_only_the_assigned_workload(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    child_pid_path = tmp_path / "owned.pid"
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process = None
    job = None
    try:
        process, job = module._start_workload(
            [
                sys.executable,
                "-c",
                "import pathlib,sys,time; "
                "pathlib.Path(sys.argv[1]).write_text(str(__import__('os').getpid())); "
                "time.sleep(30)",
                str(child_pid_path),
            ]
        )
        deadline = time.monotonic() + 5
        while not child_pid_path.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.01)
        assert child_pid_path.exists()
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        assert job is not None
        job.close()
        process.wait(timeout=5)
        deadline = time.monotonic() + 3
        while _windows_process_is_running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)

        assert not _windows_process_is_running(child_pid)
        assert unrelated.poll() is None
    finally:
        if job is not None:
            job.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
        if unrelated.poll() is None:
            unrelated.kill()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_job_assignment_failure_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "start.gate"

    class FakeProcess:
        _handle = 123
        killed = False
        waited = False

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            self.waited = True
            return 1

    class FailingJob:
        assigned_process = None
        closed = False

        def assign(self, process: FakeProcess) -> None:
            self.assigned_process = process
            raise OSError("assignment denied")

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    job = FailingJob()
    monkeypatch.setattr(module, "_WindowsJob", lambda: job)
    monkeypatch.setattr(module, "_new_windows_start_gate", lambda: gate)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(OSError, match="assignment denied"):
        module._start_workload(["ignored-workload"])

    assert job.assigned_process is process
    assert process.killed
    assert process.waited
    assert job.closed
    assert not gate.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_real_bootstrap_waits_for_assignment_gate(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    gate = tmp_path / "bootstrap.gate"
    workload_pid_path = tmp_path / "bootstrap.pid"
    marker = tmp_path / "workload.marker"
    job = module._WindowsJob()
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            module._WINDOWS_BOOTSTRAP,
            str(gate),
            str(workload_pid_path),
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')",
            str(marker),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        job.assign(process)
        time.sleep(0.2)
        assert process.poll() is None
        assert not marker.exists()

        gate.touch()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.01)
        assert marker.read_text(encoding="utf-8") == "started"
        assert int(workload_pid_path.read_text(encoding="utf-8")) > 0
        assert process.wait(timeout=5) == 0
    finally:
        job.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def test_concurrent_supervisors_append_complete_large_lines_and_flush(tmp_path: Path) -> None:
    stack_log = tmp_path / "stack.log"
    workload = (
        "import sys; label=sys.argv[1]; payload=(label + '|') * 32768; "
        "[print(f'{label}:{index}:{payload}:complete', flush=True) for index in range(2)]"
    )
    processes = []
    for label in ("api", "worker"):
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(SUPERVISOR),
                    "--label",
                    label,
                    "--stack-log",
                    str(stack_log),
                    "--component-log",
                    str(tmp_path / f"{label}.log"),
                    "--",
                    sys.executable,
                    "-c",
                    workload,
                    label,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

    outputs = [process.communicate(timeout=15) for process in processes]
    assert [process.returncode for process in processes] == [0, 0]
    assert all(stderr == "" for _, stderr in outputs)

    lines = stack_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    expected = {
        f"[{label}] {label}:{index}:{(label + '|') * 32768}:complete"
        for label in ("api", "worker")
        for index in range(2)
    }
    assert set(lines) == expected


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal and process-group contract")
def test_runtime_log_supervisor_signal_closes_descendant_writers_and_returns_130(tmp_path: Path) -> None:
    stack_log = tmp_path / "stack.log"
    component_log = tmp_path / "worker.log"
    child_pid_path = tmp_path / "child.pid"
    workload = """
import pathlib
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
print("ready", flush=True)
time.sleep(3600)
"""
    process = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--label",
            "worker",
            "--stack-log",
            str(stack_log),
            "--component-log",
            str(component_log),
            "--",
            sys.executable,
            "-c",
            workload,
            str(child_pid_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not child_pid_path.exists():
            assert process.poll() is None
            time.sleep(0.02)
        assert child_pid_path.exists()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode == 130
    assert "[worker] ready" in stdout
    assert stderr == ""
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
