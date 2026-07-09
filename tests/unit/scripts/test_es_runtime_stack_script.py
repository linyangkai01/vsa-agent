from pathlib import Path


SCRIPT = Path("scripts/es-runtime-stack.ps1")
BASH_SCRIPT = Path("scripts/es-runtime-stack.sh")


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _bash_script_text() -> str:
    return BASH_SCRIPT.read_text(encoding="utf-8")


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
    assert "Stop-Process" in text
    assert "$apiProcess" in text
    assert "finally" in text


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
