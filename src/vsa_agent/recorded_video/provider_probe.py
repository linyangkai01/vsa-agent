"""Live readiness probes for recorded-video model providers."""

from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from vsa_agent.config import AppConfig, ResolvedRoleConfig, resolve_runtime_config

ProbeOutcome = Literal[
    "ok",
    "configuration",
    "authentication",
    "quota",
    "rate_limit",
    "timeout",
    "network",
    "server_error",
    "response_schema",
    "http_error",
]

_SAFE_IDENTITY_VALUE = re.compile(r"[^A-Za-z0-9._:/-]")
_SAFE_CORRELATION_VALUE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_SAFE_VALUE_LENGTH = 160
_TEMPORARY_OUTCOMES = frozenset({"rate_limit", "timeout", "network", "server_error"})
_CONTRACT_OUTCOMES = frozenset({"response_schema", "http_error"})


@dataclass(frozen=True)
class ProviderProbeResult:
    role: Literal["vlm", "embedding"]
    outcome: ProbeOutcome
    provider: str
    model: str
    host: str
    status: int | None
    duration_ms: int
    provider_code: str | None = None
    request_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_exit_code(results: tuple[ProviderProbeResult, ...]) -> int:
    """Return the stable CLI exit code for a complete probe result set."""
    outcomes = {result.outcome for result in results if not result.ok}
    if not outcomes:
        return 0
    if "configuration" in outcomes:
        return 2
    if outcomes & {"authentication", "quota"}:
        return 3
    if outcomes & _TEMPORARY_OUTCOMES:
        return 4
    if outcomes & _CONTRACT_OUTCOMES:
        return 5
    return 5


def probe_recorded_video_providers(
    config: AppConfig,
    *,
    timeout_sec: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> tuple[ProviderProbeResult, ...]:
    """Probe the active VLM and embedding endpoints without recording credentials."""
    resolved = resolve_runtime_config(config)
    roles: tuple[tuple[Literal["vlm", "embedding"], ResolvedRoleConfig | None], ...] = (
        ("embedding", resolved.embedding),
        ("vlm", resolved.vlm),
    )
    results: list[ProviderProbeResult] = []
    with httpx.Client(timeout=timeout_sec, trust_env=False, transport=transport) as client:
        for role_name, role in roles:
            results.append(_probe_role(client, role_name, role))
    return tuple(results)


def _probe_role(
    client: httpx.Client,
    role_name: Literal["vlm", "embedding"],
    role: ResolvedRoleConfig | None,
) -> ProviderProbeResult:
    if role is None:
        return _result(role_name, "configuration")

    identity = _safe_identity(role)
    if not role.api_key:
        return _result(role_name, "configuration", **identity)
    endpoint = "/embeddings" if role_name == "embedding" else "/chat/completions"
    try:
        url = _endpoint_url(role.base_url, endpoint)
    except ValueError:
        return _result(role_name, "configuration", **identity)

    payload = (
        {"model": role.model, "input": "production readiness probe"}
        if role_name == "embedding"
        else {
            "model": role.model,
            "messages": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_tokens": 4,
            "temperature": 0,
        }
    )
    started = time.monotonic()
    try:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {role.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    except httpx.TimeoutException:
        return _result(role_name, "timeout", duration_ms=_elapsed_ms(started), **identity)
    except httpx.RequestError:
        return _result(role_name, "network", duration_ms=_elapsed_ms(started), **identity)

    duration_ms = _elapsed_ms(started)
    provider_code = _provider_error_code(response)
    request_id = _safe_optional(response.headers.get("x-request-id") or response.headers.get("request-id"))
    if response.status_code == 200:
        outcome: ProbeOutcome = "ok" if _valid_success(role_name, response) else "response_schema"
    else:
        outcome = _classify_http_failure(response.status_code, provider_code)
    return _result(
        role_name,
        outcome,
        status=response.status_code,
        duration_ms=duration_ms,
        provider_code=provider_code,
        request_id=request_id,
        **identity,
    )


def _safe_identity(role: ResolvedRoleConfig) -> dict[str, str]:
    try:
        parsed = urlsplit(role.base_url)
        port = parsed.port
    except ValueError:
        host = "invalid"
    else:
        host = parsed.hostname or "invalid"
        if port is not None:
            host = f"{host}:{port}"
    return {
        "provider": _safe_value(role.provider),
        "model": _safe_value(role.model),
        "host": _safe_value(host),
    }


def _endpoint_url(base_url: str, endpoint: str) -> str:
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as error:
        raise ValueError("invalid provider URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid provider URL")
    return base_url.rstrip("/") + endpoint


def _classify_http_failure(status: int, provider_code: str | None) -> ProbeOutcome:
    if status == 401:
        return "authentication"
    if status == 403:
        return "quota" if provider_code and "quota" in provider_code.lower() else "authentication"
    if status == 429:
        return "rate_limit"
    if status == 408:
        return "timeout"
    if status >= 500:
        return "server_error"
    return "http_error"


def _valid_success(role: Literal["vlm", "embedding"], response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if role == "embedding":
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return False
        vector = data[0].get("embedding")
        return bool(vector) and isinstance(vector, list) and all(_finite_number(value) for value in vector)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    message = choices[0].get("message")
    return isinstance(message, dict) and _nonempty_content(message.get("content"))


def _nonempty_content(content: object) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict) and isinstance(item.get("text"), str) and bool(item["text"].strip()) for item in content
    )


def _finite_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(float(value))


def _provider_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    candidate = error.get("code") if isinstance(error, dict) else payload.get("code")
    return _safe_optional(candidate)


def _safe_optional(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    safe = _SAFE_CORRELATION_VALUE.sub("", value)[:_MAX_SAFE_VALUE_LENGTH]
    return safe or None


def _safe_value(value: str) -> str:
    return _SAFE_IDENTITY_VALUE.sub("", value)[:_MAX_SAFE_VALUE_LENGTH]


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _result(
    role: Literal["vlm", "embedding"],
    outcome: ProbeOutcome,
    *,
    provider: str = "unknown",
    model: str = "unknown",
    host: str = "unknown",
    status: int | None = None,
    duration_ms: int = 0,
    provider_code: str | None = None,
    request_id: str | None = None,
) -> ProviderProbeResult:
    return ProviderProbeResult(
        role=role,
        outcome=outcome,
        provider=provider,
        model=model,
        host=host,
        status=status,
        duration_ms=duration_ms,
        provider_code=provider_code,
        request_id=request_id,
    )
