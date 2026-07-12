from pathlib import Path


SCRIPT = Path("scripts/es-runtime-stack.ps1")
BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")
SYNC_SCRIPT = Path("scripts/sync-server-files.ps1")
ES_COMPOSE = Path("docker-compose.es.yml")
PYPROJECT = Path("pyproject.toml")
GITIGNORE = Path(".gitignore")


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
    ):
        assert parameter in text


def test_es_runtime_stack_uses_existing_lifecycle_and_smoke_scripts():
    text = _script_text()

    assert "es-dev-start.ps1" in text
    assert "es-dev-stop.ps1" in text
    assert "es_ingest_smoke.py" in text
    assert "vsa_agent.api.routes:app" in text
    assert "Invoke-RestMethod" in text


def test_es_runtime_stack_generates_temporary_search_config():
    text = _script_text()

    assert ".runtime" in text
    assert "es-stack" in text
    assert "VSA_CONFIG" in text
    assert "search:" in text
    assert "enabled: true" in text
    assert "verify_certs: false" in text
    assert "force_mock_embedding: true" in text
    assert "config.yaml" in text


def test_es_runtime_stack_reports_pass_and_cleans_up_owned_process():
    text = _script_text()

    assert "PASS: ES runtime stack validation succeeded" in text
    assert "Stop-OwnedProcessTree" in text
    assert "$apiProcess" in text
    assert "finally" in text


def test_es_runtime_stack_terminates_the_owned_process_tree():
    text = _script_text()

    assert "taskkill.exe" in text
    assert "/T" in text


def test_es_runtime_stack_retains_temporary_config_with_an_explicit_notice():
    text = _script_text()

    assert "Temporary config retained: $configPath" in text


def test_es_runtime_stack_bash_script_exists():
    assert BASH_SCRIPT.exists()


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
    ):
        assert option in text


def test_es_runtime_stack_bash_uses_linux_runtime_dependencies():
    text = _bash_script_text()

    assert "docker compose" in text
    assert "es_ingest_smoke.py" in text
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
    assert "force_mock_embedding: true" in text


def test_windows_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _script_text()
    for required in (
        "Get-NetTCPConnection", "Win32_Process", "taskkill.exe", "Wait-PortFree",
        "run_original_ui_vss.sh", "NEXT_PUBLIC_ENABLE_SEARCH_TAB",
        "NEXT_PUBLIC_AGENT_API_URL_BASE", "$uiProcess", "SmokeOnly",
    ):
        assert required in text


def test_linux_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _bash_script_text()
    for required in (
        "port_listener_pids", "kill -TERM", "wait_for_port_free",
        "run_original_ui_vss.sh", "UI_PID", "NEXT_PUBLIC_ENABLE_SEARCH_TAB",
        "NEXT_PUBLIC_AGENT_API_URL_BASE", "SMOKE_ONLY",
    ):
        assert required in text


def test_linux_stack_waits_for_ui_and_reports_ui_logs_on_failure():
    text = _bash_script_text()

    for required in (
        "wait_ui_health", "UI_URL=", "UI_LOG_PATH=", "UI_ERR_LOG_PATH=",
        "Original UI process exited before readiness", "tail -n 100",
    ):
        assert required in text


def test_linux_stack_uses_port_discovery_fallbacks_without_killing_es_proxy():
    text = _bash_script_text()

    assert "command -v lsof" in text
    assert "command -v fuser" in text
    assert 'for port in "$API_PORT" "$UI_PORT"' in text
    assert 'pids="$(port_listener_pids "$port")" || return 1' in text
    assert "PORT_TERMINATION_GRACE_SEC=5" in text


def test_linux_stack_preflights_python_and_reports_each_service_failure():
    text = _bash_script_text()

    for required in (
        "verify_python_runtime",
        "aiohttp",
        "elasticsearch[async]>=8.14,<9",
        "FastAPI error log",
        "Elasticsearch logs",
        "docker compose -f docker-compose.es.yml logs --tail=100 elasticsearch",
        "kill -KILL",
        "Original UI exited after readiness",
    ):
        assert required in text


def test_linux_stack_bootstraps_node_and_ui_dependencies_before_starting_ui():
    text = _bash_script_text()

    assert 'bash "$SCRIPT_DIR/bootstrap_node.sh"' in text
    assert 'npm run ui:install' in text
    assert "config.yaml" in text


def test_es_runtime_stack_bash_reports_pass_and_cleans_up_owned_process():
    text = _bash_script_text()

    assert "PASS: ES runtime stack validation succeeded" in text
    assert "trap cleanup EXIT" in text
    assert "API_PID" in text
    assert "kill" in text


def test_es_runtime_stack_bash_terminates_the_owned_process_group_and_checks_health_payload():
    text = _bash_script_text()

    assert "setsid" in text
    assert 'kill -- "-$API_PID"' in text
    assert "json.load(sys.stdin).get(\"status\") == \"ok\"" in text
    assert "health_payload=$(curl -fsS" in text


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
    assert '"docker-compose.es.yml"' in text
    assert '"src\\vsa_agent\\api\\video_search_ingest.py"' in text
    assert '"scripts\\bootstrap_node.sh"' in text
    assert '"scripts\\run_original_ui_vss.sh"' in text
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
