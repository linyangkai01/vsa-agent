from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from vsa_agent.config import AppConfig
from vsa_agent.recorded_video.es_index import RecordedVideoIndex, build_segment_mapping

SCRIPT_PATH = Path("scripts/runtime-doctor.py")


def _load_doctor():
    spec = importlib.util.spec_from_file_location("runtime_doctor", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _production_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        active_profile="production",
        backends={
            "provider": {
                "provider": "openai_compatible",
                "base_url": "http://provider.test/v1",
                "api_key_env": "TEST_PROVIDER_API_KEY",
            }
        },
        profiles={
            "production": {
                "llm": {"backend": "provider", "model": "chat-model"},
                "vlm": {"backend": "provider", "model": "vision-model"},
                "embedding": {"backend": "provider", "model": "embedding-model"},
            }
        },
        search={
            "enabled": True,
            "es_endpoint": "http://es.test:9200",
            "embed_index": "recorded-video",
            "verify_certs": False,
            "allow_mock_fallback": False,
            "force_mock_embedding": False,
        },
        recorded_video={
            "enabled": True,
            "data_root": tmp_path / "recorded-video",
            "max_upload_bytes": 1,
        },
    )


def _success_check(doctor: Any, component: str, code: str):
    return doctor.DoctorCheck(
        component=component,
        code=code,
        ok=True,
        message="ready",
        remediation="none",
    )


def test_doctor_reports_ffmpeg_and_foreign_port_without_killing(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(recorded_video={"enabled": False, "data_root": tmp_path, "max_upload_bytes": 1})

    result = doctor.run_doctor(
        config=config,
        ports=(8000,),
        command_exists=lambda name: name != "ffmpeg",
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        port_owner=lambda _port: "other-user",
        current_user=lambda: "current-user",
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_SKIPPED"),
    )

    assert {check.code for check in result.checks} >= {"FFMPEG_MISSING", "PORT_FOREIGN_OWNER"}
    assert not result.ok
    assert all(check.remediation for check in result.checks if not check.ok)


def test_doctor_checks_configured_media_binary_paths(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(
        recorded_video={
            "enabled": False,
            "data_root": tmp_path,
            "max_upload_bytes": 1,
            "ffmpeg_path": "/opt/media/bin/ffmpeg",
            "ffprobe_path": "/opt/media/bin/ffprobe",
        }
    )
    commands: list[str] = []

    result = doctor.run_doctor(
        config=config,
        ports=(),
        command_exists=lambda name: commands.append(name) or True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
    )

    assert "/opt/media/bin/ffmpeg" in commands
    assert "/opt/media/bin/ffprobe" in commands
    assert result.ok


def test_doctor_accepts_a_port_owned_by_the_current_user(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(recorded_video={"enabled": False, "data_root": tmp_path, "max_upload_bytes": 1})

    result = doctor.run_doctor(
        config=config,
        ports=(8000,),
        command_exists=lambda _name: True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        port_owner=lambda _port: "runtime-user",
        current_user=lambda: "runtime-user",
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_SKIPPED"),
    )

    port_check = next(check for check in result.checks if check.component == "port:8000")
    assert port_check.ok
    assert port_check.code == "PORT_CURRENT_OWNER"


def test_doctor_only_requires_conda_when_an_environment_is_selected(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(recorded_video={"enabled": False, "data_root": tmp_path, "max_upload_bytes": 1})
    commands: list[str] = []

    def command_exists(name: str) -> bool:
        commands.append(name)
        return name != "conda"

    without_conda = doctor.run_doctor(
        config=config,
        ports=(),
        conda_env="",
        command_exists=command_exists,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_SKIPPED"),
    )

    assert "conda" not in commands
    assert without_conda.ok

    commands.clear()
    with_conda = doctor.run_doctor(
        config=config,
        ports=(),
        conda_env="vsa-agent",
        command_exists=command_exists,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_SKIPPED"),
    )

    assert "conda" in commands
    assert "CONDA_MISSING" in {check.code for check in with_conda.checks}
    assert not with_conda.ok


def test_static_doctor_skips_npm_when_ui_is_disabled(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(recorded_video={"enabled": False, "data_root": tmp_path, "max_upload_bytes": 1})
    commands: list[str] = []

    result = doctor.run_doctor(
        config=config,
        ports=(),
        phase="static",
        require_ui=False,
        command_exists=lambda name: commands.append(name) or True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
    )

    assert "npm" not in commands
    assert result.ok


def test_static_doctor_checks_recorded_video_python_dependencies(tmp_path: Path):
    doctor = _load_doctor()
    config = AppConfig(recorded_video={"enabled": False, "data_root": tmp_path, "max_upload_bytes": 1})

    result = doctor.run_doctor(
        config=config,
        ports=(),
        phase="static",
        command_exists=lambda _name: True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
    )

    components = {check.component for check in result.checks}
    assert {"python:aiosqlite", "python:httpx", "python:multipart"} <= components


def test_cli_reports_missing_packages_without_import_traceback(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(SCRIPT_PATH),
            "--config",
            str(tmp_path / "missing.yaml"),
            "--phase",
            "static",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert "PYTHON_PACKAGE_MISSING" in {check["code"] for check in payload["checks"]}


def test_doctor_probes_data_root_and_reports_low_disk_without_leaving_a_file(
    tmp_path: Path,
):
    doctor = _load_doctor()
    data_root = tmp_path / "data"
    config = AppConfig(
        recorded_video={
            "enabled": False,
            "data_root": data_root,
            "max_upload_bytes": 1024,
        }
    )

    result = doctor.run_doctor(
        config=config,
        ports=(),
        command_exists=lambda _name: True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        disk_free_bytes=lambda _path: 512,
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_SKIPPED"),
    )

    assert data_root.is_dir()
    assert list(data_root.iterdir()) == []
    assert "DATA_ROOT_DISK_LOW" in {check.code for check in result.checks}


def test_doctor_reports_provider_configuration_without_exposing_secret(
    tmp_path: Path,
    monkeypatch,
):
    doctor = _load_doctor()
    config = _production_config(tmp_path)
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.delenv("TEST_PROVIDER_API_KEY", raising=False)

    result = doctor.run_doctor(
        config=config,
        ports=(),
        command_exists=lambda _name: True,
        python_module_exists=lambda _name: True,
        docker_compose_available=lambda: True,
        es_checker=lambda _config, _endpoint: _success_check(doctor, "elasticsearch", "ES_INDEX_VALID"),
    )

    provider_check = next(check for check in result.checks if check.component == "providers")
    assert provider_check.code == "PROVIDER_CONFIG_INVALID"
    assert not provider_check.ok
    assert "TEST_PROVIDER_API_KEY" in provider_check.message
    assert "secret-value" not in json.dumps(result.to_dict())


class _FakeIndices:
    def __init__(self, alias: str, index_name: str, mapping: dict[str, Any]) -> None:
        self.alias = alias
        self.index_name = index_name
        self.mapping = mapping
        self.calls: list[str] = []

    async def exists_alias(self, *, name: str) -> bool:
        self.calls.append("exists_alias")
        return name == self.alias

    async def get_alias(self, *, name: str) -> dict[str, Any]:
        self.calls.append("get_alias")
        return {self.index_name: {"aliases": {name: {"is_write_index": True}}}}

    async def get_mapping(self, *, index: str) -> dict[str, Any]:
        self.calls.append("get_mapping")
        return {index: {"mappings": self.mapping}}

    async def get_settings(self, *, index: str, flat_settings: bool) -> dict[str, Any]:
        self.calls.append("get_settings")
        assert flat_settings is True
        return {
            index: {
                "settings": {
                    "index.number_of_shards": "1",
                    "index.number_of_replicas": "0",
                    "index.mapping.total_fields.limit": "64",
                }
            }
        }


class _FakeElasticsearch:
    def __init__(self, indices: _FakeIndices) -> None:
        self.indices = indices
        self.closed = False

    def options(self, **_kwargs: Any):
        return self

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


class _ObjectResponse:
    def __init__(self, body: object) -> None:
        self.body = body


class _WrappedIndices(_FakeIndices):
    async def get_alias(self, **kwargs):
        return _ObjectResponse(await super().get_alias(**kwargs))

    async def get_mapping(self, **kwargs):
        return _ObjectResponse(await super().get_mapping(**kwargs))

    async def get_settings(self, **kwargs):
        return _ObjectResponse(await super().get_settings(**kwargs))


def test_elasticsearch_check_validates_alias_mapping_without_writes(
    tmp_path: Path,
    monkeypatch,
):
    doctor = _load_doctor()
    config = _production_config(tmp_path)
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", "secret-value")
    dims = 4
    mapping = build_segment_mapping(model="embedding-model", version="v1", dims=dims)
    index_name = RecordedVideoIndex(None, alias="recorded-video").index_name(
        model="embedding-model",
        dims=dims,
    )
    indices = _FakeIndices("recorded-video", index_name, mapping)
    client = _FakeElasticsearch(indices)

    check = doctor.check_elasticsearch(
        config,
        "http://es.test:9200",
        client_factory=lambda **_kwargs: client,
    )

    assert check.ok
    assert check.code == "ES_INDEX_VALID"
    assert indices.calls == ["exists_alias", "get_alias", "get_mapping", "get_settings"]
    assert client.closed


def test_elasticsearch_check_accepts_es_omitted_object_type(tmp_path: Path, monkeypatch):
    doctor = _load_doctor()
    config = _production_config(tmp_path)
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", "secret-value")
    dims = 4
    mapping = copy.deepcopy(build_segment_mapping(model="embedding-model", version="v1", dims=dims))
    mapping["properties"]["readiness"].pop("type")
    index_name = RecordedVideoIndex(None, alias="recorded-video").index_name(
        model="embedding-model",
        dims=dims,
    )
    client = _FakeElasticsearch(_FakeIndices("recorded-video", index_name, mapping))

    check = doctor.check_elasticsearch(
        config,
        "http://es.test:9200",
        client_factory=lambda **_kwargs: client,
    )

    assert check.ok
    assert check.code == "ES_INDEX_VALID"


def test_elasticsearch_check_accepts_elasticsearch_8_object_responses(tmp_path: Path, monkeypatch):
    doctor = _load_doctor()
    config = _production_config(tmp_path)
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", "secret-value")
    dims = 4
    mapping = build_segment_mapping(model="embedding-model", version="v1", dims=dims)
    index_name = RecordedVideoIndex(None, alias="recorded-video").index_name(
        model="embedding-model",
        dims=dims,
    )
    client = _FakeElasticsearch(_WrappedIndices("recorded-video", index_name, mapping))

    check = doctor.check_elasticsearch(
        config,
        "http://es.test:9200",
        client_factory=lambda **_kwargs: client,
    )

    assert check.ok
    assert check.code == "ES_INDEX_VALID"


def test_elasticsearch_check_catches_client_construction_failure(tmp_path: Path):
    doctor = _load_doctor()
    config = _production_config(tmp_path)

    def invalid_client_factory(**_kwargs):
        raise ValueError("invalid endpoint")

    check = doctor.check_elasticsearch(
        config,
        "not-an-endpoint",
        client_factory=invalid_client_factory,
    )

    assert not check.ok
    assert check.code == "ES_CHECK_FAILED"
    assert "invalid endpoint" in check.message


def test_json_cli_returns_nonzero_and_structured_checks(tmp_path: Path, capsys):
    doctor = _load_doctor()
    config_path = tmp_path / "config.yaml"
    config_path.write_text("recorded_video:\n  enabled: false\n", encoding="utf-8")
    failed = doctor.DoctorResult(
        checks=(
            doctor.DoctorCheck(
                component="ffmpeg",
                code="FFMPEG_MISSING",
                ok=False,
                message="ffmpeg is missing",
                remediation="Install ffmpeg in the selected conda environment.",
            ),
        )
    )

    exit_code = doctor.main(
        ["--config", str(config_path), "--es-endpoint", "http://es.test:9200", "--json"],
        runner=lambda **_kwargs: failed,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["checks"][0]["code"] == "FFMPEG_MISSING"


def test_config_load_failure_redacts_malformed_secrets(tmp_path: Path, capsys):
    doctor = _load_doctor()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """backends:
  provider:
    provider: openai_compatible
    api_key:
      - api-key-secret
    base_url:
      - http://username:url-password@provider.test/v1
recorded_video:
  enabled: false
""",
        encoding="utf-8",
    )

    exit_code = doctor.main(["--config", str(config_path), "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["checks"][0]["code"] == "CONFIG_LOAD_FAILED"
    assert "api-key-secret" not in output
    assert "url-password" not in output
    assert "Authorization" not in output


def test_stack_launchers_run_two_phase_doctor_around_elasticsearch_startup():
    bash = Path("scripts/es-runtime-stack.sh").read_text(encoding="utf-8")
    powershell = Path("scripts/es-runtime-stack.ps1").read_text(encoding="utf-8")

    bash_static = bash.index("--phase static")
    bash_es_start = bash.index("docker compose -f docker-compose.es.yml up -d")
    bash_es_readiness = bash.index("--phase elasticsearch")
    assert bash_static < bash_es_start < bash_es_readiness < bash.index("python -m uvicorn")
    assert 'doctor_args+=(--conda-env "$CONDA_ENV")' in bash
    ps_static = powershell.index('"--phase", "static"')
    ps_es_start = powershell.index('es-dev-start.ps1" -Port $EsPort')
    ps_es_readiness = powershell.index('"--phase", "elasticsearch"')
    assert ps_static < ps_es_start < ps_es_readiness < powershell.index('"-m", "uvicorn"')
    assert '$doctorArgs += @("--conda-env", $CondaEnv)' in powershell


def test_stack_launchers_bootstrap_ui_before_static_doctor_and_skip_ui_for_smoke():
    bash = Path("scripts/es-runtime-stack.sh").read_text(encoding="utf-8")
    powershell = Path("scripts/es-runtime-stack.ps1").read_text(encoding="utf-8")

    assert 'if [[ ! -f "$REPO_ROOT/.deps/node-env.sh" ]]; then' in bash
    assert bash.index("ensure_ui_runtime\n") < bash.index("--phase static")
    assert "doctor_args+=(--skip-ui)" in bash
    assert powershell.index("Ensure-UiRuntime") < powershell.index('"--phase", "static"')
    assert '$doctorArgs += @("--skip-ui")' in powershell
