from pathlib import Path


SCRIPT = Path("scripts/es-runtime-stack.ps1")
BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")
SYNC_SCRIPT = Path("scripts/sync-server-files.ps1")


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _bash_script_text() -> str:
    return BASH_SCRIPT.read_text(encoding="utf-8")


def _sync_script_text() -> str:
    return SYNC_SCRIPT.read_text(encoding="utf-8")


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
