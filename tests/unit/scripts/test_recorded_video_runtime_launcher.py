from __future__ import annotations

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
POWERSHELL_SCRIPT = Path("scripts/es-runtime-stack.ps1")
POWERSHELL_LOG_PUMP = Path("scripts/lib/RuntimeLogPump.cs")


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
        if [[ "$*" == *"/api/v1/search"* ]]; then
          printf 'proxy=ready\n' >>"$HARNESS_TRACE"
          printf '405'
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
          if [[ -n "${HARNESS_SMOKE_SLEEP:-}" ]]; then sleep "$HARNESS_SMOKE_SLEEP"; fi
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
    time.sleep(0.75)
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
    (scripts / "runtime-doctor.py").write_text(fake_runtime + "print('api_key=doctor-secret')\n", encoding="utf-8")
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
    @(Get-CimInstance Win32_Process | ForEach-Object {
        [pscustomobject]@{
            pid = [int]$_.ProcessId
            parent_pid = [int]$_.ParentProcessId
            creation = $_.CreationDate.ToUniversalTime().ToString('o')
            executable_path = [string]$_.ExecutablePath
            command_line = [string]$_.CommandLine
        }
    }) | ConvertTo-Json -Compress
    """
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    snapshot = json.loads(completed.stdout)
    return snapshot if isinstance(snapshot, list) else [snapshot]


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
            if current_parent is not None:
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
    subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
        input=json.dumps(deepest_first),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


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
    command = [powershell, "-NoProfile", "-NonInteractive", "-File", str(probe)]
    stdout_path = repo / "launcher.stdout.log"
    stderr_path = repo / "launcher.stderr.log"
    exit_trigger = repo / "api-exit.trigger"
    process_env = env.copy()
    process_env["HARNESS_API_EXIT_TRIGGER"] = str(exit_trigger)
    owned_registry: dict[str, dict[str, object]] = {}
    primary_failure: BaseException | None = None
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
            try:
                exc.add_note(_powershell_runtime_diagnostics(repo))
            except BaseException as diagnostic_error:
                exc.add_note(f"PowerShell harness diagnostics failed: {diagnostic_error!r}")
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

            def verify_cleanup() -> None:
                remaining = _powershell_repo_processes(repo)
                if remaining:
                    raise AssertionError(f"PowerShell harness left owned processes: {remaining}")

            cleanup_stage("owned-process scan", cleanup_scan)
            cleanup_stage("graceful launcher trigger", graceful_cleanup)
            cleanup_stage("trace diagnostics", lambda: _powershell_runtime_diagnostics(repo))
            cleanup_stage("exact tree termination", exact_cleanup)
            cleanup_stage("final residual verification", verify_cleanup)

            if cleanup_errors:
                details = "PowerShell harness cleanup errors: " + "; ".join(cleanup_errors)
                if primary_failure is not None:
                    primary_failure.add_note(details)
                else:
                    raise AssertionError(f"{details}\n{_powershell_runtime_diagnostics(repo)}")
        result = subprocess.CompletedProcess(command, process.returncode)
    return subprocess.CompletedProcess(
        command,
        result.returncode,
        stdout_path.read_text(encoding="utf-8"),
        stderr_path.read_text(encoding="utf-8"),
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
    launcher_pid_path = repo / "launcher.pid"
    process = subprocess.Popen(
        [
            bash,
            "-c",
            'pid_path="$1"; shift; printf "%s\\n" "$$" >"$pid_path"; exec "$@"',
            "bash",
            launcher_pid_path.as_posix(),
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
    )
    try:
        deadline = time.monotonic() + 30
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

        launcher_pid = launcher_pid_path.read_text(encoding="utf-8").strip()
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
            if launcher_pid_path.exists():
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
    assert any(
        message in stack_log
        for message in (
            "recorded-video Worker exited before readiness",
            "recorded-video Worker did not emit ready=true",
        )
    )


def test_bash_normal_start_never_invokes_validation_smoke(tmp_path: Path):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_API_EXIT_AFTER"] = "1"

    completed = _run_bash_runtime(repo, env, "--timeout-sec", "3")

    assert completed.returncode == 17, completed.stderr
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "smoke=" not in trace
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    manifest = json.loads((run_dir / "processes.json").read_text(encoding="utf-8"))
    assert {item["component"] for item in manifest["processes"]} == {"es", "api", "worker", "ui"}
    assert all(item["exit_status"] is not None for item in manifest["processes"])


@pytest.mark.parametrize("signal_name", ["TERM", "INT"])
def test_bash_interruption_cleans_validation_index_data_and_config(tmp_path: Path, signal_name: str):
    repo, env = _bash_runtime_harness(tmp_path)
    env["HARNESS_SMOKE_SLEEP"] = "30"
    bash = shutil.which("bash")
    assert bash is not None
    launcher = (repo / "scripts/es-runtime-stack.sh").as_posix()

    completed = subprocess.run(
        [
            bash,
            "-c",
            'timeout --preserve-status -k 5 -s "$1" 3 "$2" --validate --smoke-only --timeout-sec 3',
            "bash",
            signal_name,
            launcher,
        ],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 130, completed.stderr
    run_dir = next((repo / ".runtime/es-stack/runs").iterdir())
    trace = (repo / "trace.log").read_text(encoding="utf-8")
    assert "-X DELETE" in trace
    assert not (run_dir / "validation-config.yaml").exists()
    assert not (run_dir / f"validation-{run_dir.name}").exists()


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


def test_powershell_helper_initial_identity_capture_failure_reclaims_start_gated_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, env = _powershell_runtime_harness(tmp_path)
    original_snapshot = _powershell_process_snapshot
    snapshot_calls = 0

    class HarnessIdentityCaptureError(RuntimeError):
        pass

    def fail_initial_identity_capture() -> list[dict[str, object]]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 1:
            raise HarnessIdentityCaptureError("intentional initial identity capture failure")
        return original_snapshot()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                sys.modules[__name__],
                "_powershell_process_snapshot",
                fail_initial_identity_capture,
            )
            with pytest.raises(
                HarnessIdentityCaptureError,
                match="intentional initial identity capture failure",
            ):
                _run_powershell_runtime(repo, env, "-Validate", "-KeepRunning", "-TimeoutSec", "3")
        assert _powershell_repo_processes(repo) == []
    finally:
        _terminate_exact_powershell_processes(_powershell_repo_processes(repo))


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


def test_powershell_helper_reclaims_recorded_descendant_after_its_parent_exits(tmp_path: Path):
    repo, env = _powershell_runtime_harness(tmp_path)
    env["HARNESS_DETACHED_CHILD"] = "1"
    detached_identity: dict[str, object] | None = None

    try:
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
        registry = _load_powershell_process_registry(repo)
        detached_record = next(item for item in registry.values() if int(item["pid"]) == detached_pid)
        assert {
            "pid",
            "parent_pid",
            "creation",
            "executable_path",
            "command_line",
            "lineage",
        } <= detached_record.keys()
        assert detached_record["lineage"][-1] == {
            "pid": detached_pid,
            "creation": detached_record["creation"],
        }
        assert len(detached_record["lineage"]) >= 3
        detached_identity = next(
            (item for item in _powershell_process_snapshot() if int(item["pid"]) == detached_pid),
            None,
        )
        assert detached_identity is None
    finally:
        if detached_identity is not None:
            _terminate_exact_powershell_processes([detached_identity])


def test_powershell_registry_rejects_preexisting_children_and_reused_parent_pid():
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

    child = identity(13, 10, "2026-07-16T01:00:01.0000000Z")
    _record_owned_powershell_descendants(registry, [root, child])
    grandchild = identity(14, 13, "2026-07-16T01:00:02.0000000Z")
    _record_owned_powershell_descendants(registry, [grandchild])
    assert registry[_powershell_identity_key(grandchild)]["lineage"] == [
        {"pid": 10, "creation": root["creation"]},
        {"pid": 13, "creation": child["creation"]},
        {"pid": 14, "creation": grandchild["creation"]},
    ]


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
    assert 'for validation_resource in "$VALIDATION_SMOKE_INDEX" "$VALIDATION_INDEX"; do' in bash
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
    assert 'sed -u "s/^/[$label] /"' in bash
    assert "redact_component_output es" in bash
    assert "redact_component_output" in bash

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


@pytest.mark.parametrize("launcher", ["bash", "powershell"])
def test_runtime_redactor_covers_quoted_json_secrets_and_multiline_image_payload(launcher: str):
    first_chunk = "A" * 96
    second_chunk = "B" * 96
    payload = (
        '{"Authorization":"Bearer json-auth-secret","api_key":"json-api-secret",'
        '"token":"json-token-secret","password":"json-password-secret",'
        f'"image":"data:image/png;base64,\n{first_chunk}\n{second_chunk}"}}'
    )
    if launcher == "bash":
        function = _bash_function("redact_runtime_text")
        completed = _run_bash_probe(f"{function}\nprintf %s {shlex.quote(payload)} | redact_runtime_text")
    else:
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
    function = _powershell_function("Stop-OwnedProcessTree")
    probe = f"""
    $ErrorActionPreference = 'Stop'
    function Set-ProcessExit {{ param($Component, $ExitStatus) }}
    function taskkill.exe {{ }}
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


def test_powershell_forced_shutdown_timeout_still_finalizes_owned_process():
    function = _powershell_function("Stop-OwnedProcessTree")
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
