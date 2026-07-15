from __future__ import annotations

import json
import re
import shutil
import subprocess
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
    assert 'sed -u "s/^/[$2] /"' in bash
    assert "[es]" in bash
    for component in ("api", "worker", "ui"):
        assert f"start_file_log_stream {component}" in bash

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
