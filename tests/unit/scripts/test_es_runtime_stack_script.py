import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/es-runtime-stack.ps1")
BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")
RUNTIME_LOG_SUPERVISOR = Path("scripts/runtime-log-supervisor.py")
SYNC_SCRIPT = Path("scripts/sync-server-files.ps1")
ES_COMPOSE = Path("docker-compose.es.yml")
PYPROJECT = Path("pyproject.toml")
GITIGNORE = Path(".gitignore")
RUNTIME_DOC = Path("docs/es-video-search-runtime.md")
VSS_NEXT_CONFIG = Path("frontend/original-ui/apps/nv-metropolis-bp-vss-ui/next.config.js")
ORIGINAL_UI_SERVER_DECLARATIONS = (
    Path("frontend/original-ui/packages/nv-metropolis-bp-vss-ui/map/lib-src/server.d.ts"),
    Path("frontend/original-ui/packages/nv-metropolis-bp-vss-ui/dashboard/lib-src/server.d.ts"),
    Path("frontend/original-ui/packages/nv-metropolis-bp-vss-ui/alerts/lib-src/server.d.ts"),
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _bash_script_text() -> str:
    return BASH_SCRIPT.read_text(encoding="utf-8")


def _sync_script_text() -> str:
    return SYNC_SCRIPT.read_text(encoding="utf-8")


def test_elasticsearch_uses_docker_managed_named_volume_by_default():
    text = ES_COMPOSE.read_text(encoding="utf-8")

    assert "esdata:/usr/share/elasticsearch/data" in text
    assert "VSA_ES_VOLUME_NAME:-vsa-agent-es-data" in text
    assert "VSA_ES_DATA_DIR" not in text


def test_runtime_stack_declares_its_asgi_server_dependency():
    assert '"uvicorn>=0.30"' in PYPROJECT.read_text(encoding="utf-8")


def test_original_ui_data_source_directory_is_not_ignored():
    text = GITIGNORE.read_text(encoding="utf-8")

    assert "!frontend/original-ui/packages/nemo-agent-toolkit-ui/utils/data/" in text


def test_runtime_doc_uses_one_linux_launcher_command_and_describes_live_logs():
    text = RUNTIME_DOC.read_text(encoding="utf-8")

    assert "conda run -n vsa-agent python -m pip install" not in text
    assert "source .deps/node-env.sh" not in text
    assert "[es]" in text
    assert "[api]" in text
    assert "[ui]" in text
    assert "ssh -L 3000:127.0.0.1:3000" in text
    assert "same-origin" in text


def test_stack_proxies_browser_search_requests_through_the_original_ui():
    launcher = _bash_script_text()
    windows_launcher = _script_text()
    next_config = VSS_NEXT_CONFIG.read_text(encoding="utf-8")

    assert 'NEXT_PUBLIC_AGENT_API_URL_BASE="/api/v1"' in launcher
    assert 'VSA_ORIGINAL_UI_TRACE_ROOT="$RUN_DIR/chat-traces"' in launcher
    assert 'NEXT_PUBLIC_VST_API_URL="/api/v1/vst"' in launcher
    assert 'VSA_INTERNAL_AGENT_API_URL_BASE="${API_URL}/api/v1"' in launcher
    assert '$env:NEXT_PUBLIC_AGENT_API_URL_BASE = "/api/v1"' in windows_launcher
    assert '$env:NEXT_PUBLIC_VST_API_URL = "/api/v1/vst"' in windows_launcher
    assert '$env:VSA_INTERNAL_AGENT_API_URL_BASE = "$apiUrl/api/v1"' in windows_launcher
    assert "source: '/api/v1/:path*'" in next_config
    assert "VSA_INTERNAL_AGENT_API_URL_BASE" in next_config


def test_original_ui_server_declarations_do_not_reference_missing_source_maps():
    for declaration in ORIGINAL_UI_SERVER_DECLARATIONS:
        assert "sourceMappingURL=server.d.ts.map" not in declaration.read_text(encoding="utf-8")


def test_es_runtime_stack_script_exists():
    assert SCRIPT.exists()


def test_es_runtime_stack_exposes_expected_parameters():
    text = _script_text()

    for parameter in (
        "[int]$ApiPort = 8000",
        "[int]$EsPort = 9200",
        '[string]$Index = "vsa-video-embeddings"',
        '[string]$CondaEnv = ""',
        "[switch]$StopElasticsearch",
        "[int]$UiPort = 3000",
        "[switch]$SmokeOnly",
        '[string]$DataRoot = ""',
        "[switch]$Validate",
        "[switch]$KeepRunning",
    ):
        assert parameter in text


def test_es_runtime_stack_uses_existing_lifecycle_and_explicit_validation_script():
    text = _script_text()

    assert "es-dev-start.ps1" in text
    assert "es-dev-stop.ps1" in text
    assert "es_ingest_smoke.py" in text
    assert "if ($Validate)" in text
    assert "vsa_agent.api.routes:app" in text
    assert "Invoke-RestMethod" in text


def test_stack_preserves_conda_subprocess_logs_for_api_observability():
    windows = _script_text()
    linux = _bash_script_text()

    assert '"--no-capture-output"' in windows
    assert "conda run --no-capture-output -n" in linux


def test_es_runtime_stack_generates_temporary_search_config():
    text = _script_text()

    assert ".runtime" in text
    assert "es-stack" in text
    assert "VSA_CONFIG" in text
    assert "search:" in text
    assert "enabled: true" in text
    assert "verify_certs: false" in text
    assert '$mockValue = if ($validationMode) { "true" } else { "false" }' in text
    assert "force_mock_embedding: $mockValue" in text
    assert "allow_mock_fallback: $mockValue" in text
    assert "recorded_video:" in text
    assert "enabled: true" in text
    assert "config.yaml" in text


def test_es_runtime_stack_reports_pass_and_cleans_up_owned_process():
    text = _script_text()

    assert "PASS: ES runtime stack validation succeeded" in text
    assert "Stop-OwnedProcessTree" in text
    assert "$apiProcess" in text
    assert "finally" in text


def test_es_runtime_stack_terminates_owned_processes_through_verified_handles():
    text = _script_text()

    assert "taskkill.exe" not in text
    assert "VsaProcessTracker" in text
    assert "BoundProcess" in text
    assert ".Kill()" in text


def test_es_runtime_stack_retains_temporary_config_with_an_explicit_notice():
    text = _script_text()

    assert "Temporary config retained: $configPath" in text


def test_es_runtime_stack_bash_script_exists():
    assert BASH_SCRIPT.exists()


def test_es_runtime_stack_bash_uses_one_standard_library_log_supervisor():
    text = _bash_script_text()

    assert RUNTIME_LOG_SUPERVISOR.exists()
    assert 'RUNTIME_LOG_SUPERVISOR="$SCRIPT_DIR/runtime-log-supervisor.py"' in text
    assert "ACTIVE_STACK_COMMAND_PID" not in text
    assert "redact_runtime_text" not in text
    assert "redact_component_output" not in text
    assert "> >(redact" not in text
    assert "sed -u" not in text
    assert "taskkill.exe" not in text


def test_es_runtime_stack_bash_exposes_expected_options():
    text = _bash_script_text()

    for option in (
        "--api-port",
        "--es-port",
        "--index",
        "--conda-env",
        "--timeout-sec",
        "--stop-elasticsearch",
        "--ui-port",
        "--smoke-only",
        "--data-root",
        "--validate",
        "--keep-running",
        "--secrets-file",
        "-KeepRunning",
    ):
        assert option in text


def test_es_runtime_stack_bash_uses_linux_runtime_dependencies():
    text = _bash_script_text()

    assert "docker compose" in text
    assert "es_ingest_smoke.py" in text
    assert 'if [[ "$VALIDATE" == "1" ]]' in text
    assert "vsa_agent.api.routes:app" in text
    assert "curl" in text
    assert "uvicorn" in text


def test_es_runtime_stack_bash_generates_temporary_search_config():
    text = _bash_script_text()

    assert ".runtime/es-stack" in text
    assert "VSA_CONFIG" in text
    assert "search:" in text
    assert "enabled: true" in text
    assert "verify_certs: false" in text
    assert 'validation = mode == "validation"' in text
    assert "force_mock_embedding: false" in text
    assert "allow_mock_fallback: false" in text
    assert "recorded_video:" in text
    assert "enabled: true" in text


def test_linux_stack_exports_selected_runtime_config_to_short_lived_commands():
    text = _bash_script_text()

    assert 'export VSA_CONFIG="$API_CONFIG_PATH"' in text


def test_linux_stack_loads_private_secrets_and_bootstraps_production_index():
    text = _bash_script_text()

    assert 'SECRETS_FILE="${VSA_SECRETS_FILE:-${HOME:-}/.config/vsa-agent/secrets.env}"' in text
    assert "load_secrets_file" in text
    assert "refusing secrets file with group or other permissions" in text
    assert "recorded-video-bootstrap-index.py" in text
    assert text.index("load_secrets_file") < text.index("--phase static")
    assert text.index("recorded-video-bootstrap-index.py") < text.index(
        'log_stack "validating active alias and mapping without writes"'
    )


def test_linux_stack_bootstraps_and_validates_the_active_runtime_config():
    text = _bash_script_text()

    assert 'recorded-video-bootstrap-index.py --config "$API_CONFIG_PATH" --json' in text
    assert text.count('runtime-doctor.py --config "$API_CONFIG_PATH"') == 2
    assert 'runtime-doctor.py --config "$CONFIG_PATH"' not in text
    assert 'log_stack "bootstrapping isolated validation alias before service startup"' in text
    assert 'curl -fsS "$ES_ENDPOINT/_alias/$VALIDATION_INDEX"' in text
    assert '"$ES_ENDPOINT/_cat/indices/${VALIDATION_INDEX}-*?h=index"' in text


def test_original_ui_launcher_forwards_the_requested_port_to_next():
    text = Path("scripts/run_original_ui_vss.sh").read_text(encoding="utf-8")
    turbo = Path("frontend/original-ui/turbo.json").read_text(encoding="utf-8")

    assert '-- --port "${PORT:-3000}"' in text
    assert '"env": ["VSA_INTERNAL_AGENT_API_URL_BASE"]' in turbo
    assert "env-mode=loose" not in text


def test_windows_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _script_text()
    for required in (
        "Get-NetTCPConnection",
        "Win32_Process",
        "Get-Process",
        "Wait-PortFree",
        "run_original_ui_vss.sh",
        "NEXT_PUBLIC_ENABLE_SEARCH_TAB",
        "NEXT_PUBLIC_AGENT_API_URL_BASE",
        "$uiProcess",
        "SmokeOnly",
    ):
        assert required in text
    assert "taskkill.exe" not in text


def test_windows_stack_waits_for_ui_readiness_and_reports_failures():
    text = _script_text()

    for required in (
        "Wait-UiReady",
        "Invoke-WebRequest",
        "Original UI process exited before readiness",
        "Original UI did not become reachable",
        'Join-Path $runDir "ui.log"',
        "stack log:",
    ):
        assert required in text


def test_linux_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _bash_script_text()
    for required in (
        "port_listener_pids",
        "kill -TERM",
        "wait_for_port_free",
        "run_original_ui_vss.sh",
        "UI_PID",
        "NEXT_PUBLIC_ENABLE_SEARCH_TAB",
        "NEXT_PUBLIC_AGENT_API_URL_BASE",
        "SMOKE_ONLY",
        "reclaim_stale_project_ui_processes",
        "stale_project_ui_pids",
    ):
        assert required in text
    assert 'root "/frontend/original-ui"' in text
    assert "current_uid" in text
    assert text.index("reclaim_stale_project_ui_processes\n") < text.index(
        'for port in "$API_PORT" "$UI_PORT"; do reclaim_port "$port"; done'
    )


def test_linux_stack_waits_for_ui_and_reports_ui_logs_on_failure():
    text = _bash_script_text()

    for required in (
        "wait_ui_health",
        "UI_URL=",
        "UI_LOG_PATH=",
        "ES_LOG_PATH=",
        'log_stack_error "$MANAGED_EXIT_COMPONENT exited with status $MANAGED_EXIT_STATUS"',
        "fail_if_managed_process_exited",
        "runtime-log-supervisor.py",
        "start_es_log_stream",
        "wait_runtime_processes",
        "PYTHONUNBUFFERED=1",
    ):
        assert required in text

    assert "tail_log" not in text


def test_linux_stack_uses_port_discovery_fallbacks_without_killing_es_proxy():
    text = _bash_script_text()

    assert "command -v lsof" in text
    assert "command -v fuser" in text
    assert 'for port in "$API_PORT" "$UI_PORT"' in text
    assert 'pids="$(port_listener_pids "$port")" || return 1' in text
    assert "PORT_TERMINATION_GRACE_SEC=5" in text
    assert "assert_current_user_pid" in text
    assert "FOREIGN_LISTENER" in text
    assert 'kill -0 "$pid"' in text


def test_linux_stack_preflights_python_and_reports_each_service_failure():
    text = _bash_script_text()

    for required in (
        "verify_python_runtime",
        "ensure_python_runtime",
        "python -m pip install --upgrade -e '.[dev]'",
        "aiohttp",
        "elasticsearch[async]>=8.14,<9",
        "kill -KILL",
        'MANAGED_EXIT_COMPONENT=""',
        "MANAGED_EXIT_STATUS=0",
        'log_stack_error "$MANAGED_EXIT_COMPONENT exited with status $MANAGED_EXIT_STATUS"',
    ):
        assert required in text


def test_linux_stack_bootstraps_node_and_ui_dependencies_before_starting_ui():
    text = _bash_script_text()

    assert 'bash "$SCRIPT_DIR/bootstrap_node.sh"' in text
    assert "npm run ui:install" in text
    assert "config.yaml" in text


def test_es_runtime_stack_bash_reports_pass_and_cleans_up_owned_process():
    text = _bash_script_text()

    assert "PASS: ES runtime stack validation succeeded" in text
    assert 'trap \'status=$?; trap "" INT TERM; cleanup "$status"\' EXIT' in text
    assert "API_PID" in text
    assert "kill" in text


def test_es_runtime_stack_bash_terminates_the_owned_process_group_and_checks_health_payload():
    text = _bash_script_text()

    assert "runtime-log-supervisor.py" in text
    assert "SYNC_SUPERVISOR_PID" in text
    assert "stop_managed_process" in text
    assert "signal_process_tree" in text
    assert 'kill -"$signal" -- "-$target_pgid"' in text
    assert 'json.load(sys.stdin).get("status") == "ok"' in text
    assert 'health_payload="$(curl -fsS' in text


def test_es_runtime_stack_bash_retains_temporary_config_with_an_explicit_notice():
    text = _bash_script_text()

    assert "Temporary config retained: $CONFIG_PATH" in text


def test_sync_server_files_script_exists():
    assert SYNC_SCRIPT.exists()


def test_sync_server_files_script_exposes_target_and_manifest_options():
    text = _sync_script_text()

    assert '[string]$TargetRoot = "Z:\\vsa-agent"' in text
    assert "[string[]]$IncludePaths" in text
    assert "[switch]$DryRun" in text
    assert "[switch]$PreflightOnly" in text
    assert '".gitignore"' in text
    assert '"scripts\\sync-server-files.ps1"' in text
    assert '"docker-compose.es.yml"' in text
    assert '"src\\vsa_agent\\api\\video_search_ingest.py"' in text
    assert '"tests\\unit\\api\\test_video_search_ingest.py"' in text
    assert '"scripts\\bootstrap_node.sh"' in text
    assert '"scripts\\run_original_ui_vss.sh"' in text
    assert '"scripts\\runtime-log-supervisor.py"' in text
    for acceptance_path in (
        "scripts\\recorded-video-bootstrap-index.py",
        "scripts\\recorded-video-production-acceptance.py",
        "src\\vsa_agent\\recorded_video\\bootstrap.py",
        "tests\\unit\\recorded_video\\test_bootstrap.py",
        "src\\vsa_agent\\recorded_video\\production_acceptance.py",
        "src\\vsa_agent\\recorded_video\\production_evidence.py",
        "src\\vsa_agent\\recorded_video\\production_runner.py",
        "tests\\unit\\recorded_video\\test_production_acceptance.py",
        "tests\\unit\\recorded_video\\test_production_evidence.py",
        "tests\\acceptance\\test_recorded_video_validation_report.py",
    ):
        assert f'"{acceptance_path}"' in text
    assert '"frontend\\original-ui\\package.json"' not in text
    assert '"frontend\\original-ui\\package-lock.json"' not in text
    assert '"frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\package.json"' in text
    assert '"frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\next.config.js"' in text
    for task22_server_e2e_path in (
        "frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\playwright.config.ts",
        "frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\e2e\\config.e2e.yaml",
        "frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\e2e\\fake-openai-provider.py",
        "frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\e2e\\fixtures.ts",
        "frontend\\original-ui\\apps\\nv-metropolis-bp-vss-ui\\e2e\\recorded-video.spec.ts",
    ):
        assert f'"{task22_server_e2e_path}"' in text
    assert '"frontend\\original-ui\\packages\\nv-metropolis-bp-vss-ui\\map\\lib-src\\server.d.ts"' in text
    assert '"frontend\\original-ui\\packages\\nv-metropolis-bp-vss-ui\\dashboard\\lib-src\\server.d.ts"' in text
    assert '"frontend\\original-ui\\packages\\nv-metropolis-bp-vss-ui\\alerts\\lib-src\\server.d.ts"' in text
    assert '"docs\\recorded-video-validation.md"' in text
    assert '"frontend\\original-ui\\packages\\nemo-agent-toolkit-ui\\utils\\data\\throttle.ts"' in text
    assert '"frontend\\original-ui\\packages\\nemo-agent-toolkit-ui\\__tests__\\utils\\throttle.test.ts"' in text


def test_sync_server_files_script_uses_targeted_copy_not_recursive_robocopy():
    text = _sync_script_text()

    assert "[System.IO.File]::Copy" in text
    assert "[System.IO.Directory]::CreateDirectory" in text
    assert "$IncludePaths" in text
    assert "Resolve-Path" in text
    assert "Join-Path $TargetRoot" in text
    assert "PASS: synced selected files to server target" in text
    assert "robocopy" not in text.lower()


def test_sync_server_files_script_reports_mapped_drive_permission_boundary():
    text = _sync_script_text()

    assert "Test-TargetWritable" in text
    assert "Access denied while writing to mapped target" in text
    assert "already-authenticated mapped drive" in text
    assert "No password is requested or stored by this script" in text


def test_sync_server_files_script_rejects_paths_outside_the_repo_and_target_roots():
    text = _sync_script_text()

    assert "Resolve-PathWithinRoot" in text
    assert "Path '$RelativePath' escapes $Label root" in text
    assert "-Root $repoRoot" in text
    assert "-Root $targetRootPath" in text


def _run_sync_script(tmp_path: Path, *include_paths: str) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required to execute the sync script contract")
    target = tmp_path / "target"
    target.mkdir()
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SYNC_SCRIPT.resolve()),
        "-TargetRoot",
        str(target),
        "-DryRun",
    ]
    if include_paths:
        command.extend(("-IncludePaths", *include_paths))
    return subprocess.run(command, cwd=Path.cwd(), capture_output=True, text=True, timeout=30, check=False)


@pytest.mark.parametrize(
    ("include_path", "expected_error"),
    [
        (".env", "forbidden"),
        (r".runtime\recorded-video\secret.json", "forbidden"),
    ],
)
def test_sync_server_files_rejects_unapproved_runtime_and_secret_paths(
    tmp_path: Path,
    include_path: str,
    expected_error: str,
) -> None:
    completed = _run_sync_script(tmp_path, include_path)

    assert completed.returncode != 0
    assert expected_error in (completed.stdout + completed.stderr).lower()


def test_sync_server_files_default_dry_run_uses_approved_manifest(tmp_path: Path) -> None:
    completed = _run_sync_script(tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS: dry run completed for selected files" in completed.stdout


def test_sync_server_files_default_manifest_excludes_unclassified_root_node_manifests(tmp_path: Path) -> None:
    completed = _run_sync_script(tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "frontend\\original-ui\\package.json" not in completed.stdout
    assert "frontend\\original-ui\\package-lock.json" not in completed.stdout


def test_sync_server_files_dry_run_normalizes_task22_include_path(tmp_path: Path) -> None:
    completed = _run_sync_script(
        tmp_path,
        "FRONTEND/original-ui/APPS/nv-metropolis-bp-vss-ui/E2E/FIXTURES.ts",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DRYRUN:" in completed.stdout
    assert "PASS: dry run completed for selected files" in completed.stdout
