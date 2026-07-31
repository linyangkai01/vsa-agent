import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SENSITIVE_KEY_PARTS = {"authorization", "secret", "password", "token"}
_PRIVACY_TRACE_PREFIXES = (
    "lvs_video_understanding.",
    "model.astream.",
    "model.invoke.",
    "original_ui.",
    "report_agent.",
    "search_agent.",
    "top_agent.",
    "video_understanding.",
)
_TRACE_PATH_CONTEXT: ContextVar[str | None] = ContextVar("vsa_live_trace_path", default=None)
_ARTIFACT_DIR_CONTEXT: ContextVar[str | None] = ContextVar("vsa_live_artifact_dir", default=None)


@contextmanager
def live_trace_context(
    trace_path: str | Path | None = None,
    artifact_dir: str | Path | None = None,
) -> Iterator[None]:
    """Temporarily route live trace writes to request-local paths."""
    trace_token = _TRACE_PATH_CONTEXT.set(str(trace_path) if trace_path else None)
    artifact_token = _ARTIFACT_DIR_CONTEXT.set(str(artifact_dir) if artifact_dir else None)
    try:
        yield
    finally:
        _ARTIFACT_DIR_CONTEXT.reset(artifact_token)
        _TRACE_PATH_CONTEXT.reset(trace_token)


def live_trace_enabled() -> bool:
    """Return whether opt-in live trace logging is configured."""
    return bool((_TRACE_PATH_CONTEXT.get() or os.getenv("VSA_LIVE_TRACE_PATH") or "").strip())


def get_live_artifact_dir() -> Path | None:
    raw = (_ARTIFACT_DIR_CONTEXT.get() or os.getenv("VSA_LIVE_ARTIFACT_DIR") or "").strip()
    if raw:
        return Path(raw)
    trace_path = (_TRACE_PATH_CONTEXT.get() or os.getenv("VSA_LIVE_TRACE_PATH") or "").strip()
    if trace_path:
        return Path(trace_path).parent
    return None


def write_live_text_artifact(name: str, content: str) -> str | None:
    base_dir = get_live_artifact_dir()
    if base_dir is None:
        return None
    path = _resolve_artifact_path(base_dir, name)
    _ensure_private_directory(path.parent)
    path.write_text(content, encoding="utf-8")
    _ensure_private_file(path)
    return str(path)


def write_live_json_artifact(name: str, payload: dict[str, Any] | list[Any]) -> str | None:
    base_dir = get_live_artifact_dir()
    if base_dir is None:
        return None
    path = _resolve_artifact_path(base_dir, name)
    _ensure_private_directory(path.parent)
    path.write_text(
        json.dumps(serialize_live_trace_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _ensure_private_file(path)
    return str(path)


def write_live_binary_artifact(name: str, content: bytes) -> str | None:
    base_dir = get_live_artifact_dir()
    if base_dir is None:
        return None
    path = _resolve_artifact_path(base_dir, name)
    _ensure_private_directory(path.parent)
    path.write_bytes(content)
    _ensure_private_file(path)
    return str(path)


def serialize_live_trace_value(value: Any) -> Any:
    """Convert common runtime objects into JSON-safe trace values."""
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if _is_sensitive_key(str(key)) else serialize_live_trace_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [serialize_live_trace_value(item) for item in value]
    if isinstance(value, str):
        if value.startswith("data:image/") and ";base64," in value:
            header, encoded = value.split(",", 1)
            return f"{header},<{len(encoded)} base64 chars>"
        return value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return serialize_live_trace_value(value.model_dump())
    if hasattr(value, "content"):
        data: dict[str, Any] = {
            "type": value.__class__.__name__,
            "content": getattr(value, "content", ""),
        }
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = serialize_live_trace_value(tool_calls)
        additional_kwargs = getattr(value, "additional_kwargs", None)
        if additional_kwargs:
            data["additional_kwargs"] = serialize_live_trace_value(additional_kwargs)
        return data
    return repr(value)


def write_live_trace_event(event_type: str, payload: dict[str, Any]) -> None:
    """Append one JSONL live trace event when VSA_LIVE_TRACE_PATH is set."""
    trace_path = (_TRACE_PATH_CONTEXT.get() or os.getenv("VSA_LIVE_TRACE_PATH") or "").strip()
    if not trace_path:
        return

    path = Path(trace_path)
    _ensure_private_directory(path.parent)
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "payload": _privacy_safe_trace_payload(event_type, payload),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    _ensure_private_file(path)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def _ensure_private_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _privacy_safe_trace_payload(event_type: str, payload: dict[str, Any]) -> Any:
    """Keep search/agent traces useful without persisting provider inputs."""

    serialized = serialize_live_trace_value(payload)
    if not event_type.startswith(_PRIVACY_TRACE_PREFIXES):
        return serialized
    if not isinstance(serialized, dict):
        return {"redacted": True}

    allowed = {
        key: value
        for key, value in serialized.items()
        if key
        in {
            "iteration",
            "tool_count",
            "tool_name",
            "tool_call_id",
            "result_length",
            "cached",
            "has_tool_calls",
            "adapter",
            "model",
            "path",
            "critic_requested",
            "critic_applied",
            "query_sha256",
            "query_length",
            "result_count",
            "error_type",
            "cached_result_length",
            "context_item_count",
            "chunk_count",
            "chunk_duration_sec",
            "chunk_index",
            "duration_sec",
            "elapsed_sec",
            "event_count",
            "fps",
            "final_answer_length",
            "frame_count",
            "has_local_video_context",
            "has_selected_video",
            "has_segment",
            "raw_output_length",
            "max_frames",
            "max_frames_per_chunk",
            "markdown_length",
            "source_type",
            "summary_length",
            "total_frames",
            "validation_passed",
            "window_duration_sec",
            "window_end_sec",
            "window_start_sec",
        }
    }
    allowed["redacted_fields"] = sorted(key for key in serialized if key not in allowed)
    return allowed


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_")
    words = normalized.replace("_", " ")
    normalized = "".join(
        f"_{char.lower()}"
        if char.isupper()
        and index > 0
        and (
            words[index - 1].islower()
            or (words[index - 1].isupper() and index + 1 < len(words) and words[index + 1].islower())
        )
        else char.lower()
        for index, char in enumerate(words)
    ).replace(" ", "_")
    parts = [part for part in normalized.split("_") if part]
    has_api_key_parts = any(
        part == "api" and index + 1 < len(parts) and parts[index + 1] == "key" for index, part in enumerate(parts)
    )
    return (
        any(part in SENSITIVE_KEY_PARTS for part in parts) or normalized in {"apikey", "api_key"} or has_api_key_parts
    )


def _resolve_artifact_path(base_dir: Path, name: str) -> Path:
    base_path = base_dir.resolve()
    path = base_dir / name
    resolved_path = path.resolve()
    if resolved_path != base_path and base_path not in resolved_path.parents:
        raise ValueError("artifact path is outside live artifact directory")
    if path.exists():
        return _next_available_artifact_path(path)
    return path


def _next_available_artifact_path(path: Path) -> Path:
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = parent / f"{stem}-{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate artifact path for {path}")
