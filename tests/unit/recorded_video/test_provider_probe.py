from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from vsa_agent.config import AppConfig
from vsa_agent.recorded_video.provider_probe import probe_exit_code, probe_recorded_video_providers

_SECRET = "probe-canary-secret"


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", _SECRET)
    return AppConfig(
        active_profile="production",
        backends={
            "remote": {
                "provider": "openai_compatible",
                "base_url": "https://provider.test/v1",
                "api_key_env": "TEST_PROVIDER_API_KEY",
            }
        },
        profiles={
            "production": {
                "llm": {"backend": "remote", "model": "llm-model"},
                "vlm": {"backend": "remote", "model": "vlm-model"},
                "embedding": {"backend": "remote", "model": "embedding-model"},
            }
        },
        search={"allow_mock_fallback": False, "force_mock_embedding": False},
        recorded_video={"enabled": True, "data_root": tmp_path},
    )


def test_probe_succeeds_for_valid_embedding_and_vlm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path, monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {_SECRET}"
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(handler))

    assert [result.role for result in results] == ["embedding", "vlm"]
    assert all(result.ok for result in results)
    assert probe_exit_code(results) == 0
    assert [request.url.path for request in requests] == ["/v1/embeddings", "/v1/chat/completions"]
    assert _SECRET not in json.dumps([result.to_dict() for result in results])


@pytest.mark.parametrize(
    ("status", "payload", "outcome", "exit_code"),
    [
        (401, {"error": {"code": "InvalidApiKey"}}, "authentication", 3),
        (403, {"error": {"code": "AllocationQuota.FreeTierOnly"}}, "quota", 3),
        (403, {"error": {"code": "Forbidden"}}, "authentication", 3),
        (408, {"error": {"code": "RequestTimeout"}}, "timeout", 4),
        (429, {"error": {"code": "RateLimit"}}, "rate_limit", 4),
        (503, {"error": {"code": "Unavailable"}}, "server_error", 4),
        (422, {"error": {"code": "BadPayload"}}, "http_error", 5),
    ],
)
def test_probe_classifies_http_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: dict,
    outcome: str,
    exit_code: int,
):
    config = _config(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        return httpx.Response(
            status,
            json=payload,
            headers={"x-request-id": "request-id/unsafe value"},
        )

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(handler))
    vlm = next(result for result in results if result.role == "vlm")

    assert vlm.outcome == outcome
    assert vlm.request_id == "request-idunsafevalue"
    assert probe_exit_code(results) == exit_code
    assert _SECRET not in json.dumps([result.to_dict() for result in results])


@pytest.mark.parametrize("role", ["embedding", "vlm"])
def test_probe_rejects_invalid_success_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
):
    config = _config(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        current_role = "embedding" if request.url.path.endswith("/embeddings") else "vlm"
        if current_role == role:
            return httpx.Response(200, json={"unexpected": True})
        if current_role == "embedding":
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(handler))

    failed = next(result for result in results if result.role == role)
    assert failed.outcome == "response_schema"
    assert probe_exit_code(results) == 5


def test_probe_reports_network_error_without_exception_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Authorization: Bearer {_SECRET}", request=request)

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(handler))
    serialized = json.dumps([result.to_dict() for result in results])

    assert {result.outcome for result in results} == {"network"}
    assert probe_exit_code(results) == 4
    assert _SECRET not in serialized
    assert "Authorization" not in serialized


def test_probe_reports_missing_key_as_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path, monkeypatch)
    monkeypatch.delenv("TEST_PROVIDER_API_KEY")

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(lambda _request: None))

    assert {result.outcome for result in results} == {"configuration"}
    assert probe_exit_code(results) == 2


def test_probe_filters_and_truncates_untrusted_correlation_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _config(tmp_path, monkeypatch)
    unsafe_request_id = "request:/ value-" + ("x" * 200)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        return httpx.Response(
            403,
            json={"error": {"code": {"unexpected": _SECRET}}},
            headers={"x-request-id": unsafe_request_id},
        )

    results = probe_recorded_video_providers(config, transport=httpx.MockTransport(handler))
    vlm = next(result for result in results if result.role == "vlm")

    assert vlm.provider_code is None
    assert vlm.request_id == ("requestvalue-" + ("x" * 200))[:160]
    assert ":" not in vlm.request_id
    assert "/" not in vlm.request_id
    assert _SECRET not in json.dumps(vlm.to_dict())
