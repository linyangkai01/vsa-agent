#!/usr/bin/env python3
"""Read-only runtime preflight checks for the recorded-video stack."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_ES_COMPAT_HEADERS = {
    "accept": "application/vnd.elasticsearch+json; compatible-with=8",
    "content-type": "application/vnd.elasticsearch+json; compatible-with=8",
}
_REQUIRED_COMMANDS = ("docker", "ffprobe", "ffmpeg")
_COMMAND_CODES = {
    "conda": "CONDA_MISSING",
    "npm": "NPM_MISSING",
    "docker": "DOCKER_MISSING",
    "ffprobe": "FFPROBE_MISSING",
    "ffmpeg": "FFMPEG_MISSING",
}
_REQUIRED_PYTHON_MODULES = (
    "aiohttp",
    "aiosqlite",
    "elasticsearch",
    "fastapi",
    "httpx",
    "multipart",
    "pydantic",
    "uvicorn",
    "yaml",
)

_CREDENTIAL_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_AUTHORIZATION_VALUE = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;]+")
_API_KEY_VALUE = re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+")


@dataclass(frozen=True)
class DoctorCheck:
    component: str
    code: str
    ok: bool
    message: str
    remediation: str


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [asdict(check) for check in self.checks],
        }


def _check(
    component: str,
    code: str,
    ok: bool,
    message: str,
    remediation: str = "none",
) -> DoctorCheck:
    return DoctorCheck(
        component=component,
        code=code,
        ok=ok,
        message=_redact_sensitive(message),
        remediation=_redact_sensitive(remediation),
    )


def _redact_sensitive(value: str) -> str:
    redacted = _CREDENTIAL_URL.sub(r"\1<redacted>@", value)
    redacted = _AUTHORIZATION_VALUE.sub(r"\1<redacted>", redacted)
    return _API_KEY_VALUE.sub(r"\1<redacted>", redacted)


def _safe_error_summary(error: Exception) -> str:
    return f"Cannot load runtime configuration ({type(error).__name__})."


def _default_command_exists(name: str) -> bool:
    if name == "npm" and (REPO_ROOT / ".deps" / "node" / "bin" / "npm").is_file():
        return True
    return shutil.which(name) is not None


def _default_python_module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _default_docker_compose_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "compose", "version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _port_is_available(port: int) -> bool:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        listener.close()


def _process_owner(pid: str) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-o", "user=", "-p", pid],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    owner = completed.stdout.strip()
    return owner or None


def detect_port_owner(port: int) -> str | None:
    """Return None for a free port, the listener owner, or '<unknown>'."""
    if _port_is_available(port):
        return None
    if os.name == "nt":
        return "<unknown>"

    commands: list[list[str]] = []
    if shutil.which("lsof"):
        commands.append(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
    if shutil.which("fuser"):
        commands.append(["fuser", "-n", "tcp", str(port)])

    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        pid_text = f"{completed.stdout} {completed.stderr}"
        pids = [token for token in pid_text.split() if token.isdigit()]
        owners = sorted({owner for pid in pids if (owner := _process_owner(pid))})
        if owners:
            return ",".join(owners)
    return "<unknown>"


def _data_root_checks(
    config: Any,
    disk_free_bytes: Callable[[Path], int],
) -> list[DoctorCheck]:
    data_root = Path(config.recorded_video.data_root)
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        descriptor, probe_name = tempfile.mkstemp(prefix=".runtime-doctor-", dir=data_root)
        os.close(descriptor)
        Path(probe_name).unlink()
    except OSError as error:
        return [
            _check(
                "data_root",
                "DATA_ROOT_UNWRITABLE",
                False,
                f"Cannot create and write the recorded-video data root: {error}",
                f"Grant the current user write access to {data_root}.",
            )
        ]

    checks = [
        _check(
            "data_root",
            "DATA_ROOT_WRITABLE",
            True,
            f"Recorded-video data root is writable: {data_root}",
        )
    ]
    try:
        available = int(disk_free_bytes(data_root))
    except OSError as error:
        checks.append(
            _check(
                "data_root",
                "DATA_ROOT_DISK_UNKNOWN",
                False,
                f"Cannot determine free disk space: {error}",
                "Check the filesystem mount and quota for the recorded-video data root.",
            )
        )
        return checks

    required = int(config.recorded_video.max_upload_bytes)
    enough = available >= required
    checks.append(
        _check(
            "data_root",
            "DATA_ROOT_DISK_READY" if enough else "DATA_ROOT_DISK_LOW",
            enough,
            f"Free bytes={available}; required bytes={required}.",
            "Free disk space or reduce recorded_video.max_upload_bytes." if not enough else "none",
        )
    )
    return checks


def _provider_check(config: Any) -> DoctorCheck:
    if not config.recorded_video.enabled:
        return _check(
            "providers",
            "RECORDED_VIDEO_DISABLED",
            True,
            "Recorded-video provider validation is skipped because the feature is disabled.",
        )
    try:
        from vsa_agent.config import validate_recorded_video_runtime

        diagnostics = validate_recorded_video_runtime(config)
    except (KeyError, ValueError) as error:
        return _check(
            "providers",
            "PROVIDER_CONFIG_INVALID",
            False,
            str(error),
            "Configure a production VLM and embedding provider without mock fallback.",
        )
    if not diagnostics.ok:
        messages = "; ".join(issue.message for issue in diagnostics.issues)
        return _check(
            "providers",
            "PROVIDER_CONFIG_INVALID",
            False,
            messages,
            "Set the named provider environment variables and verify profile role bindings.",
        )
    return _check(
        "providers",
        "PROVIDER_CONFIG_VALID",
        True,
        "Recorded-video VLM and embedding provider configuration is valid.",
    )


def _mapping_value(mapping: dict[str, Any], *path: str) -> Any:
    value: Any = mapping
    for item in path:
        if not isinstance(value, dict):
            return None
        value = value.get(item)
    return value


def _normalized_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Match RecordedVideoIndex readiness semantics for ES-normalized objects."""
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized[key] = _normalized_mapping(value) if isinstance(value, Mapping) else value
    if normalized.get("type") == "object" and isinstance(normalized.get("properties"), Mapping):
        normalized.pop("type")
    return normalized


async def _check_elasticsearch_async(
    config: Any,
    endpoint: str,
    client_factory: Callable[..., Any],
) -> DoctorCheck:
    client = None
    try:
        from vsa_agent.config import resolve_runtime_config
        from vsa_agent.recorded_video.es_index import RecordedVideoIndex, build_segment_mapping

        client = client_factory(
            hosts=[endpoint],
            request_timeout=config.search.request_timeout_sec,
            verify_certs=config.search.verify_certs,
        )
        compatible = (
            client.options(headers=_ES_COMPAT_HEADERS) if callable(getattr(client, "options", None)) else client
        )
        if not await compatible.ping():
            return _check(
                "elasticsearch",
                "ES_UNREACHABLE",
                False,
                f"Elasticsearch did not respond at {endpoint}.",
                "Start Elasticsearch and verify the loopback endpoint and TLS settings.",
            )

        alias = config.search.embed_index
        if not await compatible.indices.exists_alias(name=alias):
            return _check(
                "elasticsearch",
                "INDEX_ALIAS_MISSING",
                False,
                f"Recorded-video alias does not exist: {alias}",
                "Bootstrap the versioned recorded-video index before starting the production stack.",
            )
        alias_payload = await compatible.indices.get_alias(name=alias)
        if not isinstance(alias_payload, dict) or len(alias_payload) != 1:
            raise ValueError("INDEX_ALIAS_CONFLICT: alias must resolve to exactly one index")
        index_name, index_alias = next(iter(alias_payload.items()))
        alias_settings = index_alias.get("aliases", {}).get(alias, {}) if isinstance(index_alias, dict) else {}
        if alias_settings.get("is_write_index") is not True:
            raise ValueError("INDEX_ALIAS_CONFLICT: alias must identify one explicit write index")

        mapping_payload = await compatible.indices.get_mapping(index=index_name)
        mapping = mapping_payload.get(index_name, {}).get("mappings", {}) if isinstance(mapping_payload, dict) else {}
        dims = _mapping_value(mapping, "properties", "vector", "dims")
        resolved = resolve_runtime_config(config)
        expected_model = resolved.embedding.model if resolved.embedding else ""
        if type(dims) is not int or dims <= 0:
            raise ValueError("INDEX_MAPPING_CONFLICT: dense vector dimensions are missing")
        expected_mapping = build_segment_mapping(model=expected_model, version="v1", dims=dims)
        expected_name = RecordedVideoIndex(None, alias=alias).index_name(model=expected_model, dims=dims)
        if index_name != expected_name or _normalized_mapping(mapping) != _normalized_mapping(expected_mapping):
            raise ValueError("INDEX_MAPPING_CONFLICT: recorded-video mapping, model, or index name differs")

        settings_payload = await compatible.indices.get_settings(index=index_name, flat_settings=True)
        settings = (
            settings_payload.get(index_name, {}).get("settings", {}) if isinstance(settings_payload, dict) else {}
        )
        actual_settings = {
            "shards": str(settings.get("index.number_of_shards")),
            "replicas": str(settings.get("index.number_of_replicas")),
            "field_limit": str(settings.get("index.mapping.total_fields.limit")),
        }
        if actual_settings != {"shards": "1", "replicas": "0", "field_limit": "64"}:
            raise ValueError("INDEX_SETTINGS_CONFLICT: recorded-video index settings differ")
        return _check(
            "elasticsearch",
            "ES_INDEX_VALID",
            True,
            f"Recorded-video alias {alias} resolves to the expected index {index_name}.",
        )
    except Exception as error:
        message = str(error) or type(error).__name__
        code = message.split(":", 1)[0] if ":" in message else "ES_CHECK_FAILED"
        return _check(
            "elasticsearch",
            code,
            False,
            message,
            "Verify the Elasticsearch alias, embedding model, vector dimensions, mapping, and settings.",
        )
    finally:
        close = getattr(client, "close", None) if client is not None else None
        if callable(close):
            await close()


def check_elasticsearch(
    config: Any,
    endpoint: str,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> DoctorCheck:
    if not config.recorded_video.enabled:
        return _check(
            "elasticsearch",
            "ES_RECORDED_VIDEO_SKIPPED",
            True,
            "Recorded-video alias validation is skipped because the feature is disabled.",
        )
    if not config.search.enabled:
        return _check(
            "elasticsearch",
            "SEARCH_DISABLED",
            False,
            "Recorded-video processing requires search.enabled=true.",
            "Enable production Elasticsearch search before starting the Worker.",
        )
    if not endpoint:
        return _check(
            "elasticsearch",
            "ES_ENDPOINT_MISSING",
            False,
            "Elasticsearch endpoint is empty.",
            "Set search.es_endpoint or pass --es-endpoint.",
        )
    if client_factory is None:
        from elasticsearch import AsyncElasticsearch

        client_factory = AsyncElasticsearch
    return asyncio.run(_check_elasticsearch_async(config, endpoint, client_factory))


def _python_dependency_checks(
    python_module_exists: Callable[[str], bool],
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for module in _REQUIRED_PYTHON_MODULES:
        exists = python_module_exists(module)
        checks.append(
            _check(
                f"python:{module}",
                "PYTHON_PACKAGE_AVAILABLE" if exists else "PYTHON_PACKAGE_MISSING",
                exists,
                f"Python package is available: {module}" if exists else f"Python package is missing: {module}",
                f"Install the project Python dependencies containing {module}." if not exists else "none",
            )
        )
    return checks


def run_doctor(
    *,
    config: Any | None = None,
    es_endpoint: str = "",
    ports: Sequence[int] = (8000, 3000),
    conda_env: str = "",
    phase: str = "all",
    require_ui: bool = True,
    command_exists: Callable[[str], bool] = _default_command_exists,
    python_module_exists: Callable[[str], bool] = _default_python_module_exists,
    docker_compose_available: Callable[[], bool] = _default_docker_compose_available,
    port_owner: Callable[[int], str | None] = detect_port_owner,
    current_user: Callable[[], str] = getpass.getuser,
    disk_free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    es_checker: Callable[[Any, str], DoctorCheck] = check_elasticsearch,
) -> DoctorResult:
    if phase not in {"all", "static", "elasticsearch"}:
        raise ValueError(f"Unsupported runtime doctor phase: {phase}")
    if config is None:
        from vsa_agent.config import AppConfig

        config = AppConfig()
    app_config = config
    checks: list[DoctorCheck] = []

    if phase == "elasticsearch":
        endpoint = es_endpoint.strip() or app_config.search.es_endpoint.strip()
        return DoctorResult(checks=(es_checker(app_config, endpoint),))

    required_commands = (
        (("conda",) if conda_env.strip() else ()) + (("npm",) if require_ui else ()) + _REQUIRED_COMMANDS
    )
    for command in required_commands:
        exists = command_exists(command)
        checks.append(
            _check(
                command,
                f"{command.upper()}_AVAILABLE" if exists else _COMMAND_CODES[command],
                exists,
                f"Command is available: {command}" if exists else f"Required command is missing: {command}",
                f"Install {command} for the current user or selected conda environment." if not exists else "none",
            )
        )

    checks.extend(_python_dependency_checks(python_module_exists))

    compose_ready = docker_compose_available()
    checks.append(
        _check(
            "docker-compose",
            "DOCKER_COMPOSE_AVAILABLE" if compose_ready else "DOCKER_COMPOSE_UNAVAILABLE",
            compose_ready,
            "Docker Compose is available." if compose_ready else "docker compose version failed.",
            "Enable the Docker Compose plugin for the current user." if not compose_ready else "none",
        )
    )
    checks.extend(_data_root_checks(app_config, disk_free_bytes))
    checks.append(_provider_check(app_config))

    user = current_user()
    for port in ports:
        owner = port_owner(int(port))
        component = f"port:{port}"
        if owner is None:
            checks.append(_check(component, "PORT_AVAILABLE", True, f"Port {port} is available."))
        elif owner == user:
            checks.append(
                _check(component, "PORT_CURRENT_OWNER", True, f"Port {port} is owned by the current user {user}.")
            )
        elif owner == "<unknown>":
            checks.append(
                _check(
                    component,
                    "PORT_OWNER_UNKNOWN",
                    False,
                    f"Port {port} is occupied and its owner cannot be identified.",
                    "Stop the listener yourself or choose another port; the launcher will not terminate it.",
                )
            )
        else:
            checks.append(
                _check(
                    component,
                    "PORT_FOREIGN_OWNER",
                    False,
                    f"Port {port} is owned by another user: {owner}",
                    "Choose another port or ask that user to stop the listener; do not use sudo.",
                )
            )

    if phase == "all":
        endpoint = es_endpoint.strip() or app_config.search.es_endpoint.strip()
        checks.append(es_checker(app_config, endpoint))
    return DoctorResult(checks=tuple(checks))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--es-endpoint", default="")
    parser.add_argument("--port", type=int, action="append", default=[])
    parser.add_argument("--conda-env", default="")
    parser.add_argument("--phase", choices=("all", "static", "elasticsearch"), default="all")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., DoctorResult] = run_doctor,
) -> int:
    args = _build_parser().parse_args(argv)
    dependency_checks = _python_dependency_checks(_default_python_module_exists)
    missing_dependencies = tuple(check for check in dependency_checks if not check.ok)
    if missing_dependencies:
        result = DoctorResult(checks=missing_dependencies)
    else:
        try:
            from vsa_agent.config import AppConfig

            config = AppConfig.from_yaml(args.config)
        except Exception as error:
            result = DoctorResult(
                checks=(
                    _check(
                        "config",
                        "CONFIG_LOAD_FAILED",
                        False,
                        _safe_error_summary(error),
                        "Fix the YAML file and referenced local configuration before starting the stack.",
                    ),
                )
            )
        else:
            result = runner(
                config=config,
                es_endpoint=args.es_endpoint,
                ports=tuple(args.port or (8000, 3000)),
                conda_env=args.conda_env,
                phase=args.phase,
                require_ui=not args.skip_ui,
            )

    if args.json_output:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        for check in result.checks:
            state = "PASS" if check.ok else "FAIL"
            print(f"[{state}] {check.component} {check.code}: {check.message}")
            if not check.ok:
                print(f"  remediation: {check.remediation}")
        print("PASS: runtime doctor succeeded" if result.ok else "ERROR: runtime doctor failed")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
