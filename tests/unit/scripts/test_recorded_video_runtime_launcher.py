from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")
RUNTIME_LOG_SUPERVISOR = Path("scripts/runtime-log-supervisor.py")
POWERSHELL_SCRIPT = Path("scripts/es-runtime-stack.ps1")
POWERSHELL_LOG_PUMP = Path("scripts/lib/RuntimeLogPump.cs")
BASH_RUNTIME_READINESS_TIMEOUT_SEC = 90
BASH_SMOKE_COMPLETION_BOUNDARY_TIMEOUT_SEC = 180
RUNTIME_TREE_OBSERVATION_INTERVAL_SEC = 2.0


def _bash() -> str:
    return BASH_SCRIPT.read_text(encoding="utf-8")


def _powershell() -> str:
    return POWERSHELL_SCRIPT.read_text(encoding="utf-8")


def _ordered(text: str, *markers: str) -> None:
    positions = [text.rindex(marker) for marker in markers]
    assert positions == sorted(positions), dict(zip(markers, positions, strict=True))


def _conditional_block(text: str, opening: str, closing: str) -> str:
    start = text.index(opening)
    end = text.index(closing, start)
    return text[start:end]


def _bash_function(name: str) -> str:
    text = _bash()
    start = text.index(f"{name}() {{")
    depth = 0
    lines: list[str] = []
    for line in text[start:].splitlines():
        lines.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            break
    return "\n".join(lines)


def _powershell_function(name: str) -> str:
    script = POWERSHELL_SCRIPT.resolve()
    probe = textwrap.dedent(
        f"""
        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            '{script}', [ref]$tokens, [ref]$errors
        )
        if ($errors.Count -ne 0) {{ throw ($errors | Out-String) }}
        $node = $ast.FindAll(
            {{
                param($n)
                $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '{name}'
            }},
            $true
        ) | Select-Object -First 1
        if ($null -eq $node) {{ exit 44 }}
        [Console]::Out.Write($node.Extent.Text)
        """
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _powershell_shutdown_functions() -> str:
    return "\n\n".join(
        _powershell_function(name)
        for name in (
            "ConvertTo-TrackedProcessIdentity",
            "Test-TrackedProcessIdentity",
            "Update-ProcessTracker",
            "Stop-OwnedProcessTree",
        )
    )


def _create_windows_kill_on_close_job() -> tuple[object, int]:
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
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

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = _ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job_handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        primary_error = ctypes.WinError(ctypes.get_last_error())
        if not kernel32.CloseHandle(job_handle):
            primary_error.add_note(f"CloseHandle failed: {ctypes.WinError(ctypes.get_last_error())!r}")
        raise primary_error
    return kernel32, int(job_handle)


def _run_job_owned_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    import ctypes

    shim = (
        "import subprocess,sys\n"
        "if sys.stdin.buffer.read(1) != b'1': raise SystemExit(125)\n"
        "raise SystemExit(subprocess.call(sys.argv[1:], creationflags=0x200))\n"
    )
    shim_command = [sys.executable, "-S", "-c", shim, *command]
    job_api, job_handle = _create_windows_kill_on_close_job()
    process: subprocess.Popen[str] | None = None
    stdout: str | None = None
    stderr: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []

    def remember_timeout_output(error: subprocess.TimeoutExpired) -> None:
        nonlocal stdout, stderr
        if error.output is not None:
            stdout = error.output
        if error.stderr is not None:
            stderr = error.stderr

    try:
        process = subprocess.Popen(
            shim_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        if not job_api.AssignProcessToJobObject(job_handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert process.stdin is not None
        process.stdin.write("1")
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None

        deadline = time.monotonic() + timeout
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired as error:
                remember_timeout_output(error)
            else:
                break
    except BaseException as error:
        primary_error = error
    finally:

        def cleanup_stage(name: str, action) -> None:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(f"{name}: {error!r}")

        def close_gate() -> None:
            if process is None or process.stdin is None:
                return
            stream = process.stdin
            process.stdin = None
            stream.close()

        def windows_call_error(operation: str) -> RuntimeError:
            return RuntimeError(f"{operation} failed: {ctypes.WinError(ctypes.get_last_error())!r}")

        def close_job() -> None:
            nonlocal job_handle
            if job_handle is None:
                return
            if not job_api.CloseHandle(job_handle):
                raise windows_call_error("CloseHandle")
            job_handle = None

        def terminate_job_fallback() -> None:
            nonlocal job_handle
            if job_handle is None:
                return
            handle = job_handle
            job_handle = None
            errors: list[Exception] = []
            try:
                if not job_api.TerminateJobObject(handle, 1):
                    errors.append(windows_call_error("TerminateJobObject"))
            finally:
                if not job_api.CloseHandle(handle):
                    errors.append(windows_call_error("CloseHandle"))
            if len(errors) == 1:
                raise errors[0]
            if errors:
                raise ExceptionGroup("Windows Job termination and handle close failed", errors)

        def kill_root_fallback() -> None:
            if process is not None and process.poll() is None:
                process.kill()

        def drain_pipes() -> None:
            nonlocal stdout, stderr
            if process is None:
                return
            try:
                final_stdout, final_stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as error:
                remember_timeout_output(error)
                raise
            else:
                stdout = final_stdout if final_stdout is not None else stdout
                stderr = final_stderr if final_stderr is not None else stderr

        cleanup_stage("release-gate close", close_gate)
        cleanup_stage("kill-on-close job release", close_job)
        cleanup_stage("explicit job termination fallback", terminate_job_fallback)
        cleanup_stage("root process-handle fallback", kill_root_fallback)
        cleanup_stage("stdout/stderr drain", drain_pipes)

    if isinstance(primary_error, subprocess.TimeoutExpired):
        primary_error.cmd = command
        primary_error.output = stdout
        primary_error.stderr = stderr
    if primary_error is not None:
        if cleanup_errors:
            primary_error.add_note("Bash probe cleanup failed: " + "; ".join(cleanup_errors))
        raise primary_error.with_traceback(primary_error.__traceback__)
    if cleanup_errors:
        raise AssertionError("Bash probe cleanup failed: " + "; ".join(cleanup_errors))
    assert process is not None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_runtime_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    shim = (
        "import subprocess,sys\n"
        "if sys.stdin.buffer.read(1) != b'1': raise SystemExit(125)\n"
        "raise SystemExit(subprocess.call(sys.argv[1:], creationflags=0x200))\n"
    )
    shim_command = [sys.executable, "-S", "-c", shim, *command]
    process: subprocess.Popen[str] | None = None
    registry: dict[str, dict[str, object]] = {}
    stdout: str | None = None
    stderr: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []
    next_observation = 0.0

    def remember_timeout_output(error: subprocess.TimeoutExpired) -> None:
        nonlocal stdout, stderr
        if error.output is not None:
            stdout = error.output
        if error.stderr is not None:
            stderr = error.stderr

    def observe_owned_tree(*, force: bool = False) -> list[dict[str, object]] | None:
        nonlocal next_observation
        assert process is not None
        now = time.monotonic()
        if not force and now < next_observation:
            return None
        snapshot = _powershell_process_snapshot()
        if not registry:
            root = next((item for item in snapshot if int(item["pid"]) == process.pid), None)
            if root is not None:
                _register_powershell_root_identity(registry, root)
            elif process.poll() is None:
                raise AssertionError(f"Could not capture runtime shim identity for PID {process.pid}")
        _record_owned_powershell_descendants(registry, snapshot)
        next_observation = time.monotonic() + RUNTIME_TREE_OBSERVATION_INTERVAL_SEC
        return snapshot

    try:
        process = subprocess.Popen(
            shim_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        observe_owned_tree(force=True)
        assert process.stdin is not None
        process.stdin.write("1")
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None
        observe_owned_tree(force=True)

        deadline = time.monotonic() + timeout
        while process.poll() is None:
            observe_owned_tree()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired as error:
                remember_timeout_output(error)
            else:
                break
    except BaseException as error:
        primary_error = error
    finally:

        def cleanup_stage(name: str, action) -> None:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(f"{name}: {error!r}")

        def close_gate() -> None:
            if process is None or process.stdin is None:
                return
            stream = process.stdin
            process.stdin = None
            stream.close()

        def terminate_registered_tree() -> None:
            snapshot = observe_owned_tree(force=True)
            assert snapshot is not None
            if _current_registered_powershell_processes(registry, snapshot):
                _terminate_exact_powershell_processes(list(registry.values()))

        def kill_root_fallback() -> None:
            if process is not None and process.poll() is None:
                process.kill()

        def drain_pipes() -> None:
            nonlocal stdout, stderr
            if process is None:
                return
            try:
                final_stdout, final_stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as error:
                remember_timeout_output(error)
                raise
            else:
                stdout = final_stdout if final_stdout is not None else stdout
                stderr = final_stderr if final_stderr is not None else stderr

        def verify_cleanup() -> None:
            snapshot = _powershell_process_snapshot()
            _record_owned_powershell_descendants(registry, snapshot)
            remaining = _current_registered_powershell_processes(registry, snapshot)
            if remaining:
                raise AssertionError(f"Runtime runner left owned processes: {remaining}")

        cleanup_stage("release-gate close", close_gate)
        cleanup_stage("exact registered-tree termination", terminate_registered_tree)
        cleanup_stage("root process-handle fallback", kill_root_fallback)
        cleanup_stage("stdout/stderr drain", drain_pipes)
        cleanup_stage("final residual verification", verify_cleanup)

    if isinstance(primary_error, subprocess.TimeoutExpired):
        primary_error.cmd = command
        primary_error.output = stdout
        primary_error.stderr = stderr
    if primary_error is not None:
        if cleanup_errors:
            primary_error.add_note("Runtime runner cleanup failed: " + "; ".join(cleanup_errors))
        raise primary_error.with_traceback(primary_error.__traceback__)
    if cleanup_errors:
        raise AssertionError("Runtime runner cleanup failed: " + "; ".join(cleanup_errors))
    assert process is not None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _real_bash_path(bash: str) -> str:
    bash_path = Path(bash).resolve()
    real_bash = bash_path.parent.parent / "usr" / "bin" / "bash.exe"
    if os.name == "nt" and bash_path.parent.name.casefold() == "bin" and real_bash.exists():
        return str(real_bash)
    return str(bash_path)


def _run_bash_probe(body: str, *, timeout: float = 5) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    return _run_job_owned_command([_real_bash_path(bash), "-c", body], timeout=timeout)


def _bash_launcher_creationflags() -> int:
    return subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0


def test_bash_runtime_helper_uses_shared_readiness_timeout():
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_bash_runtime")
    run_call = next(
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "_run_runtime_command"
    )
    timeout_values = [keyword.value for keyword in run_call.keywords if keyword.arg == "timeout"]

    assert len(timeout_values) == 1
    assert ast.unparse(timeout_values[0]) == "BASH_RUNTIME_READINESS_TIMEOUT_SEC"


@pytest.mark.skipif(os.name != "nt", reason="regression covers Git for Windows Bash resolution")
def test_bash_runtime_resolves_git_wrapper_to_real_bash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wrapper = tmp_path / "Git/bin/bash.exe"
    real_bash = tmp_path / "Git/usr/bin/bash.exe"
    wrapper.parent.mkdir(parents=True)
    real_bash.parent.mkdir(parents=True)
    wrapper.touch()
    real_bash.touch()
    captured: dict[str, object] = {}
    real_which = shutil.which
    env = {"HARNESS_ENV": "preserved"}

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: str(wrapper) if name == "bash" else real_which(name))
    monkeypatch.setattr(sys.modules[__name__], "_run_runtime_command", fake_runner)

    completed = _run_bash_runtime(tmp_path, env, "--validate")

    assert completed.returncode == 0
    assert captured["command"] == [
        str(real_bash.resolve()),
        (tmp_path / "scripts/es-runtime-stack.sh").as_posix(),
        "--validate",
    ]
    assert captured["kwargs"] == {
        "cwd": tmp_path,
        "env": env,
        "timeout": BASH_RUNTIME_READINESS_TIMEOUT_SEC,
    }


def test_bash_runtime_launcher_processes_use_windows_process_group_isolation():
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    launcher_test_names = {
        "test_bash_keep_running_reaches_readiness_stays_alive_and_cleans_on_signal",
        "test_bash_interruption_cleans_validation_index_data_and_config",
        "test_bash_rapid_back_to_back_terms_before_cleanup_still_finish_cleanup",
        "test_bash_manifest_update_failure_during_signal_cleanup_is_aggregated",
        "test_bash_second_signal_during_cleanup_still_finishes_all_cleanup",
        "test_bash_signal_while_pass_log_is_lock_blocked_never_emits_pass",
    }
    launcher_starts = [
        call
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef) and function.name in launcher_test_names
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func) == "subprocess.Popen"
        and call.args
        and "es-runtime-stack.sh" in ast.unparse(call.args[0])
    ]

    assert launcher_starts
    assert "def _bash_launcher_creationflags()" in source
    assert all(
        any(
            keyword.arg == "creationflags" and ast.unparse(keyword.value) == "_bash_launcher_creationflags()"
            for keyword in call.keywords
        )
        for call in launcher_starts
    )


def test_bash_windows_cleanup_uses_only_registered_supervisor_pids():
    bash = _bash()
    stop_managed_process = _bash_function("stop_managed_process")

    assert "taskkill" not in bash.lower()
    assert 'stop_pid_bounded "$pid"' in stop_managed_process


def test_bash_launcher_records_its_running_msys_pid_in_the_run_directory():
    bash = _bash()

    assert 'LAUNCHER_PID="$BASHPID"' in bash
    assert 'LAUNCHER_PID_PATH="$RUN_DIR/launcher.pid"' in bash
    assert 'printf \'%s\\n\' "$LAUNCHER_PID" >"$LAUNCHER_PID_PATH"' in bash
    assert 'log_stack "launcher_pid=$LAUNCHER_PID"' in bash


def test_bash_stale_ui_cleanup_protects_launcher_ancestor_chain():
    function = _bash_function("stale_project_ui_pids")

    assert 'pid="$LAUNCHER_PID"' in function
    assert 'ps -p "$pid" -o ppid=' in function
    assert 'index(protected, " " $2 " ") == 0' in function


def test_bash_cleanup_internal_status_lines_do_not_start_new_supervisors():
    cleanup = _bash_function("cleanup")
    delete_validation_resources = _bash_function("delete_validation_resources")

    assert "log_stack " not in cleanup
    assert "log_stack " not in delete_validation_resources
    assert "log_stack_error " not in delete_validation_resources
    assert cleanup.count("cleanup_log_line ") >= 3
    assert "cleanup_log_error " in delete_validation_resources


def test_bash_status_publication_guards_all_registered_status_sidecars():
    publisher = _bash_function("publish_status")
    script = _bash()

    assert 'pid="${PROCESS_PIDS[$component]:-}"' in publisher
    assert 'status_file="${PROCESS_STATUS_FILES[$component]:-$RUN_DIR/$component.status.json}"' in publisher
    assert 'status_guards+=(--require-running-status "$component" "$pid" "$status_file")' in publisher
    assert 'publish_status "READY: isolated validation runtime' in script
    assert 'publish_status "PASS: ES runtime stack validation succeeded"' in script
    assert 'publish_status "PASS: ES recorded-video runtime stack is ready"' in script
    assert 'log_stack "READY:' not in script
    assert 'log_stack "PASS:' not in script


def test_bash_keep_running_ready_fails_closed_when_component_exits_after_preliminary_check():
    keep_running = _conditional_block(
        _bash(),
        '  if [[ "$KEEP_RUNNING" == "1" ]]; then',
        "    wait_runtime_processes",
    )
    publication_actions = [
        line.strip()
        for line in keep_running.splitlines()
        if line.strip() == "validate_managed_statuses"
        or line.strip().startswith(('log_stack "READY:', 'publish_status "READY:'))
    ]
    assert len(publication_actions) == 2
    probe = f"""
    set -Eeuo pipefail
    component_state=running
    API_URL=api
    UI_URL=ui
    ES_ENDPOINT=es
    VALIDATION_INDEX=index
    validate_managed_statuses() {{ [[ "$component_state" == "running" ]]; }}
    log_stack() {{ component_state=exited; printf '%s\n' "$*"; }}
    publish_status() {{
      component_state=exited
      [[ "$component_state" == "running" ]] || return 17
      printf '%s\n' "$*"
    }}
    {chr(10).join(publication_actions)}
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode == 17
    assert "READY:" not in completed.stdout
    assert "READY:" not in completed.stderr


def test_bash_pid_running_uses_kill_probe_without_msys_ps_polling():
    validator = _bash_function("pid_is_running")

    assert '[[ -n "${MSYSTEM:-}" || "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]' in validator
    assert "return 0" in validator


def test_bash_cleanup_fans_out_term_before_waiting_for_any_supervisor():
    cleanup = _bash_function("cleanup")

    requests = [
        cleanup.index(f"request_managed_process_stop {component}") for component in ("ui", "worker", "api", "es")
    ]
    waits = [cleanup.index(f'run_cleanup_stage "stop {component}"') for component in ("ui", "worker", "api", "es")]
    assert requests == sorted(requests)
    assert max(requests) < min(waits)


def test_bash_stop_pid_bounded_does_not_wait_when_kill_cannot_stop_pid():
    stop_pid_bounded = _bash_function("stop_pid_bounded")
    probe = f"""
    PROCESS_SHUTDOWN_GRACE_TICKS=1
    pid_is_running() {{ return 0; }}
    signal_process_tree() {{ printf 'signal=%s\\n' "$1" >&2; }}
    wait() {{ printf 'waited\\n' >&2; return 0; }}
    {stop_pid_bounded}
    stop_pid_bounded 4242
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode != 0
    assert "signal=TERM" in completed.stderr
    assert "signal=KILL" in completed.stderr
    assert "waited" not in completed.stderr


def test_bash_component_stop_failure_preserves_survivor_ownership():
    stop_managed_process = _bash_function("stop_managed_process")
    probe = f"""
    declare -A PROCESS_PIDS=([worker]=4242)
    stop_pid_bounded() {{ return 1; }}
    record_process_exit() {{ printf 'recorded=%s\\n' "$*"; }}
    {stop_managed_process}
    set +e
    stop_managed_process worker
    status=$?
    printf 'status=%s pid=%s\\n' "$status" "${{PROCESS_PIDS[worker]}}"
    exit "$status"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode != 0
    assert "pid=4242" in completed.stdout
    assert "recorded=" not in completed.stdout


def test_bash_sync_stop_failure_preserves_registered_pid_and_marks_cleanup_failed():
    stop_sync_supervisor = _bash_function("stop_sync_supervisor")
    cleanup = _bash_function("cleanup")
    probe = f"""
    SYNC_SUPERVISOR_PID=4242
    stop_pid_bounded() {{ return 1; }}
    {stop_sync_supervisor}
    set +e
    stop_sync_supervisor
    status=$?
    printf 'status=%s pid=%s\\n' "$status" "$SYNC_SUPERVISOR_PID"
    exit "$status"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode != 0
    assert "pid=4242" in completed.stdout
    assert 'run_cleanup_stage "stop sync supervisor" stop_sync_supervisor' in cleanup


def test_bash_managed_failure_sync_stop_failure_preserves_pid_without_extra_wait(tmp_path: Path):
    wait_sync_supervisor = _bash_function("wait_sync_supervisor")
    stop_called = tmp_path / "stop.called"
    wait_called = tmp_path / "wait.called"
    probe = f"""
    SYNC_SUPERVISOR_PID=4242
    MANAGED_EXIT_COMPONENT=worker
    MANAGED_EXIT_STATUS=17
    pid_is_running() {{ return 0; }}
    observe_managed_processes() {{ return 7; }}
    stop_pid_bounded() {{ return 1; }}
    stop_sync_supervisor() {{ : >{shlex.quote(stop_called.as_posix())}; return 1; }}
    wait() {{ : >{shlex.quote(wait_called.as_posix())}; return 0; }}
    log_stack_error() {{ :; }}
    {wait_sync_supervisor}
    set +e
    if wait_sync_supervisor 1; then status=0; else status=$?; fi
    printf 'status=%s pid=%s\\n' "$status" "$SYNC_SUPERVISOR_PID"
    exit "$status"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode != 0
    assert "pid=4242" in completed.stdout
    assert stop_called.exists()
    assert not wait_called.exists()


def test_bash_observe_managed_processes_preserves_pid_when_manifest_finalization_fails():
    observer = _bash_function("observe_managed_processes")
    probe = f"""
    declare -A PROCESS_PIDS=([api]=4242)
    MANAGED_EXIT_COMPONENT=""
    MANAGED_EXIT_STATUS=0
    pid_is_running() {{ return 1; }}
    wait() {{ return 17; }}
    record_process_exit() {{ return 91; }}
    {observer}
    set +e
    observe_managed_processes
    status=$?
    set -e
    printf 'status=%s pid=%s component=%s exit=%s\n' \
      "$status" "${{PROCESS_PIDS[api]}}" "$MANAGED_EXIT_COMPONENT" "$MANAGED_EXIT_STATUS"
    exit "$status"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode == 91
    assert "status=91 pid=4242 component=api exit=17" in completed.stdout


def test_bash_cleanup_retries_pending_exit_without_overwriting_observed_status():
    observer = _bash_function("observe_managed_processes")
    requester = _bash_function("request_managed_process_stop")
    stopper = _bash_function("stop_managed_process")
    probe = f"""
    declare -A PROCESS_PIDS=([api]=4242)
    declare -A PROCESS_PENDING_EXIT_STATUS=()
    MANAGED_EXIT_COMPONENT=""
    MANAGED_EXIT_STATUS=0
    STOPPED_PROCESS_STATUS=0
    wait_calls=0
    signal_calls=0
    stop_calls=0
    record_calls=0
    recorded_statuses=""
    pid_is_running() {{ return 1; }}
    kill() {{ signal_calls=$((signal_calls + 1)); return 0; }}
    wait() {{ wait_calls=$((wait_calls + 1)); return 17; }}
    stop_pid_bounded() {{ stop_calls=$((stop_calls + 1)); STOPPED_PROCESS_STATUS=127; return 0; }}
    record_process_exit() {{
      record_calls=$((record_calls + 1))
      recorded_statuses="${{recorded_statuses}}$2,"
      [[ "$record_calls" == "1" ]] && return 91
      return 0
    }}
    {observer}
    {requester}
    {stopper}
    set +e
    observe_managed_processes
    observe_status=$?
    request_managed_process_stop api
    stop_managed_process api
    cleanup_status=$?
    set -e
    printf 'observe=%s cleanup=%s waits=%s signals=%s stops=%s recorded=%s pending=%s pid=%s\n' \
      "$observe_status" "$cleanup_status" "$wait_calls" "$signal_calls" "$stop_calls" "$recorded_statuses" \
      "${{PROCESS_PENDING_EXIT_STATUS[api]:-}}" "${{PROCESS_PIDS[api]:-}}"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode == 0, completed.stderr
    assert "observe=91 cleanup=0 waits=1 signals=0 stops=0 recorded=17,17, pending= pid=" in completed.stdout


def _run_powershell_probe(body: str) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", body],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _bash_runtime_harness(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "runtime-repo"
    scripts = repo / "scripts"
    fake_bin = repo / "fake-bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(BASH_SCRIPT, scripts / BASH_SCRIPT.name)
    shutil.copy2(RUNTIME_LOG_SUPERVISOR, scripts / RUNTIME_LOG_SUPERVISOR.name)
    (repo / ".deps").mkdir()
    (repo / ".deps/node-env.sh").write_text("", encoding="utf-8")
    turbo = repo / "frontend/original-ui/node_modules/.bin/turbo"
    turbo.parent.mkdir(parents=True)
    _write_executable(turbo, "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        scripts / "run_original_ui_vss.sh",
        """
        #!/usr/bin/env bash
        echo 'ui ready'
        trap 'exit 0' TERM INT
        while :; do sleep 0.1; done
        """,
    )
    (repo / "config.yaml").write_text(
        """search:\n  enabled: false\nrecorded_video:\n  enabled: true\n  data_root: .runtime/recorded-video\n""",
        encoding="utf-8",
    )
    (scripts / "runtime-doctor.py").write_text(
        """
import os
from pathlib import Path
import sys

with Path(os.environ["HARNESS_TRACE"]).open("a", encoding="utf-8") as stream:
    stream.write(f"doctor={' '.join(sys.argv)}\\n")
    stream.write(f"doctor_key_loaded={'yes' if os.environ.get('PROBE_CANARY_API_KEY') else 'no'}\\n")
print("api_key=doctor-secret")
raise SystemExit(int(os.environ.get("HARNESS_DOCTOR_STATUS", "0")))
""".lstrip(),
        encoding="utf-8",
    )
    _write_executable(
        fake_bin / "lsof",
        """
        #!/usr/bin/env bash
        if [[ -n "${HARNESS_FOREIGN_PID:-}" ]]; then printf '%s\n' "$HARNESS_FOREIGN_PID"; fi
        """,
    )
    _write_executable(fake_bin / "npm", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "docker",
        """
        #!/usr/bin/env bash
        printf 'docker=%s\n' "$*" >>"$HARNESS_TRACE"
        if [[ "$1" == "inspect" && "$*" == *State.Running* ]]; then echo true; exit 0; fi
        if [[ "$1" == "inspect" && "$*" == *State.Pid* ]]; then echo 987654; exit 0; fi
        if [[ "$1" == "compose" && "$*" == *"logs"* ]]; then
          echo 'Authorization: Bearer es-secret'
          if [[ -n "${HARNESS_ES_LOG_EXIT_STATUS:-}" ]]; then exit "$HARNESS_ES_LOG_EXIT_STATUS"; fi
          if [[ -n "${HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE:-}" ]]; then
            : >"${HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE}.ready"
            while [[ ! -e "${HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE}.smoke-complete" ]]; do sleep 0.01; done
            exit "${HARNESS_ES_LOG_SMOKE_BOUNDARY_STATUS:-19}"
          fi
          trap 'exit 0' TERM INT
          while :; do sleep 0.1; done
        fi
        exit 0
        """,
    )
    _write_executable(
        fake_bin / "curl",
        """
        #!/usr/bin/env bash
        printf 'curl=%s\n' "$*" >>"$HARNESS_TRACE"
        if [[ "$*" == *"-X DELETE"* ]]; then
          if [[ -n "${HARNESS_DELETE_GATE:-}" && ! -e "${HARNESS_DELETE_GATE}.ready" ]]; then
            : >"${HARNESS_DELETE_GATE}.ready"
            while [[ ! -e "${HARNESS_DELETE_GATE}.release" ]]; do sleep 0.01; done
          fi
          if [[ "${HARNESS_DELETE_FAIL:-0}" == "1" ]]; then exit 22; fi
          exit 0
        fi
        if [[ "$*" == *"/api/v1/search"* ]]; then
          printf 'proxy=ready\n' >>"$HARNESS_TRACE"
          printf '405'
          exit 0
        fi
        if [[ "$*" == *"/_alias/validation-"* ]]; then
          url="${@: -1}"
          alias="${url##*/}"
          printf '{"%s-contract-v1":{"aliases":{"%s":{"is_write_index":true}}}}\n' "$alias" "$alias"
          exit 0
        fi
        if [[ "$*" == *"/_cat/indices/validation-"* ]]; then
          url="${@: -1}"
          alias="${url##*/indices/}"
          alias="${alias%-*?h=index}"
          printf '%s-contract-v1\n' "$alias"
          exit 0
        fi
        if [[ "$*" == *"/health"* ]]; then printf '{"status":"ok"}\n'; else printf '{}\n'; fi
        """,
    )
    _write_executable(
        fake_bin / "python",
        """
        #!/usr/bin/env bash
        if [[ "$1" == "-" ]]; then
          probe="$(mktemp)"
          cat >"$probe"
          if grep -q 'elasticsearch\\[async\\]>=8.14' "$probe"; then rm -f "$probe"; exit 0; fi
          if grep -q 'payload = json.loads(path.read_text' "$probe" \
            && [[ -n "${HARNESS_MANIFEST_FAILURE_GATE:-}" ]] \
            && [[ -e "$HARNESS_MANIFEST_FAILURE_GATE" ]]; then
            printf 'manifest_update_failed=1\n' >>"$HARNESS_TRACE"
            rm -f "$probe"
            exit 91
          fi
          "$REAL_PYTHON" "$@" <"$probe"
          status=$?
          rm -f "$probe"
          exit "$status"
        fi
        if [[ "$1" == "-c" ]]; then exec "$REAL_PYTHON" "$@"; fi
        if [[ "$1" == "scripts/runtime-doctor.py" ]]; then
          printf 'doctor=%s\n' "$*" >>"$HARNESS_TRACE"
          printf 'doctor_key_loaded=%s\n' "${PROBE_CANARY_API_KEY:+yes}" >>"$HARNESS_TRACE"
          echo 'api_key=doctor-secret'
          exit "${HARNESS_DOCTOR_STATUS:-0}"
        fi
        if [[ "$1" == "scripts/recorded-video-bootstrap-index.py" ]]; then
          printf 'bootstrap=%s\n' "$*" >>"$HARNESS_TRACE"
          printf '{"alias":"validation-alias","created_alias":true}\n'
          exit 0
        fi
        if [[ "$1" == "-m" && "$2" == "uvicorn" ]]; then
          printf 'api_config=%s\n' "$VSA_CONFIG" >>"$HARNESS_TRACE"
          printf 'api_pid=%s\n' "$$" >>"$HARNESS_TRACE"
          echo 'Authorization: Bearer api-secret'
          trap 'exit 0' TERM INT
          if [[ -n "${HARNESS_API_EXIT_TRIGGER:-}" ]]; then
            while [[ ! -e "$HARNESS_API_EXIT_TRIGGER" ]]; do sleep 0.01; done
            "$REAL_PYTHON" -c \
              'import sys; sys.stdout.write(("api drain payload=" + "x" * 96 + "\\n") * int(sys.argv[1]))' \
              "${HARNESS_API_DRAIN_LINES:-0}"
            exit 17
          fi
          if [[ -n "${HARNESS_API_EXIT_AFTER:-}" ]]; then
            sleep "$HARNESS_API_EXIT_AFTER"
            exit 17
          fi
          while :; do sleep 0.1; done
        fi
        if [[ "$1" == "scripts/recorded-video-worker.py" ]]; then
          shift
          [[ "$1" == "--config" ]]
          printf 'worker_config=%s\n' "$2" >>"$HARNESS_TRACE"
          printf 'worker_pid=%s\n' "$$" >>"$HARNESS_TRACE"
          cp "$2" "$HARNESS_TRACE.config"
          grep -E 'embed_index:|data_root:|enabled:' "$2" | tr '\n' '|' >>"$HARNESS_TRACE"
          printf '\n' >>"$HARNESS_TRACE"
          data_root="$(sed -n 's/^  data_root: //p' "$2" | tr -d '"')"
          mkdir -p "$data_root"
          printf 'ready' >"$data_root/interruption-ready.marker"
          if [[ "${HARNESS_WORKER_READY:-1}" != "1" ]]; then exit 7; fi
          printf '%s\n' \
            '{"event":"worker.readiness","ready":true,"token":"worker-secret","image":"data:image/jpeg;base64,QUJDREVGR0g="}'
          trap 'exit 0' TERM INT
          while :; do sleep 0.1; done
        fi
        if [[ "$1" == "scripts/es_ingest_smoke.py" ]]; then
          printf 'smoke=%s\n' "$*" >>"$HARNESS_TRACE"
          printf 'smoke_pid=%s\n' "$$" >>"$HARNESS_TRACE"
          if [[ -n "${HARNESS_SMOKE_SLEEP:-}" ]]; then sleep "$HARNESS_SMOKE_SLEEP"; fi
          if [[ -n "${HARNESS_SMOKE_GATE:-}" ]]; then
            : >"${HARNESS_SMOKE_GATE}.ready"
            while [[ ! -e "${HARNESS_SMOKE_GATE}.release" ]]; do sleep 0.01; done
          fi
          if [[ -n "${HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE:-}" ]]; then
            : >"${HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE}.smoke-complete"
            es_status_file="$(dirname "$VSA_CONFIG")/es.status.json"
            while ! "$REAL_PYTHON" -c \
              'import json,sys; p=json.load(open(sys.argv[1],encoding="utf-8")); sys.exit(p["state"]!="exited")' \
              "$es_status_file" 2>/dev/null; do
              sleep 0.01
            done
          fi
          exit "${HARNESS_SMOKE_STATUS:-0}"
        fi
        exec "$REAL_PYTHON" "$@"
        """,
    )
    trace = repo / "trace.log"
    env = os.environ.copy()
    bash = shutil.which("bash")
    assert bash is not None

    def as_bash_path(path: Path) -> str:
        return subprocess.run(
            [bash, "-lc", 'cygpath -u "$1"', "bash", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    bash_path = subprocess.run(
        [bash, "-lc", "printf '%s' \"$PATH\""],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    fake_bin_bash = as_bash_path(fake_bin)
    bash_env = repo / "harness-env.sh"
    bash_env.write_text(
        f"""
export PATH="{fake_bin_bash}:$PATH"
if [[ -n "${{HARNESS_DEFINE_CONDA_FUNCTION:-}}" ]]; then
  conda() {{
    printf 'conda_function=%s\\n' "$*" >>"$HARNESS_TRACE"
    [[ "$1" == "run" ]] && shift
    [[ "${{1:-}}" == "--no-capture-output" ]] && shift
    if [[ "${{1:-}}" == "-n" ]]; then shift 2; fi
    if [[ "${{1:-}}" == "python" && "${{2:-}}" == "-c" && "${{3:-}}" == *"sys.executable"* ]]; then
      printf '%s\n' "$HARNESS_CONDA_PYTHON"
      return 0
    fi
    "$@"
  }}
fi
hash -r
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )
    env.update(
        {
            "PATH": f"{fake_bin_bash}:{bash_path}",
            "BASH_ENV": as_bash_path(bash_env),
            "REAL_PYTHON": as_bash_path(Path(sys.executable)),
            "VSA_SUPERVISOR_PYTHON": as_bash_path(Path(sys.executable)),
            "HARNESS_TRACE": as_bash_path(trace),
            "HARNESS_CONDA_PYTHON": f"{fake_bin_bash}/python",
        }
    )
    return repo, env


def test_bash_runtime_harness_fake_api_drain_emits_requested_lines(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    api_exit_trigger = tmp_path / "api-exit.trigger"
    api_exit_trigger.touch()
    env["HARNESS_API_EXIT_TRIGGER"] = api_exit_trigger.as_posix()
    env["HARNESS_API_DRAIN_LINES"] = "3"
    bash = shutil.which("bash")
    assert bash is not None

    completed = subprocess.run(
        [bash, (repo / "fake-bin/python").as_posix(), "-m", "uvicorn"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 17, completed.stderr
    assert completed.stdout.count("api drain payload=") == 3


def _run_bash_runtime(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    return _run_runtime_command(
        [_real_bash_path(bash), (repo / "scripts/es-runtime-stack.sh").as_posix(), *args],
        cwd=repo,
        env=env,
        timeout=BASH_RUNTIME_READINESS_TIMEOUT_SEC,
    )


@pytest.mark.parametrize("doctor_status", [0, 3])
def test_bash_provider_probe_propagates_status_without_starting_stack(tmp_path: Path, doctor_status: int):
    repo, env = _bash_runtime_harness(tmp_path)
    secrets = repo / "secrets.env"
    secrets.write_text("PROBE_CANARY_API_KEY=canary-secret\n", encoding="utf-8", newline="\n")
    secrets.chmod(0o600)
    env["HARNESS_DOCTOR_STATUS"] = str(doctor_status)

    completed = _run_bash_runtime(
        repo,
        env,
        "--config",
        "config.yaml",
        "--secrets-file",
        secrets.as_posix(),
        "--probe-providers",
    )

    assert completed.returncode == doctor_status, completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "doctor=scripts/runtime-doctor.py --config" in trace
    assert "--probe-providers --json" in trace
    assert "doctor_key_loaded=yes" in trace
    assert "docker=" not in trace
    assert "curl=" not in trace
    assert "bootstrap=" not in trace
    assert "api_config=" not in trace
    assert "worker_config=" not in trace
    assert "smoke=" not in trace
    assert not (repo / ".runtime/recorded-video").exists()
    assert "canary-secret" not in completed.stdout
    assert "canary-secret" not in completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="regression covers Windows runtime tree cleanup")
def test_bash_runtime_reclaims_pipe_holding_descendant_after_root_exit(tmp_path: Path):
    repo = tmp_path / "runtime-job-root-exit"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    result = tmp_path / "runtime-job-result.json"
    ready = tmp_path / "runtime-job-runner.ready"
    release = tmp_path / "runtime-job-runner.release"
    runner = tmp_path / "runtime-job-runner.py"
    token = f"bash-runtime-job-owned-descendant-{tmp_path.name}"
    python = shlex.quote(Path(sys.executable).as_posix())
    child_code = (
        'from pathlib import Path; import time; Path("runtime-child.ready").write_text("ready"); time.sleep(30)'
    )
    child_command = f"{python} -c {shlex.quote(child_code)} {shlex.quote(token)} &"
    _write_executable(
        scripts / "es-runtime-stack.sh",
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            printf '%s' "$HARNESS_JOB_VALUE" > runtime-job-contract.txt
            printf 'runtime-job-stdout\n'
            printf 'runtime-job-stderr\n' >&2
            {child_command}
            for _ in {{1..20}}; do
              [[ -f runtime-child.ready ]] && break
              sleep 0.01
            done
            [[ -f runtime-child.ready ]] || exit 91
            for _ in {{1..120}}; do
              [[ -f runtime-child.observed ]] && break
              sleep 0.05
            done
            [[ -f runtime-child.observed ]] || exit 92
            exit 0
            """
        ).lstrip(),
    )
    runner.write_text(
        textwrap.dedent(
            """
            import json
            import os
            from pathlib import Path
            import runpy
            import subprocess
            import sys
            import time

            test_path, repo_path, result_path, ready_path, release_path, _token = sys.argv[1:]
            namespace = runpy.run_path(test_path)
            helper = namespace["_run_bash_runtime"]
            real_snapshot = namespace["_powershell_process_snapshot"]
            observed_path = Path(repo_path) / "runtime-child.observed"

            def observing_snapshot():
                snapshot = real_snapshot()
                if any(
                    _token in str(item["command_line"] or "")
                    and "time.sleep(30)" in str(item["command_line"] or "")
                    for item in snapshot
                ):
                    observed_path.write_text("observed", encoding="utf-8")
                return snapshot

            helper.__globals__["_powershell_process_snapshot"] = observing_snapshot
            helper.__globals__["BASH_RUNTIME_READINESS_TIMEOUT_SEC"] = 8.0
            helper.__globals__["RUNTIME_TREE_OBSERVATION_INTERVAL_SEC"] = 0.05
            Path(ready_path).write_text("ready", encoding="utf-8")
            while not Path(release_path).exists():
                time.sleep(0.01)
            env = os.environ.copy()
            env["HARNESS_JOB_VALUE"] = "cwd-and-env-preserved"
            try:
                completed = helper(Path(repo_path), env)
            except subprocess.TimeoutExpired:
                payload = {"kind": "timeout"}
            except BaseException as error:
                payload = {"kind": "error", "error": repr(error)}
            else:
                payload = {
                    "kind": "completed",
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            Path(result_path).write_text(json.dumps(payload), encoding="utf-8")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(runner),
        str(Path(__file__).resolve()),
        str(repo),
        str(result),
        str(ready),
        str(release),
        token,
    ]
    registry: dict[str, dict[str, object]] = {}
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    def observe_owned_tree() -> list[dict[str, object]]:
        snapshot = _powershell_process_snapshot()
        if not registry:
            root = next((item for item in snapshot if int(item["pid"]) == process.pid), None)
            if root is not None:
                _register_powershell_root_identity(registry, root)
        _record_owned_powershell_descendants(registry, snapshot)
        return snapshot

    try:
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            observe_owned_tree()
            time.sleep(0.02)
        assert ready.exists()
        assert registry
        release.touch()

        deadline = time.monotonic() + 12
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        snapshot = observe_owned_tree()

        assert process.poll() is not None, "_run_bash_runtime remained blocked on descendant pipe EOF"
        payload = json.loads(result.read_text(encoding="utf-8"))
        assert payload == {
            "kind": "completed",
            "returncode": 0,
            "stdout": "runtime-job-stdout\n",
            "stderr": "runtime-job-stderr\n",
        }
        assert (repo / "runtime-job-contract.txt").read_text(encoding="utf-8") == "cwd-and-env-preserved"
        assert (repo / "runtime-child.ready").read_text(encoding="utf-8") == "ready"
        assert (repo / "runtime-child.observed").read_text(encoding="utf-8") == "observed"
        assert _current_registered_powershell_processes(registry, snapshot) == []
        assert [item for item in snapshot if token in str(item["command_line"] or "")] == []
    finally:
        active_error = sys.exception()
        cleanup_errors: list[str] = []

        def cleanup_stage(name: str, action) -> None:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(f"{name}: {error!r}")

        def refresh_registry() -> None:
            observe_owned_tree()

        def terminate_registered_tree() -> None:
            _terminate_exact_powershell_processes(list(registry.values()))

        def terminate_token_fallback() -> None:
            snapshot = _powershell_process_snapshot()
            token_processes = [item for item in snapshot if token in str(item["command_line"] or "")]
            _terminate_exact_powershell_processes(token_processes)

        def kill_runner_fallback() -> None:
            if process.poll() is None:
                process.kill()

        def verify_no_residuals() -> None:
            snapshot = _powershell_process_snapshot()
            _record_owned_powershell_descendants(registry, snapshot)
            remaining = _current_registered_powershell_processes(registry, snapshot)
            token_processes = [item for item in snapshot if token in str(item["command_line"] or "")]
            if remaining or token_processes:
                raise AssertionError(
                    f"Bash runtime regression left processes: registered={remaining}, token={token_processes}"
                )

        cleanup_stage("final registry refresh", refresh_registry)
        cleanup_stage("registered tree termination", terminate_registered_tree)
        cleanup_stage("token fallback termination", terminate_token_fallback)
        cleanup_stage("runner process-handle fallback", kill_runner_fallback)
        cleanup_stage("runner wait", lambda: process.wait(timeout=5))
        cleanup_stage("final residual verification", verify_no_residuals)
        if cleanup_errors:
            details = "Bash runtime regression cleanup failed: " + "; ".join(cleanup_errors)
            if active_error is not None:
                active_error.add_note(details)
            else:
                raise AssertionError(details)


def _wait_for_bash_pids_gone(
    bash: str,
    repo: Path,
    env: dict[str, str],
    pids: list[int],
    *,
    timeout: float = 3.0,
) -> list[int]:
    deadline = time.monotonic() + timeout
    survivors = pids
    while survivors and time.monotonic() < deadline:
        probe = subprocess.run(
            [
                bash,
                "-c",
                'for pid in "$@"; do kill -0 "$pid" 2>/dev/null && printf "%s\\n" "$pid"; done',
                "bash",
                *map(str, survivors),
            ],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        survivors = [int(pid) for pid in probe.stdout.splitlines() if pid]
        if survivors:
            time.sleep(0.05)
    return survivors


def _kill_bash_pids(bash: str, repo: Path, env: dict[str, str], pids: list[int]) -> None:
    if not pids:
        return
    subprocess.run(
        [bash, "-c", 'for pid in "$@"; do kill -KILL "$pid" 2>/dev/null || true; done', "bash", *map(str, pids)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _terminate_bash_launcher_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def _powershell_runtime_harness(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "powershell-runtime-repo"
    scripts = repo / "scripts"
    fake_bin = repo / "fake-bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(POWERSHELL_SCRIPT, scripts / POWERSHELL_SCRIPT.name)
    (scripts / "lib").mkdir()
    shutil.copy2(POWERSHELL_LOG_PUMP, scripts / "lib" / POWERSHELL_LOG_PUMP.name)
    (repo / ".deps").mkdir()
    (repo / ".deps/node-env.sh").write_text("", encoding="utf-8")
    turbo = repo / "frontend/original-ui/node_modules/.bin/turbo"
    turbo.parent.mkdir(parents=True)
    _write_executable(turbo, "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(scripts / "bootstrap_node.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        scripts / "run_original_ui_vss.sh",
        """
        #!/usr/bin/env bash
        while :; do sleep 0.1; done
        """,
    )
    (repo / "config.yaml").write_text(
        """search:\n  enabled: false\nrecorded_video:\n  enabled: true\n  data_root: .runtime/recorded-video\n""",
        encoding="utf-8",
    )
    (scripts / "es-dev-start.ps1").write_text("& docker compose up | Out-Null\n", encoding="utf-8")
    (scripts / "es-dev-stop.ps1").write_text("& docker compose down | Out-Null\n", encoding="utf-8")
    fake_runtime = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys
        import time

        trace = Path(os.environ["HARNESS_TRACE"])
        with trace.open("a", encoding="utf-8") as stream:
            stream.write(f"{Path(sys.argv[0]).name}={' '.join(sys.argv[1:])}\\n")
        """
    )
    (repo / "inspect").write_text(fake_runtime + "print('true')\n", encoding="utf-8")
    (repo / "compose").write_text(fake_runtime + "if 'logs' in sys.argv:\n    time.sleep(3600)\n", encoding="utf-8")
    shutil.copy2(Path(sys.executable), fake_bin / "docker.exe")
    (repo / "uvicorn.py").write_text(
        fake_runtime
        + """
with trace.open("a", encoding="utf-8") as stream:
    stream.write(f"api_config={os.environ.get('VSA_CONFIG', '')}\\n")
if os.environ.get("HARNESS_DETACHED_CHILD") == "1":
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    with trace.open("a", encoding="utf-8") as stream:
        stream.write(f"detached_child_pid={child.pid}\\n")
    registration_deadline = time.monotonic() + 10
    while time.monotonic() < registration_deadline:
        stack_logs = list((trace.parent / ".runtime/es-stack/runs").glob("*/stack.log"))
        if os.environ.get("HARNESS_FORCE_TRACKER_TIMEOUT") != "1" and any(
            f"process tracker registered component=api pid={child.pid} "
            in stack_log.read_text(encoding="utf-8", errors="replace")
            for stack_log in stack_logs
        ):
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(f"detached_child_registered_by_launcher={child.pid}\\n")
            break
        time.sleep(0.05)
    else:
        with trace.open("a", encoding="utf-8") as stream:
            stream.write(f"detached_child_launcher_registration_timeout={child.pid}\\n")
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        raise SystemExit(18)
    raise SystemExit(17)
delay = int(os.environ.get("HARNESS_API_EXIT_AFTER_MS", "0"))
if delay:
    time.sleep(delay / 1000)
    raise SystemExit(17)
exit_trigger = os.environ.get("HARNESS_API_EXIT_TRIGGER")
if exit_trigger:
    while not Path(exit_trigger).exists():
        time.sleep(0.05)
    raise SystemExit(17)
time.sleep(3600)
""",
        encoding="utf-8",
    )
    (scripts / "runtime-doctor.py").write_text(
        fake_runtime
        + """
with trace.open("a", encoding="utf-8") as stream:
    stream.write(f"doctor_key_loaded={'yes' if os.environ.get('PROBE_CANARY_API_KEY') else 'no'}\\n")
print('api_key=doctor-secret')
raise SystemExit(int(os.environ.get("HARNESS_DOCTOR_STATUS", "0")))
""",
        encoding="utf-8",
    )
    (scripts / "recorded-video-worker.py").write_text(
        fake_runtime
        + """
config = Path(sys.argv[sys.argv.index("--config") + 1])
with trace.open("a", encoding="utf-8") as stream:
    stream.write(f"worker_config={config}\\n")
data_root_line = next(
    line for line in config.read_text(encoding="utf-8").splitlines() if line.startswith("  data_root:")
)
validation_root = Path(json.loads(data_root_line.split(":", 1)[1].strip()))
validation_root.mkdir(parents=True, exist_ok=True)
(validation_root / "interruption-ready.marker").write_text("ready", encoding="utf-8")
if os.environ.get("HARNESS_WORKER_READY") == "0":
    raise SystemExit(7)
(config.parent / "worker.log").write_text(
    json.dumps({"event": "worker.readiness", "ready": True}) + "\\n",
    encoding="utf-8",
)
time.sleep(3600)
""",
        encoding="utf-8",
    )
    (scripts / "es_ingest_smoke.py").write_text(
        fake_runtime
        + """
with trace.open("a", encoding="utf-8") as stream:
    stream.write(f"smoke={' '.join(sys.argv[1:])}\\n")
smoke_index = sys.argv[sys.argv.index("--index") + 1]
validation_index = smoke_index.removesuffix("-legacy-smoke")
validation_root = Path(os.environ["VSA_CONFIG"]).parent / validation_index
validation_root.mkdir(parents=True, exist_ok=True)
(validation_root / "interruption-ready.marker").write_text("ready", encoding="utf-8")
time.sleep(int(os.environ.get("HARNESS_SMOKE_SLEEP_MS", "0")) / 1000)
raise SystemExit(int(os.environ.get("HARNESS_SMOKE_STATUS", "0")))
""",
        encoding="utf-8",
    )
    trace = repo / "trace.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "HARNESS_TRACE": str(trace),
        }
    )
    return repo, env


def _powershell_process_snapshot() -> list[dict[str, object]]:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    probe = """
    Get-CimInstance Win32_Process | ForEach-Object {
        [pscustomobject]@{
            pid = [int]$_.ProcessId
            parent_pid = [int]$_.ParentProcessId
            creation = $_.CreationDate.ToUniversalTime().ToString('o')
            executable_path = [string]$_.ExecutablePath
            command_line = [string]$_.CommandLine
        } | ConvertTo-Json -Compress
    }
    """
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def _powershell_identity_key(item: dict[str, object]) -> str:
    return f"{int(item['pid'])}|{item['creation']}"


def _same_powershell_process_identity(left: dict[str, object], right: dict[str, object]) -> bool:
    return all(
        left[field] == right[field] for field in ("pid", "parent_pid", "creation", "executable_path", "command_line")
    )


def _powershell_registry_path(repo: Path) -> Path:
    return repo / "harness-owned-processes.json"


def _load_powershell_process_registry(repo: Path) -> dict[str, dict[str, object]]:
    path = _powershell_registry_path(repo)
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    return {_powershell_identity_key(item): item for item in records}


def _persist_powershell_process_registry(repo: Path, registry: dict[str, dict[str, object]]) -> None:
    records = sorted(registry.values(), key=lambda item: (str(item["creation"]), int(item["pid"])))
    _powershell_registry_path(repo).write_text(json.dumps(records, indent=2), encoding="utf-8")


def _register_powershell_root_identity(
    registry: dict[str, dict[str, object]], root_identity: dict[str, object]
) -> None:
    record = dict(root_identity)
    record["lineage"] = [{"pid": int(record["pid"]), "creation": str(record["creation"])}]
    registry[_powershell_identity_key(record)] = record


def _record_owned_powershell_descendants(
    registry: dict[str, dict[str, object]], snapshot: list[dict[str, object]]
) -> None:
    current_by_pid = {int(item["pid"]): item for item in snapshot}
    while True:
        added = False
        for child in snapshot:
            child_key = _powershell_identity_key(child)
            if child_key in registry:
                continue
            parent_pid = int(child["parent_pid"])
            parents = [
                item
                for item in registry.values()
                if int(item["pid"]) == parent_pid and str(child["creation"]) >= str(item["creation"])
            ]
            if not parents:
                continue
            current_parent = current_by_pid.get(parent_pid)
            if current_parent is None:
                continue
            parents = [item for item in parents if _same_powershell_process_identity(item, current_parent)]
            if not parents:
                continue
            parent = max(parents, key=lambda item: str(item["creation"]))
            record = dict(child)
            record["lineage"] = [
                *list(parent["lineage"]),
                {"pid": int(record["pid"]), "creation": str(record["creation"])},
            ]
            registry[child_key] = record
            added = True
        if not added:
            return


def _current_registered_powershell_processes(
    registry: dict[str, dict[str, object]], snapshot: list[dict[str, object]]
) -> list[dict[str, object]]:
    registered = {_powershell_identity_key(item): item for item in registry.values()}
    return [
        item
        for item in snapshot
        if (record := registered.get(_powershell_identity_key(item))) is not None
        and _same_powershell_process_identity(record, item)
    ]


def _powershell_repo_processes(repo: Path) -> list[dict[str, object]]:
    snapshot = _powershell_process_snapshot()
    registry = _load_powershell_process_registry(repo)
    if registry:
        _record_owned_powershell_descendants(registry, snapshot)
        _persist_powershell_process_registry(repo, registry)
        return _current_registered_powershell_processes(registry, snapshot)

    needle = str(repo.resolve()).casefold()
    roots = [item for item in snapshot if needle in str(item["command_line"] or "").casefold()]
    for root in roots:
        _register_powershell_root_identity(registry, root)
    _record_owned_powershell_descendants(registry, snapshot)
    if registry:
        _persist_powershell_process_registry(repo, registry)
    return _current_registered_powershell_processes(registry, snapshot)


def _terminate_exact_powershell_processes(processes: list[dict[str, object]]) -> None:
    if not processes:
        return
    powershell = shutil.which("powershell")
    assert powershell is not None
    by_pid = {int(item["pid"]): item for item in processes}

    def lineage_depth(item: dict[str, object]) -> int:
        depth = 0
        parent_pid = int(item["parent_pid"])
        seen: set[int] = set()
        while parent_pid in by_pid and parent_pid not in seen:
            seen.add(parent_pid)
            depth += 1
            parent_pid = int(by_pid[parent_pid]["parent_pid"])
        return depth

    deepest_first = sorted(processes, key=lineage_depth, reverse=True)
    probe = """
    $records = [Console]::In.ReadToEnd() | ConvertFrom-Json
    foreach ($record in @($records)) {
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)" -ErrorAction SilentlyContinue
        if ($null -eq $current) { continue }
        $creation = $current.CreationDate.ToUniversalTime().ToString('o')
        if ($creation -ne $record.creation) { continue }
        if ([int]$current.ParentProcessId -ne [int]$record.parent_pid) { continue }
        if ([string]$current.ExecutablePath -cne [string]$record.executable_path) { continue }
        if ([string]$current.CommandLine -cne [string]$record.command_line) { continue }
        Stop-Process -Id $record.pid -Force -ErrorAction SilentlyContinue
    }
    """
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
        input=json.dumps(deepest_first),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


def test_powershell_process_snapshot_parses_one_json_record_per_nonempty_line(
    monkeypatch: pytest.MonkeyPatch,
):
    records = [
        {
            "pid": 101,
            "parent_pid": 1,
            "creation": "2026-07-19T00:00:00.0000000Z",
            "executable_path": r"C:\fake\root.exe",
            "command_line": "root --serve",
        },
        {
            "pid": 202,
            "parent_pid": 101,
            "creation": "2026-07-19T00:00:01.0000000Z",
            "executable_path": r"C:\fake\bash.exe",
            "command_line": "bash child.sh",
        },
    ]
    stdout = "\n".join((json.dumps(records[0]), "", json.dumps(records[1]), ""))
    completed = subprocess.CompletedProcess(["powershell"], 0, stdout, "")

    monkeypatch.setattr(shutil, "which", lambda name: "powershell" if name == "powershell" else None)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: completed)

    assert _powershell_process_snapshot() == records


class _FakeBashProbeStdin:
    def write(self, _value: str) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.mark.skipif(os.name != "nt", reason="regression covers Windows runtime snapshot throttling")
def test_runtime_runner_throttles_active_process_snapshots(monkeypatch: pytest.MonkeyPatch):
    class FakeProcess:
        pid = 901

        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stdin: _FakeBashProbeStdin | None = _FakeBashProbeStdin()
            self.communicate_calls = 0

        def poll(self) -> int | None:
            return self.returncode

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            self.communicate_calls += 1
            if self.communicate_calls <= 5:
                raise subprocess.TimeoutExpired(["fake-runtime"], timeout)
            self.returncode = 0
            return "runtime-stdout", "runtime-stderr"

        def kill(self) -> None:
            raise AssertionError("completed fake runtime must not be killed")

    process = FakeProcess()
    root_identity = {
        "pid": process.pid,
        "parent_pid": 1,
        "creation": "2026-07-19T06:00:00.0000000Z",
        "executable_path": "C:\\fake\\python.exe",
        "command_line": "fake-runtime-shim",
    }
    snapshot_calls = 0
    clock = 0.0

    def fake_snapshot() -> list[dict[str, object]]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return [root_identity] if process.returncode is None else []

    def fake_monotonic() -> float:
        nonlocal clock
        clock += 0.1
        return clock

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(sys.modules[__name__], "_powershell_process_snapshot", fake_snapshot)
    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    completed = _run_runtime_command(["fake-runtime"], timeout=10)

    assert completed.args == ["fake-runtime"]
    assert completed.returncode == 0
    assert completed.stdout == "runtime-stdout"
    assert completed.stderr == "runtime-stderr"
    assert snapshot_calls == 4


@pytest.mark.skipif(os.name != "nt", reason="regression covers Windows Job cleanup")
def test_bash_probe_job_fallback_closes_handle_after_terminate_failure(monkeypatch: pytest.MonkeyPatch):
    class FakeJobApi:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def AssignProcessToJobObject(self, job_handle: int, process_handle: int) -> bool:  # noqa: N802
            self.calls.append(("assign", job_handle, process_handle))
            return True

        def CloseHandle(self, job_handle: int) -> bool:  # noqa: N802
            self.calls.append(("close", job_handle))
            return False

        def TerminateJobObject(self, job_handle: int, status: int) -> bool:  # noqa: N802
            self.calls.append(("terminate", job_handle, status))
            return False

    class FakeProcess:
        _handle = 101
        returncode = 0
        stdin: _FakeBashProbeStdin | None = _FakeBashProbeStdin()

        def poll(self) -> int:
            return 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            return "", ""

        def kill(self) -> None:
            raise AssertionError("completed fake process must not be killed")

    job_api = FakeJobApi()
    process = FakeProcess()
    monkeypatch.setattr(sys.modules[__name__], "_create_windows_kill_on_close_job", lambda: (job_api, 77))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(AssertionError) as caught:
        _run_bash_probe("exit 0")

    assert job_api.calls == [
        ("assign", 77, 101),
        ("close", 77),
        ("terminate", 77, 1),
        ("close", 77),
    ]
    assert "TerminateJobObject failed" in str(caught.value)
    assert "CloseHandle failed" in str(caught.value)


@pytest.mark.skipif(os.name != "nt", reason="regression covers Windows timeout output")
@pytest.mark.parametrize(
    ("drain_stdout", "drain_stderr", "expected_stdout", "expected_stderr"),
    [
        pytest.param(
            "drain-partial-stdout",
            "drain-partial-stderr",
            "drain-partial-stdout",
            "drain-partial-stderr",
            id="final-drain-overrides-polling",
        ),
        pytest.param(
            None,
            None,
            "poll-partial-stdout",
            "poll-partial-stderr",
            id="polling-retained-with-empty-final-drain",
        ),
    ],
)
def test_bash_probe_timeout_preserves_latest_partial_output_when_final_drain_times_out(
    monkeypatch: pytest.MonkeyPatch,
    drain_stdout: str | None,
    drain_stderr: str | None,
    expected_stdout: str,
    expected_stderr: str,
):
    class FakeJobApi:
        def AssignProcessToJobObject(self, _job_handle: int, _process_handle: int) -> bool:  # noqa: N802
            return True

        def CloseHandle(self, _job_handle: int) -> bool:  # noqa: N802
            return True

        def TerminateJobObject(self, _job_handle: int, _status: int) -> bool:  # noqa: N802
            raise AssertionError("successful close must not use termination fallback")

    class FakeProcess:
        _handle = 102

        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stdin: _FakeBashProbeStdin | None = _FakeBashProbeStdin()
            self.communicate_calls = 0

        def poll(self) -> int | None:
            return self.returncode

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(
                    ["fake-shim"],
                    timeout,
                    output="poll-partial-stdout",
                    stderr="poll-partial-stderr",
                )
            raise subprocess.TimeoutExpired(
                ["fake-shim"],
                timeout,
                output=drain_stdout,
                stderr=drain_stderr,
            )

        def kill(self) -> None:
            self.returncode = -9

    process = FakeProcess()
    times = iter((0.0, 0.1, 1.0))
    monkeypatch.setattr(sys.modules[__name__], "_create_windows_kill_on_close_job", lambda: (FakeJobApi(), 78))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(time, "monotonic", lambda: next(times))

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _run_bash_probe("while :; do sleep 0.1; done", timeout=0.5)

    assert caught.value.output == expected_stdout
    assert caught.value.stderr == expected_stderr
    assert any("stdout/stderr drain" in note for note in caught.value.__notes__)


@pytest.mark.skipif(os.name != "nt", reason="regression covers Windows timeout cleanup")
def test_bash_probe_timeout_reclaims_its_owned_descendant(tmp_path: Path):
    runner = tmp_path / "probe-runner.py"
    ready = tmp_path / "runner.ready"
    release = tmp_path / "runner.release"
    result = tmp_path / "runner.result"
    probe_token = f"bash-probe-owned-descendant-{tmp_path.name}"
    runner.write_text(
        textwrap.dedent(
            """
            from pathlib import Path
            import runpy
            import subprocess
            import sys
            import time

            test_path, body, ready_path, release_path, result_path, _token = sys.argv[1:]
            Path(ready_path).write_text("ready", encoding="utf-8")
            while not Path(release_path).exists():
                time.sleep(0.01)
            helper = runpy.run_path(test_path)["_run_bash_probe"]
            try:
                helper(body, timeout=0.5)
            except subprocess.TimeoutExpired:
                Path(result_path).write_text("timeout", encoding="utf-8")
            else:
                Path(result_path).write_text("returned", encoding="utf-8")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    probe = textwrap.dedent(
        f"""
        owned_probe_token={shlex.quote(probe_token)}
        {shlex.quote(Path(sys.executable).as_posix())} -c 'import time; time.sleep(30)' \
          {shlex.quote(probe_token)} &
        while :; do sleep 0.1; done
        """
    )
    command = [
        sys.executable,
        str(runner),
        str(Path(__file__).resolve()),
        probe,
        str(ready),
        str(release),
        str(result),
        probe_token,
    ]
    registry: dict[str, dict[str, object]] = {}
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    def observe_owned_tree() -> list[dict[str, object]]:
        snapshot = _powershell_process_snapshot()
        if not registry:
            root = next((item for item in snapshot if int(item["pid"]) == process.pid), None)
            if root is not None:
                _register_powershell_root_identity(registry, root)
        _record_owned_powershell_descendants(registry, snapshot)
        return snapshot

    try:
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            observe_owned_tree()
            time.sleep(0.02)
        assert ready.exists()
        assert registry
        release.touch()

        deadline = time.monotonic() + 4
        snapshot: list[dict[str, object]] = []
        while process.poll() is None and time.monotonic() < deadline:
            snapshot = observe_owned_tree()
            time.sleep(0.05)
        snapshot = observe_owned_tree()

        assert process.poll() is not None, "_run_bash_probe remained blocked after its timeout"
        assert result.read_text(encoding="utf-8") == "timeout"
        assert _current_registered_powershell_processes(registry, snapshot) == []
        assert [item for item in snapshot if probe_token in str(item["command_line"] or "")] == []
    finally:
        active_error = sys.exception()
        cleanup_errors: list[str] = []

        def cleanup_stage(name: str, action) -> None:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(f"{name}: {error!r}")

        def refresh_registry() -> None:
            observe_owned_tree()

        def terminate_registered_tree() -> None:
            _terminate_exact_powershell_processes(list(registry.values()))

        def terminate_token_fallback() -> None:
            snapshot = _powershell_process_snapshot()
            token_processes = [item for item in snapshot if probe_token in str(item["command_line"] or "")]
            _terminate_exact_powershell_processes(token_processes)

        def kill_runner_fallback() -> None:
            if process.poll() is None:
                process.kill()

        def verify_no_residuals() -> None:
            snapshot = _powershell_process_snapshot()
            _record_owned_powershell_descendants(registry, snapshot)
            remaining = _current_registered_powershell_processes(registry, snapshot)
            token_processes = [item for item in snapshot if probe_token in str(item["command_line"] or "")]
            if remaining or token_processes:
                raise AssertionError(
                    f"Bash probe regression left owned processes: registered={remaining}, token={token_processes}"
                )

        cleanup_stage("final registry refresh", refresh_registry)
        cleanup_stage("registered tree termination", terminate_registered_tree)
        cleanup_stage("token fallback termination", terminate_token_fallback)
        cleanup_stage("runner process-handle fallback", kill_runner_fallback)
        cleanup_stage("runner wait", lambda: process.wait(timeout=5))
        cleanup_stage("final residual verification", verify_no_residuals)
        if cleanup_errors:
            details = "Bash probe regression cleanup failed: " + "; ".join(cleanup_errors)
            if active_error is not None:
                active_error.add_note(details)
            else:
                raise AssertionError(details)


def _powershell_runtime_diagnostics(repo: Path) -> str:
    sections: list[str] = []
    for path in (
        repo / "trace.log",
        repo / "launcher.stdout.log",
        repo / "launcher.stderr.log",
    ):
        if path.exists():
            sections.append(f"--- {path.name} ---\n{path.read_text(encoding='utf-8', errors='replace')}")
    for stack_log in (repo / ".runtime/es-stack/runs").glob("*/stack.log"):
        contents = stack_log.read_text(encoding="utf-8", errors="replace")
        sections.append(f"--- {stack_log.relative_to(repo)} ---\n{contents}")
    return "\n".join(sections) or "no launcher diagnostics were created"


def _run_powershell_runtime(
    repo: Path,
    env: dict[str, str],
    *args: str,
    timeout: float = 60,
    exit_after_trace: str | None = None,
    exit_after_marker: str | None = None,
    exit_after_stack: str | None = None,
    stop_pipeline_after_trace: bool = False,
) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    launcher_args = " ".join(args)
    launcher = (repo / "scripts/es-runtime-stack.ps1").resolve()
    trace = (repo / "trace.log").resolve()
    launcher_body = repo / "launcher-body.ps1"
    launcher_body.write_text(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            function Get-NetTCPConnection {{ return @() }}
            function Invoke-RestMethod {{ [pscustomobject]@{{ status = 'ok' }} }}
            function Invoke-WebRequest {{
                param($Uri, $Method, $TimeoutSec, [switch]$UseBasicParsing)
                if ($Method -eq 'Delete') {{
                    [IO.File]::AppendAllText('{trace}', "delete=$Uri`n")
                    return [pscustomobject]@{{ StatusCode = 200 }}
                }}
                if ("$Uri" -like '*/api/v1/search') {{
                    [IO.File]::AppendAllText('{trace}', "proxy=ready`n")
                    $exception = [Exception]::new('method not allowed')
                    $response = [pscustomobject]@{{ StatusCode = [pscustomobject]@{{ value__ = 405 }} }}
                    $exception | Add-Member -NotePropertyName Response -NotePropertyValue $response
                    throw $exception
                }}
                return [pscustomobject]@{{ StatusCode = 200 }}
            }}
            & '{launcher}' {launcher_args}
            [IO.File]::AppendAllText(
                '{trace}',
                "wrapper=returned;last=$LASTEXITCODE;env=$([Environment]::ExitCode);errors=$($Error.Count);ok=$?`n"
            )
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    probe = repo / "run-launcher.ps1"
    start_trigger = repo / "harness-start.trigger"
    pipeline_stop_trigger = repo / "pipeline-stop.trigger"
    if stop_pipeline_after_trace:
        probe.write_text(
            textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                while (-not (Test-Path -LiteralPath '{start_trigger}')) {{ Start-Sleep -Milliseconds 10 }}
                $pipeline = [PowerShell]::Create()
                $null = $pipeline.AddScript([IO.File]::ReadAllText('{launcher_body}'))
                $async = $pipeline.BeginInvoke()
                try {{
                    while (-not $async.IsCompleted -and -not (Test-Path -LiteralPath '{pipeline_stop_trigger}')) {{
                        Start-Sleep -Milliseconds 25
                    }}
                    if (Test-Path -LiteralPath '{pipeline_stop_trigger}') {{
                        $pipeline.Stop()
                        try {{ $null = $pipeline.EndInvoke($async) }} catch {{
                            if ($_.Exception.Message -notmatch 'pipeline has been stopped') {{ throw }}
                        }}
                        [IO.File]::AppendAllText('{trace}', "wrapper=pipeline-stopped`n")
                        exit 130
                    }}
                    $output = $pipeline.EndInvoke($async)
                    $output | ForEach-Object {{ [Console]::Out.WriteLine("$_") }}
                    [IO.File]::AppendAllText('{trace}', "wrapper=returned`n")
                    exit 0
                }} catch {{
                    [Console]::Error.WriteLine($_.Exception.Message)
                    [IO.File]::AppendAllText('{trace}', "wrapper=failed`n")
                    exit 1
                }} finally {{
                    $pipeline.Dispose()
                }}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
    else:
        probe.write_text(
            textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                while (-not (Test-Path -LiteralPath '{start_trigger}')) {{ Start-Sleep -Milliseconds 10 }}
                try {{
                    & '{launcher_body}'
                    exit 0
                }} catch {{
                    [Console]::Error.WriteLine($_.Exception.Message)
                    [IO.File]::AppendAllText('{trace}', "wrapper=failed`n")
                    exit 1
                }}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(probe),
    ]
    stdout_path = repo / "launcher.stdout.log"
    stderr_path = repo / "launcher.stderr.log"
    exit_trigger = repo / "api-exit.trigger"
    process_env = env.copy()
    process_env["HARNESS_API_EXIT_TRIGGER"] = str(exit_trigger)
    owned_registry: dict[str, dict[str, object]] = {}
    primary_failure: BaseException | None = None
    diagnostics_text: str | None = None
    diagnostics_error: BaseException | None = None
    start_released = False
    next_observation = 0.0
    process: subprocess.Popen[str]

    def observe_owned_processes() -> None:
        nonlocal next_observation
        now = time.monotonic()
        if now < next_observation:
            return
        snapshot = _powershell_process_snapshot()
        _record_owned_powershell_descendants(owned_registry, snapshot)
        _persist_powershell_process_registry(repo, owned_registry)
        next_observation = time.monotonic() + 0.2

    def wait_with_observation(deadline: float) -> None:
        while process.poll() is None:
            observe_owned_processes()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(min(0.05, remaining))

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=repo,
            env=process_env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            snapshot = _powershell_process_snapshot()
            root_identity = next((item for item in snapshot if int(item["pid"]) == process.pid), None)
            if root_identity is None:
                raise AssertionError(f"Could not capture PowerShell host identity for PID {process.pid}")
            _register_powershell_root_identity(owned_registry, root_identity)
            _record_owned_powershell_descendants(owned_registry, snapshot)
            _persist_powershell_process_registry(repo, owned_registry)
            start_trigger.write_text("start", encoding="utf-8")
            start_released = True
            deadline = time.monotonic() + timeout
            if exit_after_trace is None:
                wait_with_observation(deadline)
            else:
                trace_path = repo / "trace.log"
                trace_ready_at: float | None = None
                while time.monotonic() < deadline:
                    observe_owned_processes()
                    trace_ready = trace_path.exists() and exit_after_trace in trace_path.read_text(encoding="utf-8")
                    if trace_ready:
                        trace_ready_at = trace_ready_at or time.monotonic()
                        marker_ready = exit_after_marker is None or any(
                            (repo / ".runtime/es-stack/runs").glob(f"*/validation-*/{exit_after_marker}")
                        )
                        stack_ready = exit_after_stack is None or any(
                            exit_after_stack in path.read_text(encoding="utf-8")
                            for path in (repo / ".runtime/es-stack/runs").glob("*/stack.log")
                        )
                        if marker_ready and stack_ready:
                            break
                        if time.monotonic() - trace_ready_at >= 2:
                            raise AssertionError(f"Validation marker was not created: {exit_after_marker}")
                    if process.poll() is not None:
                        raise AssertionError(f"PowerShell host exited before trace marker: {exit_after_trace}")
                    time.sleep(0.05)
                else:
                    raise AssertionError(f"Timed out waiting for PowerShell trace marker: {exit_after_trace}")
                assert process.poll() is None
                trigger = pipeline_stop_trigger if stop_pipeline_after_trace else exit_trigger
                trigger.write_text("stop", encoding="utf-8")
                wait_with_observation(max(time.monotonic() + 1, deadline))
        except BaseException as exc:
            primary_failure = exc
            raise
        finally:
            cleanup_errors: list[str] = []

            def cleanup_stage(name: str, action) -> None:
                try:
                    action()
                except BaseException as cleanup_error:
                    cleanup_errors.append(f"{name}: {cleanup_error!r}")

            def cleanup_scan() -> None:
                _powershell_repo_processes(repo)
                owned_registry.update(_load_powershell_process_registry(repo))

            def graceful_cleanup() -> None:
                if process.poll() is None and start_released and not stop_pipeline_after_trace:
                    exit_trigger.write_text("exit", encoding="utf-8")
                if process.poll() is not None or not start_released:
                    return
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass

            def capture_diagnostics() -> None:
                nonlocal diagnostics_text, diagnostics_error
                try:
                    diagnostics_text = _powershell_runtime_diagnostics(repo)
                except BaseException as error:
                    diagnostics_error = error
                    raise

            def exact_cleanup() -> None:
                snapshot = _powershell_process_snapshot()
                _record_owned_powershell_descendants(owned_registry, snapshot)
                _persist_powershell_process_registry(repo, owned_registry)
                survivors = _current_registered_powershell_processes(owned_registry, snapshot)
                if process.poll() is None or survivors:
                    with (repo / "trace.log").open("a", encoding="utf-8") as stream:
                        stream.write("harness=forced-cleanup\n")
                    _terminate_exact_powershell_processes(list(owned_registry.values()))
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass

            def unreleased_root_fallback() -> None:
                if start_released or process.poll() is not None:
                    return
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    raise AssertionError("PowerShell start-gated root did not exit after forced cleanup") from error

            def verify_cleanup() -> None:
                remaining = _powershell_repo_processes(repo)
                if remaining:
                    raise AssertionError(f"PowerShell harness left owned processes: {remaining}")

            cleanup_stage("owned-process scan", cleanup_scan)
            cleanup_stage("graceful launcher trigger", graceful_cleanup)
            cleanup_stage("trace diagnostics", capture_diagnostics)
            cleanup_stage("exact tree termination", exact_cleanup)
            cleanup_stage("unreleased root handle fallback", unreleased_root_fallback)
            cleanup_stage("final residual verification", verify_cleanup)

            if primary_failure is not None and diagnostics_text is not None:
                primary_failure.add_note(diagnostics_text)
            if cleanup_errors:
                details = "PowerShell harness cleanup errors: " + "; ".join(cleanup_errors)
                if primary_failure is not None:
                    primary_failure.add_note(details)
                else:
                    if diagnostics_text is not None:
                        details = f"{details}\n{diagnostics_text}"
                    elif diagnostics_error is not None:
                        details = f"{details}\nPowerShell harness diagnostics failed: {diagnostics_error!r}"
                    raise AssertionError(details)
        result = subprocess.CompletedProcess(command, process.returncode)
    return subprocess.CompletedProcess(
        command,
        result.returncode,
        stdout_path.read_text(encoding="utf-8"),
        stderr_path.read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize("doctor_status", [0, 3])
def test_powershell_provider_probe_propagates_status_without_starting_stack(
    tmp_path: Path,
    doctor_status: int,
):
    repo, env = _powershell_runtime_harness(tmp_path)
    secrets = repo / "secrets.env"
    secrets.write_text("PROBE_CANARY_API_KEY=canary-secret\n", encoding="utf-8")
    env["HARNESS_DOCTOR_STATUS"] = str(doctor_status)
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts/es-runtime-stack.ps1"),
            "-Config",
            "config.yaml",
            "-SecretsFile",
            str(secrets),
            "-ProbeProviders",
        ],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == doctor_status, completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "runtime-doctor.py=--config" in trace
    assert "--probe-providers --json" in trace
    assert "doctor_key_loaded=yes" in trace
    assert "inspect=" not in trace
    assert "compose=" not in trace
    assert "uvicorn.py=" not in trace
    assert "recorded-video-worker.py=" not in trace
    assert "es_ingest_smoke.py=" not in trace
    assert not (repo / ".runtime/recorded-video").exists()
    assert "canary-secret" not in completed.stdout
    assert "canary-secret" not in completed.stderr


def test_bash_help_exposes_data_root_and_explicit_validation_without_starting_services():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")

    completed = subprocess.run(
        [bash, str(BASH_SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--data-root PATH" in completed.stdout
    assert "--validate" in completed.stdout
    assert "docker" not in completed.stderr.lower()


@pytest.mark.parametrize("keep_option", ["--keep-running", "-KeepRunning"])
def test_bash_keep_running_requires_explicit_validation_before_dependencies(tmp_path: Path, keep_option: str):
    repo, env = _bash_runtime_harness(tmp_path)

    completed = _run_bash_runtime(repo, env, keep_option)

    assert completed.returncode == 2
    assert "requires explicit validation" in completed.stderr
    assert not (repo / "trace.log").exists()


def test_bash_keep_running_rejects_smoke_only_before_dependencies(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--keep-running")

    assert completed.returncode == 2
    assert "cannot be combined" in completed.stderr
    assert not (repo / "trace.log").exists()


def test_bash_keep_running_reaches_readiness_stays_alive_and_cleans_on_signal(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    bash = shutil.which("bash")
    assert bash is not None
    process = subprocess.Popen(
        [
            bash,
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--keep-running",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir: Path | None = None
        while time.monotonic() < deadline:
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            if run_dirs:
                run_dir = run_dirs[0]
                stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
                marker = run_dir / f"validation-{run_dir.name}" / "interruption-ready.marker"
                if "READY: isolated validation runtime" in stack_log and marker.exists():
                    break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"launcher exited before readiness: {stdout}\n{stderr}")
            time.sleep(0.05)
        else:
            raise AssertionError("launcher did not reach isolated keep-running readiness")

        assert run_dir is not None
        assert process.poll() is None
        trace = (repo / "trace.log").read_text(encoding="utf-8")
        assert "smoke=" not in trace
        assert "proxy=ready" in trace
        ready_line = next(line for line in stack_log.splitlines() if "READY: isolated validation runtime" in line)
        assert "api=http://127.0.0.1:8000" in ready_line
        assert "ui=http://127.0.0.1:3000" in ready_line
        assert "es=http://127.0.0.1:9200" in ready_line
        assert f"index=validation-{run_dir.name}" in ready_line

        launcher_pid = (run_dir / "launcher.pid").read_text(encoding="utf-8").strip()
        terminated = subprocess.run(
            [bash, "-c", 'kill -TERM "$1"', "bash", launcher_pid],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert terminated.returncode == 0, terminated.stderr
        return_code = process.wait(timeout=10)
        assert return_code != 0
        assert not (run_dir / "validation-config.yaml").exists()
        assert not (run_dir / f"validation-{run_dir.name}").exists()
        trace = (repo / "trace.log").read_text(encoding="utf-8")
        assert f"http://127.0.0.1:9200/validation-{run_dir.name}" in trace
    finally:
        if process.poll() is None:
            launcher_pid_path = run_dir / "launcher.pid" if run_dir is not None else None
            if launcher_pid_path is not None and launcher_pid_path.exists():
                launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
                subprocess.run(
                    [bash, "-c", 'kill -TERM "$1"', "bash", launcher_pid],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_bash_full_validation_run_is_isolated_redacted_and_manifested(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "3")

    assert completed.returncode == 0, completed.stderr
    run_dirs = list((repo / ".runtime/es-stack/runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    managed = {item["component"]: item for item in manifest["processes"]}
    assert {"api", "worker"} <= managed.keys()
    assert all(item["exit_status"] is not None for item in managed.values())
    assert all(item["pid"] > 0 for item in managed.values())
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    api_config = re.search(r"^api_config=(.+)$", trace, re.MULTILINE).group(1)  # type: ignore[union-attr]
    worker_config = re.search(r"^worker_config=(.+)$", trace, re.MULTILINE).group(1)  # type: ignore[union-attr]
    assert api_config == worker_config
    assert api_config.endswith("validation-config.yaml")
    assert f"embed_index: validation-{run_dir.name}" in trace
    assert re.search(rf'data_root: "[^"]+/validation-{re.escape(run_dir.name)}"', trace)
    assert ".runtime/recorded-video" not in trace
    assert "recorded_video:" not in trace or "enabled: true" in trace
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()
    combined_logs = "\n".join(
        (run_dir / name).read_text(encoding="utf-8") for name in ("stack.log", "api.log", "worker.log", "es.log")
    )
    for secret in ("doctor-secret", "api-secret", "worker-secret", "es-secret", "QUJDREVGR0g="):
        assert secret not in combined_logs


def test_bash_plain_validate_starts_ui_runs_smoke_passes_and_cleans_isolation(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)

    completed = _run_bash_runtime(repo, env, "--validate", "--timeout-sec", "3")

    assert completed.returncode == 0, completed.stderr
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker", "ui"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" in trace
    assert "PASS: ES runtime stack validation succeeded" in (run_dir / "stack.log").read_text(encoding="utf-8")
    assert (
        f"curl=-fsS -X DELETE --get --data-urlencode ignore_unavailable=true http://127.0.0.1:9200/validation-{run_dir.name}-legacy-smoke"
        in trace
    )
    assert (
        f"curl=-fsS -X DELETE --get --data-urlencode ignore_unavailable=true http://127.0.0.1:9200/validation-{run_dir.name}"
        in trace
    )
    assert not (run_dir / "config.yaml").exists()
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()


def test_bash_validation_cleanup_failure_returns_nonzero_without_claiming_success(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_DELETE_FAIL"] = "1"

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "3")

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
    assert "failed to remove validation index" in stack_log
    assert "removed isolated validation namespace" not in stack_log
    assert not (run_dir / "validation-config.yaml").exists()


def test_bash_validation_failure_still_cleans_worker_and_isolated_files(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_STATUS"] = "9"

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "3")

    assert completed.returncode == 9
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()


def test_bash_foreign_listener_refusal_happens_before_service_start(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_FOREIGN_PID"] = "999999"

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "1")

    assert completed.returncode != 0
    assert "FOREIGN_LISTENER" in completed.stderr
    trace = repo / "trace.log"
    assert not trace.exists() or "docker=" not in trace.read_text(encoding="utf-8")


def test_bash_worker_readiness_failure_cleans_started_processes(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_WORKER_READY"] = "0"

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "2")

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
    assert "component=worker" in stack_log
    assert "state=exited" in stack_log
    assert "exit_code=7" in stack_log


def test_bash_normal_start_never_invokes_validation_smoke(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_API_EXIT_AFTER"] = "1"

    completed = _run_bash_runtime(repo, env, "--timeout-sec", "3")

    assert completed.returncode == 17, completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" not in trace
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])


def test_bash_conda_shell_function_adapter_covers_doctor_and_long_running_api(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_DEFINE_CONDA_FUNCTION"] = "1"
    env["HARNESS_API_EXIT_AFTER"] = "1"
    fake_bin = env["PATH"].split(":", 1)[0]
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    completed = _run_bash_runtime(repo, env, "--conda-env", "vsa-agent", "--timeout-sec", "3")

    assert completed.returncode == 17, completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    conda_calls = [line for line in trace.splitlines() if line.startswith("conda_function=")]
    assert any("sys.executable" in line for line in conda_calls)
    assert "doctor=scripts/runtime-doctor.py" in trace
    assert any("python -m uvicorn" in line for line in conda_calls)


def test_bash_es_log_stream_exit_fails_validation_even_when_es_health_is_good(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_ES_LOG_EXIT_STATUS"] = "19"

    completed = _run_bash_runtime(repo, env, "--validate", "--smoke-only", "--timeout-sec", "3")

    assert completed.returncode != 0
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" not in trace
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    assert "PASS:" not in completed.stdout
    assert "PASS:" not in completed.stderr
    assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    es = next(item for item in manifest["processes"] if item["component"] == "es")
    assert es["exit_status"] is not None


def test_bash_es_log_exit_at_smoke_completion_boundary_prevents_pass(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    boundary_gate = tmp_path / "es-log-smoke-boundary"
    env["HARNESS_ES_LOG_SMOKE_BOUNDARY_GATE"] = boundary_gate.as_posix()
    env["HARNESS_ES_LOG_SMOKE_BOUNDARY_STATUS"] = "23"

    bash = shutil.which("bash")
    assert bash is not None
    completed = subprocess.run(
        [bash, (repo / "scripts/es-runtime-stack.sh").as_posix(), "--validate", "--smoke-only", "--timeout-sec", "3"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=BASH_SMOKE_COMPLETION_BOUNDARY_TIMEOUT_SEC,
    )

    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    es_status = json.loads((run_dir / "es.status.json").read_text(encoding="utf-8"))
    diagnostics = (
        completed.returncode,
        es_status,
        (repo / "trace.log").read_text(encoding="utf-8"),
        (run_dir / "stack.log").read_text(encoding="utf-8"),
        completed.stdout,
        completed.stderr,
    )
    assert boundary_gate.with_suffix(".ready").exists(), diagnostics
    assert boundary_gate.with_suffix(".smoke-complete").exists(), diagnostics
    assert es_status["state"] == "exited", diagnostics
    assert es_status["exit_code"] == 23, diagnostics
    assert completed.returncode != 0, (es_status, completed.stdout, completed.stderr)
    stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
    assert "PASS:" not in completed.stdout
    assert "PASS:" not in completed.stderr
    assert "PASS:" not in stack_log
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    es = next(item for item in manifest["processes"] if item["component"] == "es")
    assert es["exit_status"] is not None
    owned_pids = [int(item["pid"]) for item in manifest["processes"]]
    survivors = _wait_for_bash_pids_gone(bash, repo, env, owned_pids)
    try:
        assert not survivors, f"owned process survived boundary failure: {survivors}"
    finally:
        _kill_bash_pids(bash, repo, env, survivors)


@pytest.mark.parametrize(
    ("failure", "payload_update"),
    [
        ("missing", {}),
        ("corrupt", {}),
        ("exited", {"state": "exited", "exit_code": 23}),
        ("stale-run", {"run_id": "another-run"}),
        ("supervisor-pid", {"supervisor_pid": 999999}),
        ("workload-pid", {"workload_pid": 0}),
    ],
)
def test_bash_status_sidecar_validator_rejects_invalid_component_state(
    tmp_path: Path, failure: str, payload_update: dict[str, object]
):
    validator = _bash_function("validate_component_status")
    status_file = tmp_path / "api.status.json"
    payload = {
        "schema_version": 1,
        "run_id": "run-1",
        "component": "api",
        "state": "running",
        "supervisor_pid": os.getpid(),
        "workload_pid": os.getpid(),
        "exit_code": None,
        "updated_at": "2026-07-16T00:00:00Z",
    }
    payload.update(payload_update)
    if failure == "corrupt":
        status_file.write_text("{not-json", encoding="utf-8")
    elif failure != "missing":
        status_file.write_text(json.dumps(payload), encoding="utf-8")
    probe = f"""
    RUN_ID=run-1
    {validator}
    validate_component_status api {shlex.quote(status_file.as_posix())} {os.getpid()}
    """

    completed = _run_bash_probe(probe)

    if failure == "exited":
        assert completed.returncode == 23
    else:
        assert completed.returncode != 0
    assert "component=api" in completed.stderr
    assert f"status_file={status_file.as_posix()}" in completed.stderr
    assert "exit_code=" in completed.stderr


def test_bash_wait_component_status_running_returns_terminal_sidecar_exit_code(tmp_path: Path):
    validator = _bash_function("validate_component_status")
    waiter = _bash_function("wait_component_status_running")
    status_file = tmp_path / "api.status.json"
    status_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-1",
                "component": "api",
                "state": "exited",
                "supervisor_pid": os.getpid(),
                "workload_pid": os.getpid(),
                "exit_code": 17,
                "updated_at": "2026-07-18T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    probe = f"""
    RUN_ID=run-1
    TIMEOUT_SEC=1
    declare -A PROCESS_PIDS=([api]={os.getpid()})
    declare -A PROCESS_STATUS_FILES=([api]={shlex.quote(status_file.as_posix())})
    fail_if_managed_process_exited() {{ return 0; }}
    log_stack_error() {{ printf '%s\n' "$*" >&2; }}
    {validator}
    {waiter}
    wait_component_status_running api
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode == 17
    assert "component=api" in completed.stderr
    assert "state=exited" in completed.stderr
    assert "exit_code=17" in completed.stderr


@pytest.mark.parametrize("signal_name", ["TERM", "INT"])
def test_bash_interruption_cleans_validation_index_data_and_config(tmp_path: Path, signal_name: str):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_SLEEP"] = "30"
    bash = shutil.which("bash")
    assert bash is not None
    launcher = (repo / "scripts/es-runtime-stack.sh").as_posix()
    trace_path = repo / "trace.log"
    launcher_pid_path: Path | None = None

    process = subprocess.Popen(
        [
            bash,
            "-c",
            'exec "$@"',
            "bash",
            launcher,
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir: Path | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"launcher exited before smoke readiness: rc={process.returncode}\n{stdout}\n{stderr}")
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            if run_dirs:
                candidate = run_dirs[0]
                marker = candidate / f"validation-{candidate.name}/interruption-ready.marker"
                trace = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
                candidate_launcher_pid_path = candidate / "launcher.pid"
                if (
                    "smoke=" in trace
                    and marker.exists()
                    and (candidate / "validation-config.yaml").exists()
                    and candidate_launcher_pid_path.exists()
                ):
                    run_dir = candidate
                    launcher_pid_path = candidate_launcher_pid_path
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("launcher did not reach smoke readiness before interruption")

        assert launcher_pid_path is not None
        launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
        signaled = subprocess.run(
            [bash, "-c", 'kill -s "$1" "$2"', "bash", signal_name, launcher_pid],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert signaled.returncode == 0, signaled.stderr
        stdout, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            if launcher_pid_path is not None and launcher_pid_path.exists():
                launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
                subprocess.run(
                    [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
                    cwd=repo,
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_bash_launcher_process(process)

    assert process.returncode == 130, stderr
    assert run_dir is not None
    trace = trace_path.read_text(encoding="utf-8")
    assert "smoke=" in trace
    assert "PASS:" not in stdout
    assert "PASS:" not in stderr
    assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8")
    delete_lines = [line for line in trace.splitlines() if "-X DELETE" in line]
    assert any(line.endswith(f"/validation-{run_dir.name}-legacy-smoke") for line in delete_lines)
    assert any(line.endswith(f"/validation-{run_dir.name}-contract-v1") for line in delete_lines)
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / "config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert manifest["processes"]
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    owned_pids = [int(item["pid"]) for item in manifest["processes"]]
    owned_pids.extend(
        int(line.split("=", 1)[1])
        for line in trace.splitlines()
        if line.startswith(("api_pid=", "worker_pid=", "smoke_pid="))
    )
    survivors = _wait_for_bash_pids_gone(bash, repo, env, owned_pids)
    assert not survivors, f"owned process survived interruption: {survivors}"


def test_bash_rapid_back_to_back_terms_before_cleanup_still_finish_cleanup(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_SLEEP"] = "30"
    bash = shutil.which("bash")
    assert bash is not None
    trace_path = repo / "trace.log"
    launcher_pid_path: Path | None = None
    process = subprocess.Popen(
        [
            bash,
            "-c",
            'exec "$@"',
            "bash",
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    owned_pids: list[int] = []
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir = None
        while time.monotonic() < deadline:
            assert process.poll() is None
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            trace = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
            if run_dirs and "smoke=" in trace:
                candidate = run_dirs[0]
                marker = candidate / f"validation-{candidate.name}/interruption-ready.marker"
                if marker.exists() and (candidate / "validation-config.yaml").exists():
                    run_dir = candidate
                    launcher_pid_path = run_dir / "launcher.pid"
                    break
            time.sleep(0.02)
        assert run_dir is not None
        assert launcher_pid_path is not None

        launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
        signaled = subprocess.run(
            [
                bash,
                "-c",
                'for ((attempt = 0; attempt < 256; attempt++)); do kill -s TERM "$1" 2>/dev/null || break; done',
                "bash",
                launcher_pid,
            ],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert signaled.returncode == 0, signaled.stderr
        stdout, stderr = process.communicate(timeout=20)

        assert process.returncode == 130, stderr
        trace = trace_path.read_text(encoding="utf-8")
        assert len([line for line in trace.splitlines() if "-X DELETE" in line]) == 2
        assert not (run_dir / "validation-config.yaml").exists()
        assert not (run_dir / "config.yaml").exists()
        assert not (run_dir / f"validation-{run_dir.name}").exists()
        manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
        assert all(item["exit_status"] is not None for item in manifest["processes"])
        assert "PASS:" not in stdout
        owned_pids = [int(item["pid"]) for item in manifest["processes"]]
        owned_pids.extend(
            int(line.split("=", 1)[1])
            for line in trace.splitlines()
            if line.startswith(("api_pid=", "worker_pid=", "smoke_pid="))
        )
        assert not _wait_for_bash_pids_gone(bash, repo, env, owned_pids)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        _kill_bash_pids(bash, repo, env, owned_pids)


def test_bash_interrupt_entry_masks_followup_signals_before_cleanup_dispatch():
    handler = _bash_function("handle_interrupt")
    cleanup = _bash_function("cleanup")
    script = _bash()

    assert "trap '' INT TERM" in handler
    assert handler.index("trap '' INT TERM") < handler.index("INTERRUPTED_SIGNAL=")
    assert "trap 'handle_interrupt" not in cleanup
    assert 'trap \'status=$?; trap "" INT TERM; cleanup "$status"\' EXIT' in script


def test_bash_component_supervisor_exports_registered_pid_and_cleanup_preserves_primary_status():
    start_component = _bash_function("start_supervised_process")
    cleanup = _bash_function("cleanup")
    script = _bash()

    assert 'VSA_SUPERVISOR_REGISTERED_PID="$BASHPID" exec "$@"' in start_component
    assert 'local status="${1:-$?}" cleanup_failed=0' in cleanup
    assert 'trap \'status=$?; trap "" INT TERM; cleanup "$status"\' EXIT' in script


def test_bash_status_validator_does_not_probe_workload_pid_with_os_signal():
    validator = _bash_function("validate_component_status")

    assert "invalid workload PID" in validator
    assert "os.kill(workload_pid, 0)" not in validator
    assert "OpenProcess" not in validator
    assert "GetExitCodeProcess" not in validator


def test_bash_manifest_update_failure_during_signal_cleanup_is_aggregated(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_SLEEP"] = "30"
    manifest_failure_gate = tmp_path / "manifest-update.fail"
    env["HARNESS_MANIFEST_FAILURE_GATE"] = manifest_failure_gate.as_posix()
    bash = shutil.which("bash")
    assert bash is not None
    trace_path = repo / "trace.log"
    launcher_pid_path: Path | None = None
    process = subprocess.Popen(
        [
            bash,
            "-c",
            'exec "$@"',
            "bash",
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    owned_pids: list[int] = []
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir = None
        while time.monotonic() < deadline:
            assert process.poll() is None
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            trace = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
            if run_dirs and "smoke=" in trace:
                run_dir = run_dirs[0]
                launcher_pid_path = run_dir / "launcher.pid"
                break
            time.sleep(0.02)
        assert run_dir is not None
        assert launcher_pid_path is not None

        manifest_failure_gate.touch()
        launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
        signaled = subprocess.run(
            [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert signaled.returncode == 0, signaled.stderr
        stdout, stderr = process.communicate(timeout=20)

        assert process.returncode != 0, stderr
        trace = trace_path.read_text(encoding="utf-8")
        assert trace.count("manifest_update_failed=1") >= 3
        assert len([line for line in trace.splitlines() if "-X DELETE" in line]) == 2
        assert not (run_dir / "validation-config.yaml").exists()
        assert not (run_dir / "config.yaml").exists()
        assert not (run_dir / f"validation-{run_dir.name}").exists()
        stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
        for component in ("worker", "api", "es"):
            assert f"cleanup stage failed: stop {component}" in stack_log
        assert "PASS:" not in stdout
        manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
        owned_pids = [int(item["pid"]) for item in manifest["processes"]]
        owned_pids.extend(
            int(line.split("=", 1)[1])
            for line in trace.splitlines()
            if line.startswith(("api_pid=", "worker_pid=", "smoke_pid="))
        )
        assert not _wait_for_bash_pids_gone(bash, repo, env, owned_pids)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        _kill_bash_pids(bash, repo, env, owned_pids)


def test_bash_second_signal_during_cleanup_still_finishes_all_cleanup(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_SLEEP"] = "30"
    delete_gate = tmp_path / "delete-gate"
    env["HARNESS_DELETE_GATE"] = delete_gate.as_posix()
    delete_ready = Path(f"{delete_gate}.ready")
    delete_release = Path(f"{delete_gate}.release")
    bash = shutil.which("bash")
    assert bash is not None
    trace_path = repo / "trace.log"
    launcher_pid_path: Path | None = None
    process = subprocess.Popen(
        [
            bash,
            "-c",
            'exec "$@"',
            "bash",
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir = None
        while time.monotonic() < deadline:
            assert process.poll() is None
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            trace = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
            if run_dirs and "smoke=" in trace:
                run_dir = run_dirs[0]
                launcher_pid_path = run_dir / "launcher.pid"
                break
            time.sleep(0.05)
        assert run_dir is not None
        assert launcher_pid_path is not None

        launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
        first = subprocess.run(
            [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert first.returncode == 0, first.stderr
        deadline = time.monotonic() + 15
        while not delete_ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.02)
        assert delete_ready.exists()

        second = subprocess.run(
            [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert second.returncode == 0, second.stderr
        delete_release.touch()
        stdout, stderr = process.communicate(timeout=15)
    finally:
        delete_release.touch()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode == 130, stderr
    trace = trace_path.read_text(encoding="utf-8")
    delete_lines = [line for line in trace.splitlines() if "-X DELETE" in line]
    assert len(delete_lines) == 2
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / "config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
    assert "process manifest:" in stack_log
    assert "stack log:" in stack_log
    assert "interruption signal=" in stack_log
    assert "PASS:" not in stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows lock contention probe")
def test_bash_signal_while_pass_log_is_lock_blocked_never_emits_pass(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    smoke_gate = tmp_path / "smoke-gate"
    env["HARNESS_SMOKE_GATE"] = smoke_gate.as_posix()
    smoke_ready = Path(f"{smoke_gate}.ready")
    smoke_release = Path(f"{smoke_gate}.release")
    pass_attempt = tmp_path / "pass-attempt.marker"
    wrapper_events = tmp_path / "wrapper-events.log"
    locker_events = tmp_path / "locker-events.log"
    supervisor_wrapper = repo / "fake-bin/supervisor-python"
    _write_executable(
        supervisor_wrapper,
        f"""
        #!/usr/bin/env bash
        if [[ "$*" == *"PASS: ES runtime stack validation succeeded"* ]]; then
          : >{shlex.quote(pass_attempt.as_posix())}
          printf 'started wrapper=%s\n' "$BASHPID" >>{shlex.quote(wrapper_events.as_posix())}
        fi
        exec "$REAL_PYTHON" "$@"
        """,
    )
    env["VSA_SUPERVISOR_PYTHON"] = supervisor_wrapper.as_posix()
    bash = shutil.which("bash")
    assert bash is not None
    launcher_pid_path: Path | None = None
    process = subprocess.Popen(
        [
            bash,
            "-c",
            'exec "$@"',
            "bash",
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    lock_release = tmp_path / "lock.release"
    locker = None
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        run_dir = None
        while time.monotonic() < deadline:
            assert process.poll() is None
            run_dirs = list((repo / ".runtime/es-stack/runs").glob("*"))
            if run_dirs and smoke_ready.exists():
                run_dir = run_dirs[0]
                launcher_pid_path = run_dir / "launcher.pid"
                break
            time.sleep(0.02)
        assert run_dir is not None
        assert launcher_pid_path is not None
        lock_path = run_dir / "stack.log.lock"
        lock_ready = tmp_path / "lock.ready"
        locker_code = """
import msvcrt
import pathlib
import sys
import time

lock_path, ready, release = map(pathlib.Path, sys.argv[1:4])
with pathlib.Path(sys.argv[4]).open('a', encoding='utf-8') as events:
    events.write('opened\\n')
with lock_path.open("r+b", buffering=0) as stream:
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    pathlib.Path(sys.argv[4]).open('a', encoding='utf-8').write('locked\\n')
    ready.touch()
    while not release.exists():
        time.sleep(0.01)
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    pathlib.Path(sys.argv[4]).open('a', encoding='utf-8').write('released\\n')
"""
        locker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                locker_code,
                str(lock_path),
                str(lock_ready),
                str(lock_release),
                str(locker_events),
            ]
        )
        deadline = time.monotonic() + 5
        while not lock_ready.exists() and time.monotonic() < deadline:
            assert locker.poll() is None
            time.sleep(0.01)
        assert lock_ready.exists()

        smoke_release.touch()
        deadline = time.monotonic() + 10
        while not pass_attempt.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.01)
        assert pass_attempt.exists()
        time.sleep(0.5)
        locker_state = locker_events.read_text(encoding="utf-8") if locker_events.exists() else "<missing>"
        assert "locked" in locker_state
        assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8"), (
            locker_state,
            wrapper_events.read_text(encoding="utf-8") if wrapper_events.exists() else "<missing>",
        )
        launcher_pid = launcher_pid_path.read_text(encoding="utf-8")
        signaled = subprocess.run(
            [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert signaled.returncode == 0, signaled.stderr
        time.sleep(0.1)
        lock_release.touch()
        stdout, stderr = process.communicate(timeout=15)
    finally:
        smoke_release.touch()
        lock_release.touch()
        if locker is not None:
            if locker.poll() is None:
                locker.kill()
            locker.wait(timeout=5)
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode == 130, stderr
    events = wrapper_events.read_text(encoding="utf-8") if wrapper_events.exists() else "<missing>"
    assert "PASS:" not in stdout, events
    assert "PASS:" not in stderr
    assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows deterministic PASS publication probe")
def test_bash_pass_publication_rejects_terminal_sidecar_while_supervisor_drains(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    api_exit_trigger = tmp_path / "api-exit.trigger"
    pass_attempt = tmp_path / "pass-attempt.marker"
    pass_release = tmp_path / "pass.release"
    env["HARNESS_API_EXIT_TRIGGER"] = api_exit_trigger.as_posix()
    env["HARNESS_API_DRAIN_LINES"] = "20000"
    supervisor_wrapper = repo / "fake-bin/supervisor-python"
    _write_executable(
        supervisor_wrapper,
        f"""
        #!/usr/bin/env bash
        if [[ "$*" == *"PASS: ES runtime stack validation succeeded"* ]]; then
          : >{shlex.quote(pass_attempt.as_posix())}
          while [[ ! -e {shlex.quote(pass_release.as_posix())} ]]; do sleep 0.01; done
        fi
        exec "$REAL_PYTHON" "$@"
        """,
    )
    env["VSA_SUPERVISOR_PYTHON"] = supervisor_wrapper.as_posix()
    bash = shutil.which("bash")
    assert bash is not None
    stdout_path = tmp_path / "launcher.stdout.log"
    stderr_path = tmp_path / "launcher.stderr.log"
    stdout_sink = stdout_path.open("w", encoding="utf-8")
    stderr_sink = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            bash,
            (repo / "scripts/es-runtime-stack.sh").as_posix(),
            "--validate",
            "--smoke-only",
            "--timeout-sec",
            "3",
        ],
        cwd=repo,
        env=env,
        stdout=stdout_sink,
        stderr=stderr_sink,
        text=True,
        creationflags=_bash_launcher_creationflags(),
    )
    run_dir: Path | None = None
    try:
        deadline = time.monotonic() + BASH_RUNTIME_READINESS_TIMEOUT_SEC
        while not pass_attempt.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.01)
        assert pass_attempt.exists()
        run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
        api_exit_trigger.touch()
        api_status_path = run_dir / "api.status.json"
        api_status = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if api_status_path.exists():
                api_status = json.loads(api_status_path.read_text(encoding="utf-8"))
                if api_status.get("state") == "exited":
                    break
            time.sleep(0.005)
        assert api_status is not None
        assert api_status["state"] == "exited"
        assert api_status["exit_code"] == 17
        assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8")
        pass_release.touch()
        process.wait(timeout=20)
    finally:
        api_exit_trigger.touch()
        pass_release.touch()
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        stdout_sink.close()
        stderr_sink.close()

    assert run_dir is not None
    stdout = stdout_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    assert process.returncode != 0, stderr
    assert "PASS:" not in stdout
    assert "PASS:" not in stderr
    assert "PASS:" not in (run_dir / "stack.log").read_text(encoding="utf-8")


def test_bash_runtime_monitor_detects_api_exit_while_worker_and_ui_continue():
    functions = "\n".join(
        _bash_function(name)
        for name in (
            "pid_is_running",
            "observe_managed_processes",
            "fail_if_managed_process_exited",
            "wait_runtime_processes",
        )
    )
    probe = f"""
    declare -A PROCESS_PIDS=()
    record_process_exit() {{ :; }}
    log_stack_error() {{ printf '%s' "$*" >&2; }}
    validate_managed_statuses() {{ return 0; }}
    {functions}
    bash -c 'exit 7' & PROCESS_PIDS[api]=$!
    bash -c 'while :; do sleep 0.1; done' & PROCESS_PIDS[worker]=$!
    bash -c 'while :; do sleep 0.1; done' & PROCESS_PIDS[ui]=$!
    trap 'kill -KILL "${{PROCESS_PIDS[worker]}}" "${{PROCESS_PIDS[ui]}}" 2>/dev/null || true' EXIT
    wait_runtime_processes
    """

    completed = _run_bash_probe(probe, timeout=3)

    assert completed.returncode != 0
    assert "api" in completed.stderr


@pytest.mark.parametrize("mode", ["sync", "component"])
def test_bash_signal_in_supervisor_registration_window_cleans_registered_pid(tmp_path: Path, mode: str):
    function_names = (
        "handle_interrupt",
        "begin_supervisor_start",
        "finish_supervisor_start",
        "start_sync_supervisor",
        "wait_sync_supervisor",
        "run_stack_command",
        "start_supervised_process",
        "observe_managed_processes",
        "pid_is_running",
        "signal_process_tree",
        "stop_pid_bounded",
    )
    functions = "\n".join(_bash_function(name) for name in function_names)
    fake_supervisor = tmp_path / "fake-supervisor.py"
    fake_supervisor.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    ready = tmp_path / f"{mode}.ready"
    release = tmp_path / f"{mode}.release"
    launcher_pid_path = tmp_path / f"{mode}.launcher.pid"
    supervisor_pid_path = tmp_path / f"{mode}.supervisor.pid"
    stack_log = tmp_path / "stack.log"
    component_log = tmp_path / "component.log"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = f"""
    set -Eeuo pipefail
    SUPERVISOR_PYTHON={shlex.quote(Path(sys.executable).as_posix())}
    RUNTIME_LOG_SUPERVISOR={shlex.quote(fake_supervisor.as_posix())}
    STACK_LOG_PATH={shlex.quote(stack_log.as_posix())}
    RUN_DIR={shlex.quote(run_dir.as_posix())}
    SYNC_SUPERVISOR_PID=""
    STARTED_SUPERVISOR_PID=""
    INTERRUPTED_SIGNAL=""
    INTERRUPT_PENDING=0
    CLEANUP_ACTIVE=0
    SUPERVISOR_START_CRITICAL=0
    PROCESS_SHUTDOWN_GRACE_TICKS=2
    declare -A PROCESS_PIDS=()
    declare -A PROCESS_STATUS_FILES=()
    record_process() {{ PROCESS_PIDS["$1"]="$2"; }}
    {functions}
    register_sync_supervisor() {{
      SYNC_SUPERVISOR_PID="$1"
      printf '%s' "$1" >{shlex.quote(supervisor_pid_path.as_posix())}
      : >{shlex.quote(ready.as_posix())}
      while [[ ! -e {shlex.quote(release.as_posix())} ]]; do sleep 0.01; done
    }}
    register_component_supervisor() {{
      STARTED_SUPERVISOR_PID="$2"
      record_process "$1" "$2" "$3"
      printf '%s' "$2" >{shlex.quote(supervisor_pid_path.as_posix())}
      : >{shlex.quote(ready.as_posix())}
      while [[ ! -e {shlex.quote(release.as_posix())} ]]; do sleep 0.01; done
    }}
    cleanup_probe() {{
      local status=$?
      trap - EXIT
      trap ':' INT TERM
      CLEANUP_ACTIVE=1
      [[ -z "$SYNC_SUPERVISOR_PID" ]] || stop_pid_bounded "$SYNC_SUPERVISOR_PID" || true
      for pid in "${{PROCESS_PIDS[@]:-}}"; do [[ -z "$pid" ]] || stop_pid_bounded "$pid" || true; done
      exit "$status"
    }}
    trap cleanup_probe EXIT
    trap 'handle_interrupt INT' INT
    trap 'handle_interrupt TERM' TERM
    printf '%s' "$BASHPID" >{shlex.quote(launcher_pid_path.as_posix())}
    if [[ {shlex.quote(mode)} == sync ]]; then
      run_stack_command ignored
    else
      start_supervised_process api {shlex.quote(component_log.as_posix())} safe ignored
      sleep 30
    fi
    exit 99
    """
    bash = shutil.which("bash")
    assert bash is not None
    process = subprocess.Popen(
        [bash, "-c", textwrap.dedent(probe)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"probe exited before registration: stdout={stdout!r} stderr={stderr!r}")
            time.sleep(0.01)
        assert ready.exists()
        launcher_pid = launcher_pid_path.read_text(encoding="utf-8")
        signaled = subprocess.run(
            [bash, "-c", 'kill -s TERM "$1"', "bash", launcher_pid],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert signaled.returncode == 0, signaled.stderr
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode == 130, (stdout, stderr)
    supervisor_pid = supervisor_pid_path.read_text(encoding="utf-8")
    gone = subprocess.run(
        [bash, "-c", 'kill -0 "$1" 2>/dev/null', "bash", supervisor_pid],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert gone.returncode != 0


def test_powershell_full_validation_run_records_manifest_and_shared_isolated_config(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-SmokeOnly",
        "-TimeoutSec",
        "3",
    )

    assert completed.returncode == 0, completed.stderr
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "wrapper=returned" in trace
    api_config = re.search(r"^api_config=(.+)$", trace, re.MULTILINE).group(1)  # type: ignore[union-attr]
    worker_config = re.search(r"^worker_config=(.+)$", trace, re.MULTILINE).group(1)  # type: ignore[union-attr]
    assert api_config == worker_config
    assert api_config.endswith("validation-config.yaml")
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}-legacy-smoke" in trace
    assert not (run_dir / "validation-config.yaml").exists()
    assert "PASS: ES runtime stack validation succeeded" in (run_dir / "stack.log").read_text(encoding="utf-8")


def test_powershell_plain_validate_starts_ui_runs_smoke_passes_and_cleans_isolation(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)

    completed = _run_powershell_runtime(repo, env, "-Validate", "-TimeoutSec", "3")

    assert completed.returncode == 0, completed.stderr
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker", "ui"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" in trace
    assert "PASS: ES runtime stack validation succeeded" in (run_dir / "stack.log").read_text(encoding="utf-8")
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}-legacy-smoke" in trace
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}" in trace
    assert not (run_dir / "config.yaml").exists()
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()


@pytest.mark.parametrize(
    "args, message",
    [
        (("-KeepRunning",), "requires explicit validation"),
        (("-Validate", "-SmokeOnly", "-KeepRunning"), "cannot be combined"),
    ],
)
def test_powershell_keep_running_rejects_incompatible_invocation_before_dependencies(
    tmp_path: Path, args: tuple[str, ...], message: str
):
    repo, env = _powershell_runtime_harness(tmp_path)

    completed = _run_powershell_runtime(repo, env, *args)

    assert completed.returncode != 0
    assert message in completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "inspect.py=" not in trace
    assert "compose.py=" not in trace
    assert "uvicorn.py=" not in trace


def test_powershell_keep_running_reaches_readiness_stays_alive_and_cleans_on_component_exit(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-KeepRunning",
        "-TimeoutSec",
        "3",
        exit_after_trace="proxy=ready",
        exit_after_marker="interruption-ready.marker",
        exit_after_stack="READY: isolated validation runtime",
    )

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    stack_log = (run_dir / "stack.log").read_text(encoding="utf-8")
    assert "smoke=" not in trace
    ready_line = next(line for line in stack_log.splitlines() if "READY: isolated validation runtime" in line)
    assert "api=http://127.0.0.1:8000" in ready_line
    assert "ui=http://127.0.0.1:3000" in ready_line
    assert "es=http://127.0.0.1:9200" in ready_line
    assert f"index=validation-{run_dir.name}" in ready_line
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}" in trace
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()


def test_powershell_helper_abandoned_wait_reclaims_only_its_owned_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)

    class HarnessWaitAbandonedError(RuntimeError):
        pass

    def abandon_wait(_: float) -> None:
        raise HarnessWaitAbandonedError("intentional wait abandonment")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(time, "sleep", abandon_wait)
            with pytest.raises(HarnessWaitAbandonedError, match="intentional wait abandonment"):
                _run_powershell_runtime(
                    repo,
                    env,
                    "-Validate",
                    "-KeepRunning",
                    "-TimeoutSec",
                    "3",
                    exit_after_trace="marker-that-never-arrives",
                )
        owned_after_abandonment = _powershell_repo_processes(repo)
        assert owned_after_abandonment == []
    finally:
        _terminate_exact_powershell_processes(_powershell_repo_processes(repo))


def test_powershell_helper_persistent_snapshot_failure_reclaims_unreleased_root_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)
    snapshot_calls = 0
    original_popen = subprocess.Popen
    root_handles: list[subprocess.Popen[str]] = []

    class HarnessPersistentSnapshotError(RuntimeError):
        pass

    def fail_every_snapshot() -> list[dict[str, object]]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        raise HarnessPersistentSnapshotError("intentional persistent snapshot failure")

    def capture_root_handle(*args, **kwargs) -> subprocess.Popen[str]:
        process = original_popen(*args, **kwargs)
        root_handles.append(process)
        return process

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys.modules[__name__], "_powershell_process_snapshot", fail_every_snapshot)
            patch.setattr(subprocess, "Popen", capture_root_handle)
            with pytest.raises(
                HarnessPersistentSnapshotError,
                match="intentional persistent snapshot failure",
            ) as captured:
                _run_powershell_runtime(repo, env, "-Validate", "-KeepRunning", "-TimeoutSec", "3")
        assert snapshot_calls >= 4
        assert len(root_handles) == 1
        assert root_handles[0].poll() is not None
        assert not (repo / "harness-start.trigger").exists()
        assert any("PowerShell harness cleanup errors" in note for note in captured.value.__notes__)
        assert any("intentional persistent snapshot failure" in note for note in captured.value.__notes__)
    finally:
        for handle in root_handles:
            if handle.poll() is None:
                handle.kill()
                handle.wait(timeout=5)


def test_powershell_helper_cleanup_scan_failure_preserves_primary_and_reclaims_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)
    original_sleep = time.sleep
    original_repo_processes = _powershell_repo_processes
    cleanup_scan_calls = 0

    class HarnessPollingError(RuntimeError):
        pass

    class HarnessCleanupScanError(RuntimeError):
        pass

    def fail_after_runtime_ready(_: float) -> None:
        trace = repo / "trace.log"
        if trace.exists() and "proxy=ready" in trace.read_text(encoding="utf-8"):
            raise HarnessPollingError("intentional polling failure")
        original_sleep(0.05)

    def fail_first_cleanup_scan(path: Path) -> list[dict[str, object]]:
        nonlocal cleanup_scan_calls
        cleanup_scan_calls += 1
        if cleanup_scan_calls == 1:
            raise HarnessCleanupScanError("intentional cleanup scan failure")
        return original_repo_processes(path)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(time, "sleep", fail_after_runtime_ready)
            patch.setattr(sys.modules[__name__], "_powershell_repo_processes", fail_first_cleanup_scan)
            with pytest.raises(HarnessPollingError, match="intentional polling failure") as captured:
                _run_powershell_runtime(
                    repo,
                    env,
                    "-Validate",
                    "-KeepRunning",
                    "-TimeoutSec",
                    "3",
                    exit_after_trace="marker-that-never-arrives",
                )
        assert any("intentional cleanup scan failure" in note for note in captured.value.__notes__)
        assert _powershell_repo_processes(repo) == []
    finally:
        _terminate_exact_powershell_processes(_powershell_repo_processes(repo))


def test_powershell_helper_cleanup_diagnostics_failure_is_aggregated_once_without_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)
    diagnostics_calls = 0

    class HarnessDiagnosticsError(RuntimeError):
        pass

    def fail_diagnostics(_: Path) -> str:
        nonlocal diagnostics_calls
        diagnostics_calls += 1
        raise HarnessDiagnosticsError("intentional cleanup diagnostics failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys.modules[__name__], "_powershell_runtime_diagnostics", fail_diagnostics)
            with pytest.raises(AssertionError, match="PowerShell harness cleanup errors") as captured:
                _run_powershell_runtime(repo, env, "-Validate", "-TimeoutSec", "3")
        assert "trace diagnostics" in str(captured.value)
        assert "intentional cleanup diagnostics failure" in str(captured.value)
        assert diagnostics_calls == 1
        assert _powershell_repo_processes(repo) == []
    finally:
        _terminate_exact_powershell_processes(_powershell_repo_processes(repo))


def test_powershell_launcher_persistently_tracks_descendant_before_parent_exit(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_DETACHED_CHILD"] = "1"

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-KeepRunning",
        "-TimeoutSec",
        "3",
    )

    assert completed.returncode != 0
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    detached_pid = int(re.search(r"^detached_child_pid=(\d+)$", trace, re.MULTILINE).group(1))  # type: ignore[union-attr]
    assert f"detached_child_registered_by_launcher={detached_pid}" in trace
    assert "harness=forced-cleanup" not in trace
    stack_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (repo / ".runtime/es-stack/runs").glob("*/stack.log")
    )
    registration = re.search(
        rf"process tracker registered component=api pid={detached_pid} .* creation=(\S+)",
        stack_text,
    )
    assert registration is not None
    assert not any(
        int(item["pid"]) == detached_pid and item["creation"] == registration.group(1)
        for item in _powershell_process_snapshot()
    )


def test_powershell_helper_registration_timeout_reclaims_unrecorded_detached_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_DETACHED_CHILD"] = "1"
    env["HARNESS_FORCE_TRACKER_TIMEOUT"] = "1"
    detached_identity: dict[str, object] | None = None

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                sys.modules[__name__],
                "_record_owned_powershell_descendants",
                lambda registry, snapshot: None,
            )
            completed = _run_powershell_runtime(
                repo,
                env,
                "-Validate",
                "-KeepRunning",
                "-TimeoutSec",
                "3",
            )

        assert completed.returncode != 0
        trace = (repo / "trace.log").read_text(encoding="utf-8")
        detached_pid = int(re.search(r"^detached_child_pid=(\d+)$", trace, re.MULTILINE).group(1))  # type: ignore[union-attr]
        assert f"detached_child_launcher_registration_timeout={detached_pid}" in trace
        detached_identity = next(
            (item for item in _powershell_process_snapshot() if int(item["pid"]) == detached_pid),
            None,
        )
        assert detached_identity is None
    finally:
        if detached_identity is not None:
            _terminate_exact_powershell_processes([detached_identity])


def test_powershell_registry_rejects_first_seen_child_when_recorded_parent_is_absent(
    monkeypatch: pytest.MonkeyPatch,
):
    def identity(pid: int, parent_pid: int, creation: str) -> dict[str, object]:
        return {
            "pid": pid,
            "parent_pid": parent_pid,
            "creation": creation,
            "executable_path": f"C:\\fake\\{pid}.exe",
            "command_line": f"process-{pid}-{creation}",
        }

    registry: dict[str, dict[str, object]] = {}
    root = identity(10, 1, "2026-07-16T01:00:00.0000000Z")
    _register_powershell_root_identity(registry, root)

    older_child = identity(11, 10, "2026-07-16T00:59:59.0000000Z")
    reused_root = identity(10, 1, "2026-07-16T02:00:00.0000000Z")
    reused_child = identity(12, 10, "2026-07-16T02:00:01.0000000Z")
    _record_owned_powershell_descendants(registry, [reused_root, older_child, reused_child])
    assert {_powershell_identity_key(item) for item in registry.values()} == {_powershell_identity_key(root)}

    unrelated_child = identity(13, 10, "2026-07-16T03:00:01.0000000Z")
    _record_owned_powershell_descendants(registry, [unrelated_child])
    terminated: list[dict[str, object]] = []
    with monkeypatch.context() as patch:
        patch.setattr(
            sys.modules[__name__],
            "_terminate_exact_powershell_processes",
            lambda processes: terminated.extend(processes),
        )
        _terminate_exact_powershell_processes(list(registry.values()))
    assert _powershell_identity_key(unrelated_child) not in registry
    assert unrelated_child not in terminated

    child = identity(14, 10, "2026-07-16T01:00:01.0000000Z")
    _record_owned_powershell_descendants(registry, [root, child])
    grandchild = identity(15, 14, "2026-07-16T01:00:02.0000000Z")
    _record_owned_powershell_descendants(registry, [child, grandchild])
    assert registry[_powershell_identity_key(grandchild)]["lineage"] == [
        {"pid": 10, "creation": root["creation"]},
        {"pid": 14, "creation": child["creation"]},
        {"pid": 15, "creation": grandchild["creation"]},
    ]
    assert _current_registered_powershell_processes(registry, [grandchild]) == [grandchild]


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_refuses_reused_root_and_unverifiable_orphan():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System.Diagnostics;
public sealed class VsaExitedIdentityProcess : Process
{{
    public new bool HasExited {{ get {{ return true; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $script:stage = 0
    function New-SnapshotProcess($pid, $parentPid, $created, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$pid
            ParentProcessId = [int]$parentPid
            CreationDate = [datetime]$created
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $pid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = @(
            (New-SnapshotProcess 4242 100 '2026-07-19T01:00:00Z' 'reused-root'),
            (New-SnapshotProcess 5001 4242 '2026-07-19T01:00:01Z' 'unrelated-child')
        )
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) | Select-Object -First 1
        }}
        return $records
    }}
    function Stop-Process {{ param([int]$Id, [switch]$Force, $ErrorAction) $script:killed.Add($Id) | Out-Null }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function cmd.exe {{
        param([Parameter(ValueFromRemainingArguments = $true)][object[]]$NativeArgs)
        if (($NativeArgs -join ' ') -match '/PID (\\d+)') {{ $script:killed.Add([int]$Matches[1]) | Out-Null }}
    }}
    {function}
    $root = [VsaExitedIdentityProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
        CreationKey = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks.ToString()
        CreationTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0 }} catch {{ }}
    if ($script:killed.Count -ne 0) {{
        Write-Error "reused root or orphan was terminated: $($script:killed -join ',')"
        exit 41
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_refuses_child_when_root_retained_start_ticks_mismatch():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
public sealed class VsaRootStartTicksMismatchProcess : Process
{{
    public static long StartTicks {{ get; set; }}
    public new IntPtr Handle {{ get {{ return (IntPtr)123; }} }}
    public new bool HasExited {{ get {{ return false; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool CloseMainWindow() {{ return true; }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:childAlive = $true
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $rootCimTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    [VsaRootStartTicksMismatchProcess]::StartTicks = $rootCimTicks + 8
    function New-SnapshotProcess($snapshotPid, $snapshotParentPid, $ticks, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$snapshotParentPid
            CreationDate = [datetime]::new([long]$ticks, [DateTimeKind]::Utc)
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $snapshotPid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = @(
            (New-SnapshotProcess 4242 100 $rootCimTicks 'ui-root')
        )
        if ($script:childAlive) {{
            $records += New-SnapshotProcess 5001 4242 ($rootCimTicks + 10000000) 'bash-child'
        }}
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) |
                Select-Object -First 1
        }}
        return $records
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $target = [pscustomobject]@{{
            Id = $Id
            Handle = [intptr]123
            StartTime = [datetime]::new($rootCimTicks + 10000000, [DateTimeKind]::Utc)
            HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{
            $this.HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:killed.Add($this.Id) | Out-Null
            $script:childAlive = $false
            $this.HasExited = $true
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {function}
    $root = [VsaRootStartTicksMismatchProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = $rootCimTicks + 7
        CreationKey = $rootCimTicks.ToString()
        CreationTicks = $rootCimTicks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0 }} catch {{ }}
    if ($script:killed.Count -ne 0) {{
        Write-Error "child was terminated after root .NET StartTime mismatch: $($script:killed -join ',')"
        exit 45
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_refuses_child_when_retained_root_has_exited():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
public sealed class VsaExitedRootProcess : Process
{{
    public static long StartTicks {{ get; set; }}
    public new IntPtr Handle {{ get {{ return (IntPtr)123; }} }}
    public new bool HasExited {{ get {{ return true; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:childAlive = $true
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $rootCimTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    [VsaExitedRootProcess]::StartTicks = $rootCimTicks
    function New-SnapshotProcess($snapshotPid, $snapshotParentPid, $ticks, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$snapshotParentPid
            CreationDate = [datetime]::new([long]$ticks, [DateTimeKind]::Utc)
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $snapshotPid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = @(
            (New-SnapshotProcess 4242 100 $rootCimTicks 'ui-root')
        )
        if ($script:childAlive) {{
            $records += New-SnapshotProcess 5001 4242 ($rootCimTicks + 10000000) 'bash-child'
        }}
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) |
                Select-Object -First 1
        }}
        return $records
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $target = [pscustomobject]@{{
            Id = $Id
            Handle = [intptr]123
            StartTime = [datetime]::new($rootCimTicks + 10000000, [DateTimeKind]::Utc)
            HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{
            $this.HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:killed.Add($this.Id) | Out-Null
            $script:childAlive = $false
            $this.HasExited = $true
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {function}
    $root = [VsaExitedRootProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = $rootCimTicks
        CreationKey = $rootCimTicks.ToString()
        CreationTicks = $rootCimTicks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0 }} catch {{ }}
    if ($script:killed.Count -ne 0) {{
        Write-Error "child was terminated after root process had exited: $($script:killed -join ',')"
        exit 46
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_does_not_expand_orphan_when_parent_identity_is_unavailable():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System.Diagnostics;
public sealed class VsaExitedParentProcess : Process
{{
    public new bool HasExited {{ get {{ return true; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:stage = 0
    $script:killed = [System.Collections.Generic.List[int]]::new()
    function New-SnapshotProcess($pid, $parentPid, $created, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$pid
            ParentProcessId = [int]$parentPid
            CreationDate = [datetime]$created
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $pid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        if ($script:stage -eq 0) {{
            $script:stage = 1
            return @(New-SnapshotProcess 4242 100 '2026-07-19T00:00:00Z' 'ui-root')
        }}
        return @(New-SnapshotProcess 5001 4242 '2026-07-19T00:00:01Z' 'orphan-pipe-holder')
    }}
    function Stop-Process {{ param([int]$Id, [switch]$Force, $ErrorAction) $script:killed.Add($Id) | Out-Null }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function cmd.exe {{
        param([Parameter(ValueFromRemainingArguments = $true)][object[]]$NativeArgs)
        if (($NativeArgs -join ' ') -match '/PID (\\d+)') {{ $script:killed.Add([int]$Matches[1]) | Out-Null }}
    }}
    {function}
    $root = [VsaExitedParentProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
        CreationKey = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks.ToString()
        CreationTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0 }} catch {{ }}
    if ($script:killed.Count -ne 0) {{
        Write-Error "unverifiable orphan was terminated: $($script:killed -join ',')"
        exit 42
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_fails_closed_when_descendant_identity_changes_before_kill():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System.Diagnostics;
public sealed class VsaExitedToctouProcess : Process
{{
    public new bool HasExited {{ get {{ return true; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:killed = [System.Collections.Generic.List[int]]::new()
    function New-SnapshotProcess($pid, $parentPid, $created, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$pid
            ParentProcessId = [int]$parentPid
            CreationDate = [datetime]$created
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $pid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        return @(
            (New-SnapshotProcess 4242 100 '2026-07-19T00:00:00Z' 'ui-root'),
            (New-SnapshotProcess 5001 4242 '2026-07-19T00:00:01Z' 'child')
        )
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        [pscustomobject]@{{ Id = $Id; StartTime = [datetime]'2026-07-19T02:00:00Z' }}
    }}
    function Stop-Process {{ param([int]$Id, [switch]$Force, $ErrorAction) $script:killed.Add($Id) | Out-Null }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function cmd.exe {{
        param([Parameter(ValueFromRemainingArguments = $true)][object[]]$NativeArgs)
        if (($NativeArgs -join ' ') -match '/PID (\\d+)') {{ $script:killed.Add([int]$Matches[1]) | Out-Null }}
    }}
    {function}
    $root = [VsaExitedToctouProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
        CreationKey = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks.ToString()
        CreationTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0 }} catch {{ }}
    if ($script:killed.Count -ne 0) {{
        Write-Error "TOCTOU replacement was terminated: $($script:killed -join ',')"
        exit 43
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_normalizes_cim_precision_without_weakening_handle_identity():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
public sealed class VsaPrecisionRootProcess : Process
{{
    public static long StartTicks {{ get; set; }}
    public new IntPtr Handle {{ get {{ return (IntPtr)123; }} }}
    public new bool HasExited {{ get {{ return false; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool CloseMainWindow() {{ return true; }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:childAlive = $true
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $rootCimTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    $childCimTicks = ([datetime]'2026-07-19T00:00:01Z').ToUniversalTime().Ticks
    [VsaPrecisionRootProcess]::StartTicks = $rootCimTicks + 7
    function New-SnapshotProcess($snapshotPid, $snapshotParentPid, $ticks, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$snapshotParentPid
            CreationDate = [datetime]::new([long]$ticks, [DateTimeKind]::Utc)
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $snapshotPid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = @(
            (New-SnapshotProcess 4242 100 $rootCimTicks 'ui-root')
        )
        if ($script:childAlive) {{
            $records += New-SnapshotProcess 5001 4242 $childCimTicks 'bash-child'
        }}
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) |
                Select-Object -First 1
        }}
        return $records
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $target = [pscustomobject]@{{
            Id = $Id
            Handle = [intptr]123
            StartTime = [datetime]::new($childCimTicks + 7, [DateTimeKind]::Utc)
            HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{
            $this.HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:killed.Add($this.Id) | Out-Null
            $script:childAlive = $false
            $this.HasExited = $true
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {function}
    $root = [VsaPrecisionRootProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = $rootCimTicks + 7
        CreationKey = $rootCimTicks.ToString()
        CreationTicks = $rootCimTicks
    }})
    try {{ Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 50 }} catch {{ }}
    if ($script:childAlive -or -not $script:killed.Contains(5001)) {{
        Write-Error 'CIM precision normalization rejected the retained child process handle'
        exit 44
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
@pytest.mark.parametrize(
    ("child_path", "child_command"),
    (("", "bash-child"), ("C:\\fake\\5001.exe", "")),
    ids=("empty-executable-path", "empty-command-line"),
)
def test_powershell_runtime_tracker_and_shutdown_reject_incomplete_descendant_identity(
    child_path: str, child_command: str
):
    functions = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
public sealed class VsaIncompleteIdentityRootProcess : Process
{{
    public static long StartTicks {{ get; set; }}
    public new int Id {{ get {{ return 4242; }} }}
    public new bool HasExited {{ get {{ return true; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:childAlive = $true
    $script:getProcessCalls = 0
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $rootTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    $childTicks = ([datetime]'2026-07-19T00:00:01Z').ToUniversalTime().Ticks
    [VsaIncompleteIdentityRootProcess]::StartTicks = $rootTicks
    function New-SnapshotProcess($snapshotPid, $parentPid, $ticks, $path, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$parentPid
            CreationDate = [datetime]::new([long]$ticks, [DateTimeKind]::Utc)
            ExecutablePath = [string]$path
            CommandLine = [string]$command
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = @(
            (New-SnapshotProcess 4242 100 $rootTicks 'C:\\fake\\root.exe' 'ui-root')
        )
        if ($script:childAlive) {{
            $records += New-SnapshotProcess 5001 4242 $childTicks {child_path!r} {child_command!r}
        }}
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) |
                Select-Object -First 1
        }}
        return $records
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $script:getProcessCalls += 1
        $target = [pscustomobject]@{{
            Id = $Id
            Handle = [intptr]123
            StartTime = [datetime]::new($childTicks, [DateTimeKind]::Utc)
            HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{
            $this.HasExited = -not $script:childAlive
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:killed.Add($this.Id) | Out-Null
            $script:childAlive = $false
            $this.HasExited = $true
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {functions}
    $root = [VsaIncompleteIdentityRootProcess]::new()
    $rootIdentity = [pscustomobject]@{{
        ProcessId = 4242
        ParentProcessId = 100
        CreationKey = $rootTicks.ToString()
        CreationTicks = $rootTicks
        ExecutablePath = 'C:\\fake\\root.exe'
        CommandLine = 'ui-root'
        Depth = 0
        StartTicks = $rootTicks
        BoundProcess = $root
    }}
    $owned = @{{ '4242' = $rootIdentity }}
    $root | Add-Member -NotePropertyName VsaProcessTracker -NotePropertyValue ([pscustomobject]@{{
        Component = 'ui'
        OwnedByPid = $owned
    }})
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = $rootTicks
        CreationKey = $rootTicks.ToString()
        CreationTicks = $rootTicks
    }})
    Update-ProcessTracker -Process $root
    if ($owned.Count -ne 1 -or $script:getProcessCalls -ne 0) {{
        $detail = "runtime tracker accepted incomplete child identity: " +
            "owned=$($owned.Count) handles=$script:getProcessCalls"
        Write-Error $detail
        exit 46
    }}
    Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0
    if ($owned.Count -ne 1 -or $script:killed.Count -ne 0 -or $script:getProcessCalls -ne 0) {{
        $detail = "shutdown accepted incomplete child identity: " +
            "owned=$($owned.Count) killed=$($script:killed.Count) " +
            "handles=$script:getProcessCalls"
        Write-Error $detail
        exit 47
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, "\n".join(completed.stderr.splitlines()[-12:])


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_powershell_shutdown_disposes_rejected_handle_once_when_dispose_throws():
    functions = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
public sealed class VsaDisposeFailureRootProcess : Process
{{
    public static long StartTicks {{ get; set; }}
    public new int Id {{ get {{ return 4242; }} }}
    public new bool HasExited {{ get {{ return true; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return true; }}
}}
'@
    $script:snapshotCalls = 0
    $script:disposeCalls = 0
    $script:killed = [System.Collections.Generic.List[int]]::new()
    $rootTicks = ([datetime]'2026-07-19T00:00:00Z').ToUniversalTime().Ticks
    $childTicks = ([datetime]'2026-07-19T00:00:01Z').ToUniversalTime().Ticks
    [VsaDisposeFailureRootProcess]::StartTicks = $rootTicks
    function New-SnapshotProcess($snapshotPid, $parentPid, $ticks, $path, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$parentPid
            CreationDate = [datetime]::new([long]$ticks, [DateTimeKind]::Utc)
            ExecutablePath = [string]$path
            CommandLine = [string]$command
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $script:snapshotCalls += 1
        $records = @(
            (New-SnapshotProcess 4242 100 $rootTicks 'C:\\fake\\root.exe' 'ui-root')
        )
        if ($script:snapshotCalls -eq 1) {{
            $records += New-SnapshotProcess 5001 4242 $childTicks 'C:\\fake\\child.exe' 'bash-child'
        }}
        return $records
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $target = [pscustomobject]@{{
            Id = $Id
            Handle = [intptr]123
            StartTime = [datetime]::new($childTicks + 10000000, [DateTimeKind]::Utc)
            HasExited = $false
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{ }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:killed.Add($this.Id) | Out-Null
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{
            $script:disposeCalls += 1
            throw 'intentional dispose failure'
        }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {functions}
    $root = [VsaDisposeFailureRootProcess]::new()
    $rootIdentity = [pscustomobject]@{{
        ProcessId = 4242
        ParentProcessId = 100
        CreationKey = $rootTicks.ToString()
        CreationTicks = $rootTicks
        ExecutablePath = 'C:\\fake\\root.exe'
        CommandLine = 'ui-root'
        Depth = 0
        StartTicks = $rootTicks
        BoundProcess = $root
    }}
    $owned = @{{ '4242' = $rootIdentity }}
    $root | Add-Member -NotePropertyName VsaProcessTracker -NotePropertyValue ([pscustomobject]@{{
        Component = 'ui'
        OwnedByPid = $owned
    }})
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = $rootTicks
        CreationKey = $rootTicks.ToString()
        CreationTicks = $rootTicks
    }})
    $caught = $null
    try {{
        Stop-OwnedProcessTree -Component 'ui' -Process $root -ForceTimeoutMs 0
    }} catch {{
        $caught = $_.Exception
    }}
    if ($null -ne $caught) {{
        Write-Error "rejected handle disposal escaped: $($caught.Message)"
        exit 48
    }}
    if ($script:disposeCalls -ne 1) {{
        Write-Error "rejected handle disposed $script:disposeCalls times"
        exit 49
    }}
    if ($owned.Count -ne 1 -or $script:killed.Count -ne 0) {{
        Write-Error "rejected handle was registered or killed: owned=$($owned.Count) killed=$($script:killed.Count)"
        exit 50
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, "\n".join(completed.stderr.splitlines()[-12:])


def test_powershell_shutdown_contract_binds_launch_identity_and_uses_monotonic_sampling():
    launcher = Path("scripts/es-runtime-stack.ps1").read_text(encoding="utf-8")

    assert "VsaLaunchIdentity" in launcher
    assert "[Diagnostics.Stopwatch]::StartNew()" in launcher
    assert "Start-Sleep -Milliseconds 25" not in launcher
    assert "StartTicks" in launcher
    assert "CreationTicks" in launcher


def test_powershell_external_pipeline_stop_runs_launcher_finally_and_cleans_owned_runtime(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-KeepRunning",
        "-TimeoutSec",
        "3",
        exit_after_trace="proxy=ready",
        exit_after_marker="interruption-ready.marker",
        exit_after_stack="READY: isolated validation runtime",
        stop_pipeline_after_trace=True,
    )

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    assert "wrapper=pipeline-stopped" in trace
    assert "harness=forced-cleanup" not in trace
    assert not (repo / "api-exit.trigger").exists()
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker", "ui"}
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}-legacy-smoke" in trace
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}" in trace
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    assert not (run_dir / "config.yaml").exists()
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()
    assert _powershell_repo_processes(repo) == []


def test_powershell_log_pump_avoids_runspace_callbacks_and_exit_code_resets():
    launcher = _powershell()
    log_pump = POWERSHELL_LOG_PUMP.read_text(encoding="utf-8")

    for forbidden in (
        "DataReceivedEventHandler",
        "add_OutputDataReceived",
        "add_ErrorDataReceived",
        "BeginOutputReadLine",
        "BeginErrorReadLine",
        "$global:LASTEXITCODE = 0",
        "[Environment]::ExitCode = 0",
    ):
        assert forbidden not in launcher
    assert "Add-Type -Path $sourcePath" in launcher
    assert "class VsaRuntimeLogPump" in log_pump


def test_powershell_worker_readiness_failure_cleans_started_runtime(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_WORKER_READY"] = "0"

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-SmokeOnly",
        "-TimeoutSec",
        "2",
    )

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    assert all(item["exit_status"] is not None for item in manifest["processes"])
    assert not (run_dir / "validation-config.yaml").exists()


def test_powershell_validation_failure_cleans_resources_and_finalizes_manifest(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_STATUS"] = "17"

    completed = _run_powershell_runtime(
        repo,
        env,
        "-Validate",
        "-SmokeOnly",
        "-TimeoutSec",
        "3",
    )

    assert completed.returncode != 0
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    validation_root = run_dir / f"validation-{run_dir.name}"
    validation_marker = validation_root / "interruption-ready.marker"
    assert f"delete=http://127.0.0.1:9200/validation-{run_dir.name}-legacy-smoke" in trace
    assert not validation_root.exists()
    assert not validation_marker.exists()
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / "config.yaml").exists()
    assert manifest["processes"]
    assert all(item["exit_status"] is not None for item in manifest["processes"])


def test_powershell_normal_start_never_invokes_validation_smoke(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_API_EXIT_AFTER_MS"] = "1000"

    completed = _run_powershell_runtime(repo, env, "-TimeoutSec", "3")

    assert completed.returncode != 0
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" not in trace
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8-sig"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker", "ui"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])


def test_launchers_create_uuid_run_evidence_and_latest_pointer():
    bash = _bash()
    powershell = _powershell()

    assert re.search(r"RUN_ID=.*uuid", bash, flags=re.IGNORECASE)
    assert 'RUNS_DIR="$RUNTIME_DIR/runs"' in bash
    assert 'RUN_DIR="$RUNS_DIR/$RUN_ID"' in bash
    assert "ln -sfn" in bash
    assert "[guid]::NewGuid()" in powershell
    assert 'Join-Path $runtimeDir "runs"' in powershell
    assert "Join-Path $runsDir $runId" in powershell
    assert "-ItemType Junction" in powershell

    for name in ("stack.log", "api.log", "worker.log", "ui.log", "es.log", "processes.json"):
        assert name in bash
        assert name in powershell


def test_latest_pointer_replacement_does_not_delete_prior_run_evidence():
    bash = _bash()
    powershell = _powershell()

    assert 'rm -rf -- "$LATEST_LINK"' not in bash
    assert 'rm -f -- "$LATEST_LINK"' in bash
    latest_removal = next(line for line in powershell.splitlines() if "Remove-Item" in line and "$latestLink" in line)
    assert "-Recurse" not in latest_removal
    assert "LATEST_POINTER_CONFLICT" in bash
    assert "LATEST_POINTER_CONFLICT" in powershell


def test_launchers_record_managed_process_identity_and_final_status_without_secrets():
    for text in (_bash(), _powershell()):
        for field in ("pid", "command", "started_at", "exit_status"):
            assert field in text
        assert "processes.json" in text
        assert "Authorization" not in text
        assert "api_key" not in text.lower()
        assert "video bytes" not in text.lower()


def test_launchers_start_components_in_required_readiness_order():
    _ordered(
        _bash(),
        "--phase static",
        "docker compose -f docker-compose.es.yml up -d",
        "--phase elasticsearch",
        "wait_http_health",
        "wait_worker_ready",
        "wait_ui_health",
        "wait_same_origin_proxy",
    )
    _ordered(
        _powershell(),
        '"--phase", "static"',
        "es-dev-start.ps1",
        '"--phase", "elasticsearch"',
        "Wait-HttpHealth",
        "Wait-WorkerReady",
        "Wait-UiReady",
        "Wait-SameOriginProxy",
    )


def test_launchers_start_recorded_video_worker_and_parse_json_readiness():
    for text in (_bash(), _powershell()):
        assert "recorded-video-worker.py" in text
        assert "worker.readiness" in text
        assert 'payload.get("ready")' in text or "payload.ready" in text
        assert "worker.log" in text


def test_normal_start_does_not_invoke_ingest_smoke_and_validation_is_isolated():
    bash = _bash()
    powershell = _powershell()

    assert bash.count("es_ingest_smoke.py") == 1
    assert "es_ingest_smoke.py" in _conditional_block(
        bash,
        'if [[ "$VALIDATE" == "1" ]]',
        "fi # validation",
    )
    assert powershell.count("es_ingest_smoke.py") == 1
    assert "es_ingest_smoke.py" in _conditional_block(
        powershell,
        "if ($Validate) { # validation",
        "} # validation",
    )

    for text in (bash, powershell):
        assert "validation-" in text
        assert "DeleteValidation" in text or "delete_validation" in text
        assert "Remove-Item" in text or "rm -rf" in text


def test_validation_targets_the_legacy_smoke_index_created_by_the_ingest_api():
    bash = _bash()
    powershell = _powershell()

    assert 'VALIDATION_SMOKE_INDEX="${VALIDATION_INDEX}-legacy-smoke"' in bash
    assert '--index "$VALIDATION_SMOKE_INDEX"' in bash
    assert 'curl -fsS "$ES_ENDPOINT/_alias/$VALIDATION_INDEX"' in bash
    assert 'curl -fsS "$ES_ENDPOINT/_cat/indices/${VALIDATION_INDEX}-*?h=index"' in bash
    assert 'for validation_resource in "$VALIDATION_SMOKE_INDEX" $validation_indices; do' in bash
    assert '"$ES_ENDPOINT/$validation_resource"' in bash
    assert '$validationSmokeIndex = "$validationIndex-legacy-smoke"' in powershell
    assert '"--index", $validationSmokeIndex' in powershell
    assert "foreach ($validationResource in @($validationSmokeIndex, $validationIndex))" in powershell
    assert '"$esEndpoint/$validationResource"' in powershell


def test_launchers_only_reclaim_listeners_verified_as_current_user():
    bash = _bash()
    powershell = _powershell()

    assert "assert_current_user_pid" in bash
    assert "ps -p" in bash and "-o uid=" in bash
    assert "FOREIGN_LISTENER" in bash
    assert "sudo" not in bash

    assert "Assert-CurrentUserProcess" in powershell
    assert "GetOwner" in powershell
    assert "FOREIGN_LISTENER" in powershell
    assert "sudo" not in powershell


def test_component_output_is_aggregated_with_required_prefixes():
    bash = _bash()
    powershell = _powershell()
    powershell_log_pump = POWERSHELL_LOG_PUMP.read_text(encoding="utf-8")

    assert "[stack]" in bash
    assert "runtime-log-supervisor.py" in bash
    assert "--label" in bash
    assert "--component-log" in bash
    assert "redact_component_output" not in bash
    assert "> >(redact" not in bash
    assert "sed -u" not in bash

    assert "[stack]" in powershell
    assert '"[$Component]"' in powershell
    assert "PublishProtected" in powershell_log_pump
    for component in ("api", "worker", "ui", "es"):
        assert f'-Component "{component}"' in powershell


def test_process_manifest_example_schema_is_valid_json():
    manifest = {
        "run_id": "00000000-0000-4000-8000-000000000000",
        "processes": [
            {
                "component": "worker",
                "pid": 123,
                "command": "python scripts/recorded-video-worker.py --config <runtime-config>",
                "started_at": "2026-07-15T00:00:00Z",
                "exit_status": None,
            }
        ],
    }

    assert json.loads(json.dumps(manifest))["processes"][0]["component"] == "worker"


def test_validation_worker_uses_the_same_isolated_config_as_the_api():
    text = _bash()
    selection = next(
        line for line in text.splitlines() if "API_CONFIG_PATH=" in line and "VALIDATION_CONFIG_PATH" in line
    )
    worker_line = next(
        line
        for line in text.splitlines()
        if "recorded-video-worker.py --config" in line and '"$API_CONFIG_PATH"' in line
    )
    match = re.search(r'--config "(\$[A-Z_]+)"', worker_line)
    assert match is not None
    selected_worker_config = match.group(1)
    probe = f"""
    set -eu
    VALIDATE=1
    CONFIG_PATH=/production/config.yaml
    VALIDATION_CONFIG_PATH=/isolated/validation-config.yaml
    API_CONFIG_PATH="$CONFIG_PATH"
    {selection}
    printf '%s\n%s\n' "$API_CONFIG_PATH" "{selected_worker_config}"
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "/isolated/validation-config.yaml",
        "/isolated/validation-config.yaml",
    ]


def test_powershell_managed_process_parameter_does_not_collide_with_pid_automatic_variable():
    function = _powershell_function("Add-ManagedProcess")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $script:manifest = [ordered]@{{ processes = @() }}
    function Write-ProcessManifest {{ }}
    {function}
    Add-ManagedProcess -Component worker -ProcessId 4321 -SafeCommand worker
    if ($script:manifest.processes[0].pid -ne 4321) {{ exit 3 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_bash_managed_process_shutdown_is_bounded_and_forces_a_stubborn_child():
    functions = "\n".join(
        _bash_function(name)
        for name in ("pid_is_running", "signal_process_tree", "stop_pid_bounded", "stop_managed_process")
    )
    probe = f"""
    set -u
    PROCESS_SHUTDOWN_GRACE_TICKS=3
    declare -A PROCESS_PIDS=()
    declare -A PROCESS_PENDING_EXIT_STATUS=()
    record_process_exit() {{ :; }}
    {functions}
    bash -c 'trap "" TERM; exec sleep 30' &
    PROCESS_PIDS[worker]=$!
    stop_managed_process worker
    """
    started = time.monotonic()

    completed = _run_bash_probe(probe)

    assert time.monotonic() - started < 5.0
    assert completed.returncode == 0, completed.stderr


def test_bash_validation_delete_failure_propagates_nonzero_after_local_cleanup(tmp_path: Path):
    function = _bash_function("delete_validation_resources")
    validation_root = tmp_path / "validation-data"
    validation_root.mkdir()
    config = tmp_path / "config.yaml"
    validation_config = tmp_path / "validation-config.yaml"
    config.touch()
    validation_config.touch()
    probe = f"""
    VALIDATE=1
    ES_ENDPOINT=http://127.0.0.1:9200
    VALIDATION_SMOKE_INDEX=validation-test-legacy-smoke
    VALIDATION_DATA_ROOT='{validation_root}'
    VALIDATION_CONFIG_PATH='{validation_config}'
    CONFIG_PATH='{config}'
    VALIDATION_INDEX=validation-test
    log_stack() {{ :; }}
    curl() {{ return 22; }}
    {function}
    delete_validation_resources
    """

    completed = _run_bash_probe(probe)

    assert completed.returncode != 0
    assert not validation_root.exists()
    assert not config.exists()
    assert not validation_config.exists()


@pytest.mark.parametrize(
    ("function_loader", "probe_runner", "probe"),
    [
        (
            lambda: _powershell_function("Protect-RuntimeText"),
            _run_powershell_probe,
            "Protect-RuntimeText 'Authorization: Bearer top-secret'",
        ),
    ],
    ids=("powershell",),
)
def test_runtime_redactor_hides_header_token_and_image_payload(
    function_loader: object,
    probe_runner: object,
    probe: str,
):
    function = function_loader()  # type: ignore[operator]
    completed = probe_runner(f"{function}\n{probe}")  # type: ignore[operator]

    assert completed.returncode == 0, completed.stderr
    assert "top-secret" not in completed.stdout
    assert "[REDACTED]" in completed.stdout


@pytest.mark.parametrize("launcher", ["powershell"])
def test_runtime_redactor_covers_quoted_json_secrets_and_multiline_image_payload(launcher: str):
    first_chunk = "A" * 96
    second_chunk = "B" * 96
    payload = (
        '{"Authorization":"Bearer json-auth-secret","api_key":"json-api-secret",'
        '"token":"json-token-secret","password":"json-password-secret",'
        f'"image":"data:image/png;base64,\n{first_chunk}\n{second_chunk}"}}'
    )
    function = _powershell_function("Protect-RuntimeText")
    escaped = payload.replace("'", "''")
    completed = _run_powershell_probe(f"{function}\nProtect-RuntimeText @'\n{escaped}\n'@")

    assert completed.returncode == 0, completed.stderr
    for secret in (
        "json-auth-secret",
        "json-api-secret",
        "json-token-secret",
        "json-password-secret",
        first_chunk,
        second_chunk,
    ):
        assert secret not in completed.stdout
    assert "[REDACTED" in completed.stdout


def test_powershell_shutdown_does_not_block_on_a_stubborn_process():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function cmd.exe {{ $global:LASTEXITCODE = 0 }}
    {function}
    $child = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 2') -PassThru
    $childId = $child.Id
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $stopArgs = @{{ Component = 'worker'; Process = $child; GraceTimeoutMs = 100; ForceTimeoutMs = 100 }}
    try {{ Stop-OwnedProcessTree @stopArgs }} catch {{ }}
    $watch.Stop()
    if (Get-Process -Id $childId -ErrorAction SilentlyContinue) {{ Stop-Process -Id $childId -Force }}
    if ($watch.ElapsedMilliseconds -ge 1000) {{ exit 8 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process lineage contract")
def test_powershell_shutdown_rescans_late_owned_descendant_before_log_pump_complete():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;

public sealed class VsaRescanRootProcess : Process
{{
    public static bool RootExited {{ get; set; }}
    public static long StartTicks {{ get; set; }}
    public new IntPtr Handle {{ get {{ return (IntPtr)123; }} }}
    public new bool HasExited {{ get {{ return RootExited; }} }}
    public new int Id {{ get {{ return 4242; }} }}
    public new int ExitCode {{ get {{ return 0; }} }}
    public new DateTime StartTime {{ get {{ return new DateTime(StartTicks, DateTimeKind.Utc); }} }}
    public new void Refresh() {{ }}
    public new bool CloseMainWindow() {{ return false; }}
    public new void Kill() {{ RootExited = true; }}
    public new bool WaitForExit(int milliseconds) {{ return RootExited; }}
}}
'@
    [VsaRescanRootProcess]::RootExited = $false
    $script:stage = 0
    $script:lateDescendantAlive = $true
    $script:ownedParentAlive = $true
    $script:rescanKilled = [System.Collections.Generic.List[int]]::new()
    [VsaRescanRootProcess]::StartTicks = ([datetime]'2026-01-01T00:00:00Z').ToUniversalTime().Ticks
    function New-SnapshotProcess($snapshotPid, $snapshotParentPid, $created, $command) {{
        [pscustomobject]@{{
            ProcessId = [int]$snapshotPid
            ParentProcessId = [int]$snapshotParentPid
            CreationDate = [datetime]$created
            CommandLine = [string]$command
            ExecutablePath = 'C:\\fake\\' + $snapshotPid + '.exe'
        }}
    }}
    function Get-CimInstance {{
        param($ClassName, $Filter, $ErrorAction)
        $records = if ($script:stage -eq 0) {{
            @(
                (New-SnapshotProcess 4242 100 '2026-01-01T00:00:00Z' 'ui-root'),
                (New-SnapshotProcess 5001 4242 '2026-01-01T00:00:01Z' 'bash-old')
            )
        }} elseif ($script:lateDescendantAlive -or $script:ownedParentAlive) {{
            $lateRecords = @()
            if ($script:ownedParentAlive) {{
                $lateRecords += New-SnapshotProcess 5001 4242 '2026-01-01T00:00:01Z' 'bash-old'
            }}
            if ($script:lateDescendantAlive) {{
                $lateRecords += New-SnapshotProcess 5002 5001 '2026-01-01T00:00:02Z' 'bash-new-pipe-holder'
            }}
            $lateRecords += New-SnapshotProcess 4242 999 '2026-01-01T00:01:00Z' 'reused-unrelated-root'
            $lateRecords += New-SnapshotProcess 6000 4242 '2026-01-01T00:01:01Z' 'unrelated-child'
            $lateRecords
        }} else {{
            @(
                (New-SnapshotProcess 4242 999 '2026-01-01T00:01:00Z' 'reused-unrelated-root'),
                (New-SnapshotProcess 6000 4242 '2026-01-01T00:01:01Z' 'unrelated-child')
            )
        }}
        if ("$Filter" -match 'ProcessId=(\\d+)') {{
            $lookupPid = [int]$Matches[1]
            return @($records | Where-Object {{ [int]$_.ProcessId -eq $lookupPid }}) | Select-Object -First 1
        }}
        if ($script:stage -eq 0) {{ $script:stage = 1 }}
        return $records
    }}
    function cmd.exe {{
        param([Parameter(ValueFromRemainingArguments = $true)][object[]]$NativeArgs)
        $line = $NativeArgs -join ' '
        if ($script:stage -eq 0 -and $line -match '/PID 4242(?:\\s|$)') {{
            [VsaRescanRootProcess]::RootExited = $true
            $script:stage = 1
            return
        }}
        if ($line -match '/PID (\\d+)') {{
            $killedPid = [int]$Matches[1]
            $script:rescanKilled.Add($killedPid) | Out-Null
            if ($killedPid -eq 5002) {{ $script:lateDescendantAlive = $false }}
        }}
    }}
    function Stop-Process {{
        param([int]$Id, [switch]$Force, $ErrorAction)
        $script:rescanKilled.Add($Id) | Out-Null
        if ($Id -eq 5002) {{ $script:lateDescendantAlive = $false }}
    }}
    function Get-Process {{
        param([int]$Id, $ErrorAction)
        $startTime = if ($Id -eq 5002) {{
            [datetime]'2026-01-01T00:00:02Z'
        }} else {{
            [datetime]'2026-01-01T00:00:01Z'
        }}
        $target = [pscustomobject]@{{ Id = $Id; Handle = [intptr]123; StartTime = $startTime; HasExited = $false }}
        $target | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{ }}
        $target | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
            $script:rescanKilled.Add($this.Id) | Out-Null
            if ($this.Id -eq 5002) {{ $script:lateDescendantAlive = $false }}
            if ($this.Id -eq 5001) {{ $script:ownedParentAlive = $false }}
            $this.HasExited = $true
        }}
        $target | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
        return $target
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {function}
    $pump = [pscustomobject]@{{ CompleteCalled = $false; DisposeCalled = $false }}
    $pump | Add-Member -MemberType ScriptMethod -Name Complete -Value {{
        param($milliseconds)
        if ($script:lateDescendantAlive) {{ throw 'log pump drain timed out while owned descendant holds pipe' }}
        $this.CompleteCalled = $true
    }}
    $pump | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ $this.DisposeCalled = $true }}
    $root = [VsaRescanRootProcess]::new()
    $root | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
        ProcessId = 4242
        StartTicks = ([datetime]'2026-01-01T00:00:00Z').ToUniversalTime().Ticks
        CreationKey = ([datetime]'2026-01-01T00:00:00Z').ToUniversalTime().Ticks.ToString()
        CreationTicks = ([datetime]'2026-01-01T00:00:00Z').ToUniversalTime().Ticks
    }})
    $root | Add-Member -NotePropertyName VsaLogPump -NotePropertyValue $pump
    $failure = $null
    $survivedAtComplete = $false
    try {{
        $stopArgs = @{{ Component = 'ui'; Process = $root; GraceTimeoutMs = 25; ForceTimeoutMs = 250 }}
        Stop-OwnedProcessTree @stopArgs -LogDrainTimeoutMs 25
    }} catch {{
        $failure = $_.Exception.Message
        $survivedAtComplete = $script:lateDescendantAlive
    }} finally {{
        $script:lateDescendantAlive = $false
    }}
    if ($null -ne $failure) {{
        Write-Error "STOP_ERROR=$failure OWNED_DESCENDANT_SURVIVED=$survivedAtComplete"
        exit 41
    }}
    if (-not $pump.CompleteCalled -or -not $pump.DisposeCalled) {{ exit 42 }}
    if (-not $script:rescanKilled.Contains(5002)) {{ exit 43 }}
    if ($script:rescanKilled.Contains(4242) -or $script:rescanKilled.Contains(6000)) {{ exit 44 }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_forced_shutdown_timeout_still_finalizes_owned_process():
    function = _powershell_shutdown_functions()
    probe = f"""
    $ErrorActionPreference = 'Stop'
    Add-Type -TypeDefinition @'
using System.Diagnostics;

public sealed class VsaForcedTimeoutProcess : Process
{{
    public bool DisposedCalled {{ get; private set; }}
    public new bool HasExited {{ get {{ return false; }} }}
    public new int Id {{ get {{ return 424242; }} }}
    public new int ExitCode {{ get {{ return 23; }} }}
    public new void Refresh() {{ }}
    public new bool WaitForExit(int milliseconds) {{ return false; }}
    protected override void Dispose(bool disposing)
    {{
        DisposedCalled = true;
        base.Dispose(disposing);
    }}
}}

public sealed class VsaProbeLogPump
{{
    public bool CompleteCalled {{ get; private set; }}
    public bool DisposeCalled {{ get; private set; }}
    public void Complete(int milliseconds) {{ CompleteCalled = true; }}
    public void Dispose() {{ DisposeCalled = true; }}
}}
'@
    $script:exitStatus = $null
    function cmd.exe {{ $global:LASTEXITCODE = 0 }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) $script:exitStatus = $ExitStatus }}
    {function}
    $child = [VsaForcedTimeoutProcess]::new()
    $pump = [VsaProbeLogPump]::new()
    $child | Add-Member -NotePropertyName VsaLogPump -NotePropertyValue $pump
    try {{
        Stop-OwnedProcessTree -Component 'worker' -Process $child -GraceTimeoutMs 0 -ForceTimeoutMs 0
        exit 21
    }} catch {{
        if ($_.Exception.Message -notmatch 'forced shutdown') {{ exit 22 }}
    }}
    if (-not $pump.CompleteCalled) {{ exit 23 }}
    if (-not $pump.DisposeCalled) {{ exit 24 }}
    if (-not $child.DisposedCalled) {{ exit 25 }}
    if ([string]::IsNullOrWhiteSpace("$script:exitStatus")) {{ exit 26 }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_log_pump_drains_bounded_stdout_and_stderr_without_secret_leaks(tmp_path: Path):
    functions = "\n".join(
        _powershell_function(name)
        for name in ("Protect-RuntimeText", "ConvertTo-NativeArgument", "Start-LoggedProcess", "Stop-OwnedProcessTree")
    )
    component_log = tmp_path / "component.log"
    stack_log = tmp_path / "stack.log"
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $stackLogPath = '{stack_log}'
    function Add-ManagedProcess {{ }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {functions}
    $null = Protect-RuntimeText ''
    $command = @'
1..2000 | ForEach-Object {{
    [Console]::Out.WriteLine("stdout-$($_) token=stdout-secret")
    [Console]::Error.WriteLine("stderr-$($_) password=stderr-secret")
}}
'@
    $child = Start-LoggedProcess -Component 'probe' -FilePath 'powershell' `
        -Arguments @('-NoProfile', '-NonInteractive', '-Command', $command) `
        -WorkingDirectory '{tmp_path}' -LogPath '{component_log}' -SafeCommand 'probe' -Record:$false
    if (-not $child.WaitForExit(10000)) {{ throw 'child output blocked' }}
    Stop-OwnedProcessTree -Component 'probe' -Process $child -LogDrainTimeoutMs 10000
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr
    component = component_log.read_text(encoding="utf-8")
    stack = stack_log.read_text(encoding="utf-8")
    assert "stdout-2000 token=[REDACTED]" in component
    assert "stderr-2000 password=[REDACTED]" in component
    assert "[probe] stdout-2000 token=[REDACTED]" in stack
    assert "[probe] stderr-2000 password=[REDACTED]" in stack
    assert "stdout-secret" not in component + stack
    assert "stderr-secret" not in component + stack


def test_powershell_validation_delete_failure_is_reported_after_local_cleanup(tmp_path: Path):
    function = _powershell_function("DeleteValidationResources")
    validation_root = tmp_path / "ps-validation-data"
    validation_root.mkdir()
    config = tmp_path / "ps-config.yaml"
    validation_config = tmp_path / "ps-validation-config.yaml"
    config.touch()
    validation_config.touch()
    probe = f"""
    $Validate = $true
    $esEndpoint = 'http://127.0.0.1:9200'
    $validationSmokeIndex = 'validation-test-legacy-smoke'
    $validationDataRoot = '{validation_root}'
    $validationConfigPath = '{validation_config}'
    $configPath = '{config}'
    $validationIndex = 'validation-test'
    function Write-Stack {{ param($Message, [switch]$ErrorLine) }}
    function Invoke-WebRequest {{ throw 'delete failed' }}
    {function}
    $removed = DeleteValidationResources
    if ($removed -ne $false) {{ exit 9 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr
    assert not validation_root.exists()
    assert not config.exists()
    assert not validation_config.exists()


def test_powershell_validation_local_delete_failure_continues_and_names_failed_path(tmp_path: Path):
    function = _powershell_function("DeleteValidationResources")
    validation_root = tmp_path / "blocked-validation-data"
    config = tmp_path / "config.yaml"
    validation_config = tmp_path / "validation-config.yaml"
    probe = f"""
    $Validate = $true
    $esEndpoint = 'http://127.0.0.1:9200'
    $validationSmokeIndex = 'validation-test-legacy-smoke'
    $validationDataRoot = '{validation_root}'
    $validationConfigPath = '{validation_config}'
    $configPath = '{config}'
    $validationIndex = 'validation-test'
    $script:removedPaths = [System.Collections.Generic.List[string]]::new()
    $script:messages = [System.Collections.Generic.List[string]]::new()
    function Write-Stack {{ param($Message, [switch]$ErrorLine) $script:messages.Add("$Message") }}
    function Invoke-WebRequest {{ }}
    function Test-Path {{ return $true }}
    function Remove-Item {{
        param($LiteralPath, [switch]$Force, [switch]$Recurse, $ErrorAction)
        foreach ($path in @($LiteralPath)) {{
            if ($path -eq $validationDataRoot) {{ throw "blocked $path" }}
            $script:removedPaths.Add("$path") | Out-Null
        }}
    }}
    {function}
    $removed = DeleteValidationResources
    if ($removed -ne $false) {{ exit 11 }}
    if (-not $script:removedPaths.Contains($validationConfigPath)) {{ exit 12 }}
    if (-not $script:removedPaths.Contains($configPath)) {{ exit 13 }}
    if (($script:messages -join "`n") -notmatch [regex]::Escape($validationDataRoot)) {{ exit 14 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("owner_case", ["missing", "wrong-domain"])
def test_powershell_process_ownership_fails_closed_for_missing_or_cross_domain_owner(owner_case: str):
    function = _powershell_function("Assert-CurrentUserProcess")
    setup = (
        "function Get-CimInstance { return $null }"
        if owner_case == "missing"
        else """
        function Get-CimInstance { [pscustomobject]@{ ProcessId = 4321; CreationDate = 'start-a' } }
        function Invoke-CimMethod {
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
            $user = if ($identity.Contains('\\')) { $identity.Split('\\', 2)[1] } else { $identity }
            [pscustomobject]@{ ReturnValue = 0; User = $user; Domain = 'definitely-not-current-domain' }
        }
        """
    )
    probe = f"""
    $ErrorActionPreference = 'Stop'
    {setup}
    {function}
    try {{ Assert-CurrentUserProcess -ProcessId 4321; exit 7 }} catch {{ exit 0 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_rechecks_process_identity_immediately_before_termination():
    function = _powershell_function("Reclaim-Port")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $script:checks = 0
    $script:listener = [pscustomobject]@{{
        Id = 4321
        Handle = [intptr]123
        StartTime = [datetime]'2026-07-19T02:00:00Z'
        HasExited = $false
        KillCalled = $false
    }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{ }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
        $this.KillCalled = $true
        $this.HasExited = $true
    }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
    function Get-NetTCPConnection {{ [pscustomobject]@{{ OwningProcess = 4321 }} }}
    function Assert-CurrentUserProcess {{
        param($ProcessId, $ExpectedCreationDate)
        $script:checks++
        return [pscustomobject]@{{ CreationDate = 'identity-token' }}
    }}
    function Get-Process {{ param($Id, $ErrorAction) return $script:listener }}
    function Write-Stack {{ }}
    function taskkill.exe {{ throw 'PID-only taskkill must not be used' }}
    function Wait-PortFree {{ }}
    {function}
    Reclaim-Port -Port 8000 -TimeoutSec 1
    if ($script:checks -lt 2) {{ exit 6 }}
    if (-not $script:listener.KillCalled) {{ exit 7 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_reclaim_port_refuses_start_time_toctou_mismatch():
    function = _powershell_function("Reclaim-Port")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $script:refreshes = 0
    $script:listener = [pscustomobject]@{{
        Id = 4321
        Handle = [intptr]123
        StartTime = [datetime]'2026-07-19T02:00:00Z'
        HasExited = $false
        KillCalled = $false
    }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{
        $script:refreshes++
        if ($script:refreshes -ge 2) {{
            $this.StartTime = [datetime]'2026-07-19T02:00:01Z'
        }}
    }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Kill -Value {{
        $this.KillCalled = $true
        $this.HasExited = $true
    }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ }}
    $script:listener | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ }}
    function Get-NetTCPConnection {{ [pscustomobject]@{{ OwningProcess = 4321 }} }}
    function Get-Process {{ param($Id, $ErrorAction) return $script:listener }}
    function Assert-CurrentUserProcess {{
        param($ProcessId, $ExpectedCreationDate, $ExpectedExecutablePath, $ExpectedCommandLine)
        if ($null -ne $ExpectedCreationDate) {{
            if ($ExpectedCreationDate -ne 'identity-token' -or
                $ExpectedExecutablePath -ne 'C:\\runtime\\listener.exe' -or
                $ExpectedCommandLine -ne 'listener --port 8000') {{
                throw 'CIM identity fields must be revalidated together'
            }}
        }}
        return [pscustomobject]@{{
            CreationDate = 'identity-token'
            ExecutablePath = 'C:\\runtime\\listener.exe'
            CommandLine = 'listener --port 8000'
        }}
    }}
    function Write-Stack {{ }}
    function taskkill.exe {{ throw 'PID-only taskkill must not be used' }}
    function Wait-PortFree {{ }}
    {function}
    try {{
        Reclaim-Port -Port 8000 -TimeoutSec 1
        exit 5
    }} catch {{
        if ($_.Exception.Message -notmatch 'PID_REUSED') {{
            Write-Output "UNEXPECTED_ERROR=$($_.Exception.Message)"
            exit 6
        }}
    }}
    if ($script:listener.KillCalled) {{ exit 7 }}
    Write-Output 'probe completed'
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_start_logged_process_cleans_up_when_manifest_handoff_fails(tmp_path: Path):
    functions = "\n".join(
        _powershell_function(name)
        for name in ("Protect-RuntimeText", "ConvertTo-NativeArgument", "Start-LoggedProcess")
    )
    stack_log = tmp_path / "stack.log"
    component_log = tmp_path / "component.log"
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $stackLogPath = '{stack_log}'
    $script:startedPid = $null
    function Add-ManagedProcess {{
        param($Component, $ProcessId, $SafeCommand)
        $script:startedPid = $ProcessId
        throw 'manifest handoff failed'
    }}
    {functions}
    $null = Protect-RuntimeText ''
    try {{
        Start-LoggedProcess -Component 'probe' -FilePath 'powershell' `
            -Arguments @('-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30') `
            -WorkingDirectory '{tmp_path}' -LogPath '{component_log}' -SafeCommand 'probe' | Out-Null
        exit 5
    }} catch {{
        if ($_.Exception.Message -notmatch 'manifest handoff failed') {{
            Write-Error $_
            exit 6
        }}
    }} finally {{
        if ($null -ne $script:startedPid) {{
            $survivor = Get-Process -Id $script:startedPid -ErrorAction SilentlyContinue
            if ($null -ne $survivor) {{
                try {{ $survivor.Kill(); $survivor.WaitForExit(5000) }} finally {{ $survivor.Dispose() }}
                exit 7
            }}
        }}
    }}
    Write-Output 'probe completed'
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_runtime_monitor_detects_api_exit_while_ui_and_worker_continue():
    function = _powershell_function("Wait-RuntimeProcesses")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    function Get-CimInstance {{ return @() }}
    function Update-ProcessTracker {{ param($Process, $Snapshot) }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    {function}
    $api = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'exit 7') -PassThru
    $worker = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru
    $ui = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru
    try {{
        Wait-RuntimeProcesses -Processes @{{ api = $api; worker = $worker; ui = $ui }} -PollMilliseconds 25
        exit 5
    }} catch {{
        if ($_.Exception.Message -notmatch 'api') {{ exit 4 }}
    }} finally {{
        foreach ($child in @($worker, $ui)) {{ if (-not $child.HasExited) {{ Stop-Process -Id $child.Id -Force }} }}
    }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_runtime_monitor_shares_one_cim_snapshot_per_poll():
    function = _powershell_function("Wait-RuntimeProcesses")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    $script:snapshotCalls = 0
    $script:trackerCalls = 0
    function Get-CimInstance {{
        param($ClassName, $ErrorAction)
        $script:snapshotCalls += 1
        return @([pscustomobject]@{{ ProcessId = 1 }})
    }}
    function Update-ProcessTracker {{
        param($Process, $Snapshot)
        if (-not $PSBoundParameters.ContainsKey('Snapshot')) {{
            throw 'runtime tracker did not receive shared snapshot'
        }}
        $script:trackerCalls += 1
    }}
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function Start-Sleep {{ throw 'poll-complete' }}
    {function}
    $children = @(
        (Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru),
        (Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru),
        (Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru)
    )
    try {{
        Wait-RuntimeProcesses -Processes @{{ api = $children[0]; worker = $children[1]; ui = $children[2] }}
        exit 5
    }} catch {{
        if ($_.Exception.Message -notmatch 'poll-complete') {{
            Write-Error $_
            exit 6
        }}
    }} finally {{
        foreach ($child in $children) {{
            if (-not $child.HasExited) {{ Stop-Process -Id $child.Id -Force }}
        }}
    }}
    if ($script:snapshotCalls -ne 1 -or $script:trackerCalls -ne 3) {{
        Write-Error "unexpected runtime polling cost: snapshots=$script:snapshotCalls trackers=$script:trackerCalls"
        exit 7
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, "\n".join(completed.stderr.splitlines()[-12:])


def test_powershell_process_tracker_rejects_explicit_empty_snapshot():
    functions = "\n\n".join(
        _powershell_function(name)
        for name in (
            "ConvertTo-TrackedProcessIdentity",
            "Test-TrackedProcessIdentity",
            "Update-ProcessTracker",
        )
    )
    probe = f"""
    $ErrorActionPreference = 'Stop'
    {functions}
    $child = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep 10') -PassThru
    try {{
        $startTicks = $child.StartTime.ToUniversalTime().Ticks
        $child | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{{
            ProcessId = $child.Id
            StartTicks = $startTicks
            CreationKey = $startTicks.ToString()
            CreationTicks = $startTicks
        }})
        $child | Add-Member -NotePropertyName VsaProcessTracker -NotePropertyValue ([pscustomobject]@{{
            Component = 'api'
            OwnedByPid = @{{ 'seed' = [pscustomobject]@{{ ProcessId = $child.Id; Depth = 0 }} }}
        }})
        try {{
            Update-ProcessTracker -Process $child -Snapshot @()
            exit 5
        }} catch {{
            if ($_.Exception.Message -notmatch 'snapshot.*empty') {{
                Write-Error $_
                exit 6
            }}
        }}
    }} finally {{
        if (-not $child.HasExited) {{ Stop-Process -Id $child.Id -Force }}
        $child.Dispose()
    }}
    exit 0
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, "\n".join(completed.stderr.splitlines()[-12:])
