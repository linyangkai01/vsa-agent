"""Redacted runtime evidence for real-provider acceptance gates."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vsa_agent.config import AppConfig, ResolvedRoleConfig, get_config, resolve_runtime_config

router = APIRouter(prefix="/api/v1", tags=["runtime"])

_MOCK_MARKER = re.compile(r"(?:^|[-_.])(mock|fake|stub|test)(?:$|[-_.])", re.IGNORECASE)
_TRACE_ID = re.compile(r"[A-Za-z0-9_-]{1,255}")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,160}")
_REQUIRED_CHAT_EVENTS = (
    "original_ui.chat.request",
    "top_agent.tool.call",
    "video_understanding.result",
    "top_agent.tool.result",
    "top_agent.final",
)
_MAX_TRACE_BYTES = 5 * 1024 * 1024


class RuntimeRoleEvidence(BaseModel):
    backend: str
    provider: str
    model: str
    api_key_required: bool
    api_key_configured: bool
    is_mock: bool


class RuntimeSearchEvidence(BaseModel):
    allow_mock_fallback: bool
    force_mock_embedding: bool


class RuntimeEvidence(BaseModel):
    schema_version: int = 1
    active_profile: str
    recorded_video_enabled: bool
    roles: dict[str, RuntimeRoleEvidence | None]
    search: RuntimeSearchEvidence
    real_provider_ready: bool
    config_fingerprint: str


class ChatTraceEvidence(BaseModel):
    schema_version: int = 1
    trace_id: str
    conversation_id: str
    user_message_id: str
    selected_asset_id: str
    selected_segment_id: str
    event_types: tuple[str, ...]
    missing_event_types: tuple[str, ...]
    video_tool_call_count: int
    final_count: int
    final_nonempty: bool
    error_event_types: tuple[str, ...]
    provider_request_ids: tuple[str, ...]


def _looks_mock(role: ResolvedRoleConfig) -> bool:
    return any(_MOCK_MARKER.search(value) for value in (role.backend, role.provider, role.model))


def _role_evidence(config: AppConfig, role: ResolvedRoleConfig | None) -> RuntimeRoleEvidence | None:
    if role is None:
        return None
    backend = config.backends.get(role.backend)
    api_key_required = backend.api_key_required if backend is not None else bool(role.api_key_env)
    return RuntimeRoleEvidence(
        backend=role.backend,
        provider=role.provider,
        model=role.model,
        api_key_required=api_key_required,
        api_key_configured=bool(role.api_key),
        is_mock=bool(backend and backend.test_only) or _looks_mock(role),
    )


def build_runtime_evidence(config: AppConfig) -> RuntimeEvidence:
    runtime = resolve_runtime_config(config)
    roles = {
        "llm": _role_evidence(config, runtime.llm),
        "vlm": _role_evidence(config, runtime.vlm),
        "embedding": _role_evidence(config, runtime.embedding),
    }
    search = RuntimeSearchEvidence(
        allow_mock_fallback=config.search.allow_mock_fallback,
        force_mock_embedding=config.search.force_mock_embedding,
    )
    required_roles = tuple(roles.values())
    real_provider_ready = (
        config.recorded_video.enabled
        and all(role is not None for role in required_roles)
        and all(
            role is not None and not role.is_mock and (not role.api_key_required or role.api_key_configured)
            for role in required_roles
        )
        and not search.allow_mock_fallback
        and not search.force_mock_embedding
    )
    safe_payload = {
        "schema_version": 1,
        "active_profile": runtime.active_profile,
        "recorded_video_enabled": config.recorded_video.enabled,
        "roles": {name: role.model_dump(mode="json") if role is not None else None for name, role in roles.items()},
        "search": search.model_dump(mode="json"),
        "real_provider_ready": real_provider_ready,
    }
    fingerprint = hashlib.sha256(
        json.dumps(safe_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RuntimeEvidence(**safe_payload, config_fingerprint=fingerprint)


@router.get("/runtime/evidence", response_model=RuntimeEvidence)
async def runtime_evidence() -> RuntimeEvidence:
    return build_runtime_evidence(get_config())


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_TRACE_BYTES:
            raise ValueError(f"{label} is too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"{label} is unreadable: {error}") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail=f"{label} must contain an object")
    return payload


def _read_trace_events(path: Path) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > _MAX_TRACE_BYTES:
            raise ValueError("trace is too large")
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"chat trace is unreadable: {error}") from None
    if any(not isinstance(event, dict) for event in events):
        raise HTTPException(status_code=422, detail="chat trace events must be objects")
    return events


def _provider_request_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"request_id", "requestId"} and isinstance(item, str) and _SAFE_REQUEST_ID.fullmatch(item):
                found.add(item)
            else:
                found.update(_provider_request_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_provider_request_ids(item))
    return found


@router.get("/runtime/chat-traces/{trace_id}/evidence", response_model=ChatTraceEvidence)
async def chat_trace_evidence(trace_id: str) -> ChatTraceEvidence:
    if _TRACE_ID.fullmatch(trace_id) is None:
        raise HTTPException(status_code=400, detail="invalid chat trace id")
    from vsa_agent.api.original_ui_chat import ORIGINAL_UI_TRACE_ROOT_ENV

    root_value = os.getenv(ORIGINAL_UI_TRACE_ROOT_ENV, "").strip()
    if not root_value:
        raise HTTPException(status_code=503, detail="chat trace root is not configured")
    try:
        root = Path(root_value).resolve(strict=True)
        trace_dir = (root / trace_id).resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=404, detail="chat trace not found") from None
    if trace_dir.parent != root or not trace_dir.is_dir():
        raise HTTPException(status_code=404, detail="chat trace not found")

    request_payload = _read_json(trace_dir / "request.json", "chat request evidence")
    events = _read_trace_events(trace_dir / "trace.jsonl")
    event_types = tuple(str(event.get("event_type", "")) for event in events)
    missing = tuple(event_type for event_type in _REQUIRED_CHAT_EVENTS if event_type not in event_types)
    video_tool_calls = [
        event
        for event in events
        if event.get("event_type") == "top_agent.tool.call"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("tool_name") == "video_understanding"
    ]
    final_events = [event for event in events if event.get("event_type") == "top_agent.final"]
    final_nonempty = len(final_events) == 1 and bool(
        str(final_events[0].get("payload", {}).get("final_answer", "")).strip()
        if isinstance(final_events[0].get("payload"), dict)
        else False
    )
    error_event_types = tuple(event_type for event_type in event_types if re.search(r"(?:^|[._])error$", event_type))
    request_ids: set[str] = set()
    for event in events:
        request_ids.update(_provider_request_ids(event.get("payload")))
    return ChatTraceEvidence(
        trace_id=trace_id,
        conversation_id=str(request_payload.get("conversation_id", "")),
        user_message_id=str(request_payload.get("user_message_id", "")),
        selected_asset_id=str(request_payload.get("selected_asset_id", "")),
        selected_segment_id=str(request_payload.get("selected_segment_id", "")),
        event_types=event_types,
        missing_event_types=missing,
        video_tool_call_count=len(video_tool_calls),
        final_count=len(final_events),
        final_nonempty=final_nonempty,
        error_event_types=error_event_types,
        provider_request_ids=tuple(sorted(request_ids)),
    )
