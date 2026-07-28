import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import (
    AppConfig,
    BackendConfig,
    ProfileConfig,
    RecordedVideoConfig,
    RoleBindingConfig,
    SearchBackendConfig,
)


def _production_config() -> AppConfig:
    backend = BackendConfig(
        provider="openai_compatible",
        base_url="https://private-provider.example/v1",
        api_key="super-secret",
    )
    return AppConfig(
        active_profile="production",
        backends={"dashscope": backend},
        profiles={
            "production": ProfileConfig(
                llm=RoleBindingConfig(backend="dashscope", model="qwen-plus"),
                vlm=RoleBindingConfig(backend="dashscope", model="qwen-vl-max"),
                embedding=RoleBindingConfig(backend="dashscope", model="text-embedding-v4"),
            )
        },
        recorded_video=RecordedVideoConfig(enabled=True),
        search=SearchBackendConfig(allow_mock_fallback=False, force_mock_embedding=False),
    )


def test_runtime_evidence_is_redacted_and_stable(monkeypatch):
    from vsa_agent.api import runtime_evidence

    monkeypatch.delenv("VSA_PROFILE", raising=False)
    config = _production_config()
    monkeypatch.setattr(runtime_evidence, "get_config", lambda: config)
    app = FastAPI()
    app.include_router(runtime_evidence.router)
    client = TestClient(app)

    first = client.get("/api/v1/runtime/evidence")
    second = client.get("/api/v1/runtime/evidence")

    assert first.status_code == 200
    assert first.json() == second.json()
    payload = first.json()
    assert payload["real_provider_ready"] is True
    assert payload["roles"]["llm"] == {
        "backend": "dashscope",
        "provider": "openai_compatible",
        "model": "qwen-plus",
        "api_key_required": True,
        "api_key_configured": True,
        "is_mock": False,
    }
    assert len(payload["config_fingerprint"]) == 64
    response_text = first.text
    assert "super-secret" not in response_text
    assert "private-provider.example" not in response_text


def test_runtime_evidence_rejects_mock_fallback_and_mock_role(monkeypatch):
    from vsa_agent.api.runtime_evidence import build_runtime_evidence

    monkeypatch.delenv("VSA_PROFILE", raising=False)
    config = _production_config()
    config.search.allow_mock_fallback = True
    config.profiles["production"].embedding = RoleBindingConfig(backend="dashscope", model="mock-embedding")

    evidence = build_runtime_evidence(config)

    assert evidence.real_provider_ready is False
    assert evidence.search.allow_mock_fallback is True
    assert evidence.roles["embedding"] is not None
    assert evidence.roles["embedding"].is_mock is True


def test_runtime_evidence_rejects_explicit_test_only_backend(monkeypatch):
    from vsa_agent.api.runtime_evidence import build_runtime_evidence

    monkeypatch.delenv("VSA_PROFILE", raising=False)
    config = _production_config()
    config.backends["dashscope"].test_only = True

    evidence = build_runtime_evidence(config)

    assert evidence.real_provider_ready is False
    assert all(role is not None and role.is_mock for role in evidence.roles.values())


def test_runtime_evidence_route_is_registered():
    from vsa_agent.api.routes import app

    assert "/api/v1/runtime/evidence" in {route.path for route in app.routes}
    assert "/api/v1/runtime/chat-traces/{trace_id}/evidence" in {route.path for route in app.routes}


def test_chat_trace_evidence_is_redacted_and_correlated(tmp_path, monkeypatch):
    from vsa_agent.api import runtime_evidence
    from vsa_agent.api.original_ui_chat import ORIGINAL_UI_TRACE_ROOT_ENV

    trace_id = "20260729T010203000000Z-conversation-message"
    trace_dir = tmp_path / trace_id
    trace_dir.mkdir()
    (trace_dir / "request.json").write_text(
        json.dumps(
            {
                "conversation_id": "conversation-1",
                "user_message_id": "message-1",
                "selected_asset_id": "asset-1",
                "selected_segment_id": "segment-1",
                "message": "must not be returned",
            }
        ),
        encoding="utf-8",
    )
    events = [
        {"event_type": "original_ui.chat.request", "payload": {}},
        {"event_type": "top_agent.tool.call", "payload": {"tool_name": "video_understanding"}},
        {"event_type": "video_understanding.result", "payload": {"request_id": "provider-123"}},
        {"event_type": "top_agent.tool.result", "payload": {}},
        {"event_type": "top_agent.final", "payload": {"final_answer": "A safe answer"}},
    ]
    (trace_dir / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    monkeypatch.setenv(ORIGINAL_UI_TRACE_ROOT_ENV, str(tmp_path))
    app = FastAPI()
    app.include_router(runtime_evidence.router)

    response = TestClient(app).get(f"/api/v1/runtime/chat-traces/{trace_id}/evidence")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "trace_id": trace_id,
        "conversation_id": "conversation-1",
        "user_message_id": "message-1",
        "selected_asset_id": "asset-1",
        "selected_segment_id": "segment-1",
        "event_types": [event["event_type"] for event in events],
        "missing_event_types": [],
        "video_tool_call_count": 1,
        "final_count": 1,
        "final_nonempty": True,
        "error_event_types": [],
        "provider_request_ids": ["provider-123"],
    }
    assert "must not be returned" not in response.text


def test_chat_trace_evidence_rejects_missing_or_unsafe_trace(tmp_path, monkeypatch):
    from vsa_agent.api import runtime_evidence
    from vsa_agent.api.original_ui_chat import ORIGINAL_UI_TRACE_ROOT_ENV

    monkeypatch.setenv(ORIGINAL_UI_TRACE_ROOT_ENV, str(tmp_path))
    app = FastAPI()
    app.include_router(runtime_evidence.router)
    client = TestClient(app)

    assert client.get("/api/v1/runtime/chat-traces/missing/evidence").status_code == 404
    assert client.get("/api/v1/runtime/chat-traces/..%2Foutside/evidence").status_code in {400, 404}
