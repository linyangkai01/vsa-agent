from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")
POWERSHELL_SCRIPT = Path("scripts/es-runtime-stack.ps1")


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


def _run_bash_probe(body: str, *, timeout: float = 5) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    return subprocess.run(
        [bash, "-c", body],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
    (repo / "config.yaml").write_text(
        """search:\n  enabled: false\nrecorded_video:\n  enabled: true\n  data_root: .runtime/recorded-video\n""",
        encoding="utf-8",
    )
    _write_executable(
        fake_bin / "setsid",
        """
        #!/usr/bin/env bash
        exec "$@"
        """,
    )
    _write_executable(
        fake_bin / "lsof",
        """
        #!/usr/bin/env bash
        if [[ -n "${HARNESS_FOREIGN_PID:-}" ]]; then printf '%s\n' "$HARNESS_FOREIGN_PID"; fi
        """,
    )
    _write_executable(
        fake_bin / "docker",
        """
        #!/usr/bin/env bash
        printf 'docker=%s\n' "$*" >>"$HARNESS_TRACE"
        if [[ "$1" == "inspect" && "$*" == *State.Running* ]]; then echo true; exit 0; fi
        if [[ "$1" == "inspect" && "$*" == *State.Pid* ]]; then echo 987654; exit 0; fi
        if [[ "$1" == "compose" && "$*" == *"logs"* ]]; then
          echo 'Authorization: Bearer es-secret'
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
          if [[ "${HARNESS_DELETE_FAIL:-0}" == "1" ]]; then exit 22; fi
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
          "$REAL_PYTHON" "$@" <"$probe"
          status=$?
          rm -f "$probe"
          exit "$status"
        fi
        if [[ "$1" == "-c" ]]; then exec "$REAL_PYTHON" "$@"; fi
        if [[ "$1" == "scripts/runtime-doctor.py" ]]; then
          echo 'api_key=doctor-secret'
          exit 0
        fi
        if [[ "$1" == "-m" && "$2" == "uvicorn" ]]; then
          printf 'api_config=%s\n' "$VSA_CONFIG" >>"$HARNESS_TRACE"
          echo 'Authorization: Bearer api-secret'
          trap 'exit 0' TERM INT
          while :; do sleep 0.1; done
        fi
        if [[ "$1" == "scripts/recorded-video-worker.py" ]]; then
          shift
          [[ "$1" == "--config" ]]
          printf 'worker_config=%s\n' "$2" >>"$HARNESS_TRACE"
          cp "$2" "$HARNESS_TRACE.config"
          grep -E 'embed_index:|data_root:|enabled:' "$2" | tr '\n' '|' >>"$HARNESS_TRACE"
          printf '\n' >>"$HARNESS_TRACE"
          if [[ "${HARNESS_WORKER_READY:-1}" != "1" ]]; then exit 7; fi
          printf '%s\n' \
            '{"event":"worker.readiness","ready":true,"token":"worker-secret","image":"data:image/jpeg;base64,QUJDREVGR0g="}'
          trap 'exit 0' TERM INT
          while :; do sleep 0.1; done
        fi
        if [[ "$1" == "scripts/es_ingest_smoke.py" ]]; then
          printf 'smoke=%s\n' "$*" >>"$HARNESS_TRACE"
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
    bash_env.write_text(f'export PATH="{fake_bin_bash}:$PATH"\nhash -r\n', encoding="utf-8", newline="\n")
    env.update(
        {
            "PATH": f"{fake_bin_bash}:{bash_path}",
            "BASH_ENV": as_bash_path(bash_env),
            "REAL_PYTHON": as_bash_path(Path(sys.executable)),
            "HARNESS_TRACE": as_bash_path(trace),
        }
    )
    return repo, env


def _run_bash_runtime(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    return subprocess.run(
        [bash, (repo / "scripts/es-runtime-stack.sh").as_posix(), *args],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


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
    assert "recorded-video Worker exited before readiness" in (run_dir / "stack.log").read_text(encoding="utf-8")


def test_bash_runtime_monitor_detects_api_exit_while_worker_and_ui_continue():
    functions = "\n".join(_bash_function(name) for name in ("pid_is_running", "wait_runtime_processes"))
    probe = f"""
    declare -A PROCESS_PIDS=()
    record_process_exit() {{ :; }}
    log_stack_error() {{ printf '%s' "$*" >&2; }}
    {functions}
    bash -c 'exit 7' & PROCESS_PIDS[api]=$!
    bash -c 'while :; do :; done' & PROCESS_PIDS[worker]=$!
    bash -c 'while :; do :; done' & PROCESS_PIDS[ui]=$!
    trap 'kill -KILL "${{PROCESS_PIDS[worker]}}" "${{PROCESS_PIDS[ui]}}" 2>/dev/null || true' EXIT
    wait_runtime_processes
    """

    completed = _run_bash_probe(probe, timeout=3)

    assert completed.returncode != 0
    assert "api" in completed.stderr


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
    assert 'DELETE "$ES_ENDPOINT/$VALIDATION_SMOKE_INDEX"' in bash
    assert '$validationSmokeIndex = "$validationIndex-legacy-smoke"' in powershell
    assert '"--index", $validationSmokeIndex' in powershell
    assert '"$esEndpoint/$validationSmokeIndex"' in powershell


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

    assert "[stack]" in bash
    assert 'sed -u "s/^/[$label] /"' in bash
    assert "redact_component_output es" in bash
    assert "redact_component_output" in bash

    assert "[stack]" in powershell
    assert '$prefix = "[$Component]"' in powershell
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
        line for line in text.splitlines() if "recorded-video-worker.py --config" in line and "setsid" in line
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
    record_process_exit() {{ :; }}
    {functions}
    bash -c 'trap "" TERM; while :; do :; done' &
    PROCESS_PIDS[worker]=$!
    stop_managed_process worker
    """
    started = time.monotonic()

    completed = _run_bash_probe(probe)

    assert time.monotonic() - started < 1.8
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
            lambda: _bash_function("redact_runtime_text"),
            _run_bash_probe,
            "printf '%s' 'Authorization: Bearer top-secret' | redact_runtime_text",
        ),
        (
            lambda: _powershell_function("Protect-RuntimeText"),
            _run_powershell_probe,
            "Protect-RuntimeText 'Authorization: Bearer top-secret'",
        ),
    ],
    ids=("bash", "powershell"),
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


def test_powershell_shutdown_does_not_block_on_a_stubborn_process():
    function = _powershell_function("Stop-OwnedProcessTree")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function taskkill.exe {{ }}
    {function}
    $child = Start-Process powershell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 2') -PassThru
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $stopArgs = @{{ Component = 'worker'; Process = $child; GraceTimeoutMs = 100; ForceTimeoutMs = 100 }}
    try {{ Stop-OwnedProcessTree @stopArgs }} catch {{ }}
    $watch.Stop()
    if (-not $child.HasExited) {{ Stop-Process -Id $child.Id -Force }}
    if ($watch.ElapsedMilliseconds -ge 1000) {{ exit 8 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


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
    function Get-NetTCPConnection {{ [pscustomobject]@{{ OwningProcess = 4321 }} }}
    function Assert-CurrentUserProcess {{
        param($ProcessId, $ExpectedCreationDate)
        $script:checks++
        return [pscustomobject]@{{ CreationDate = 'identity-token' }}
    }}
    function Write-Stack {{ }}
    function taskkill.exe {{ }}
    function Wait-PortFree {{ }}
    {function}
    Reclaim-Port -Port 8000 -TimeoutSec 1
    if ($script:checks -lt 2) {{ exit 6 }}
    """

    completed = _run_powershell_probe(probe)

    assert completed.returncode == 0, completed.stderr


def test_powershell_runtime_monitor_detects_api_exit_while_ui_and_worker_continue():
    function = _powershell_function("Wait-RuntimeProcesses")
    probe = f"""
    $ErrorActionPreference = 'Stop'
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
