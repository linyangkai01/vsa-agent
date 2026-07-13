from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REQUIRED_OUTPUT_FILES = ("manifest.json", "trace.jsonl", "qa-final.txt", "report-final.txt")
SHARED_REQUIRED_EVENTS = (
    "live_video_acceptance.run.started",
    "live_video_acceptance.video_understanding.shared",
    "live_video_acceptance.qa.from_shared_understanding",
    "live_video_acceptance.report.direct_report_agent",
    "live_video_acceptance.run.completed",
)
GRAPH_REQUIRED_EVENTS = (
    "live_video_acceptance.run.started",
    "top_agent.agent.request",
    "top_agent.agent.response",
    "top_agent.tool.call",
    "top_agent.tool.result",
    "top_agent.final",
    "live_video_acceptance.run.completed",
)
UNDERSTANDING_EVIDENCE_EVENTS = (
    "video_understanding.result",
    "lvs_video_understanding.completed",
    "live_video_acceptance.video_understanding.shared",
)
TOOL_ERROR_PREFIXES = ("Error:", "Exception:", "Traceback")


class LiveRunValidationResult(BaseModel):
    """Validation summary for one live-video run directory."""

    ok: bool
    run_dir: str
    mode: str
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trace_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def _event_types(events: list[dict[str, Any]]) -> list[str]:
    return [str(event.get("event_type", "")) for event in events]


def _file_is_nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _required_events_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "graph":
        return GRAPH_REQUIRED_EVENTS
    return SHARED_REQUIRED_EVENTS


def _top_agent_tool_errors(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for event in events:
        if event.get("event_type") != "top_agent.tool.result":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        preview = str(payload.get("result_preview", ""))
        if not preview.startswith(TOOL_ERROR_PREFIXES):
            continue
        tool_name = str(payload.get("tool_name", "<unknown>"))
        errors.append(f"TopAgent tool returned an error: {tool_name}: {preview}")
    return errors


def _model_usage_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    model_call_count = 0
    llm_call_count = 0
    vlm_call_count = 0
    total_tokens = 0
    for event in events:
        if event.get("event_type") != "model.invoke.response":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        model_call_count += 1
        model = str(payload.get("model", "") or "").lower()
        if "vl" in model or "vision" in model:
            vlm_call_count += 1
        else:
            llm_call_count += 1
        response = payload.get("response", {})
        if not isinstance(response, dict):
            continue
        usage = response.get("usage_metadata", {})
        if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
            total_tokens += int(usage["total_tokens"])
    return {
        "model_call_count": model_call_count,
        "llm_call_count": llm_call_count,
        "vlm_call_count": vlm_call_count,
        "total_tokens": total_tokens,
    }


def validate_live_run(run_dir: str | Path) -> LiveRunValidationResult:
    path = Path(run_dir)
    failures: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return LiveRunValidationResult(
            ok=False,
            run_dir=str(path),
            mode="unknown",
            failures=[f"Run directory does not exist: {path}"],
            summary={},
        )

    for filename in REQUIRED_OUTPUT_FILES:
        if not _file_is_nonempty(path / filename):
            failures.append(f"Required output file is missing or empty: {filename}")

    manifest_path = path / "manifest.json"
    trace_path = path / "trace.jsonl"
    manifest: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
    if trace_path.exists():
        events = _load_trace_events(trace_path)

    mode = str(manifest.get("mode") or "shared")
    event_types = _event_types(events)
    required_events = _required_events_for_mode(mode)
    missing_events = [event_type for event_type in required_events if event_type not in event_types]
    for event_type in missing_events:
        failures.append(f"Required trace event missing: {event_type}")

    for flow_name in ("qa", "report"):
        flow = manifest.get(flow_name, {})
        if flow.get("status") != "success":
            failures.append(f"Manifest flow is not successful: {flow_name}")

    if not manifest.get("llm_model"):
        failures.append("Manifest missing llm_model")
    if not manifest.get("vlm_model"):
        failures.append("Manifest missing vlm_model")
    if not manifest.get("active_profile"):
        failures.append("Manifest missing active_profile")

    has_understanding_evidence = any(event_type in event_types for event_type in UNDERSTANDING_EVIDENCE_EVENTS)
    if not has_understanding_evidence:
        failures.append("No video-understanding evidence event found")

    if mode == "graph" and "top_agent.tool.call" not in event_types:
        failures.append("Graph mode did not record a TopAgent tool call: top_agent.tool.call")

    tool_errors = _top_agent_tool_errors(events)
    failures.extend(tool_errors)
    metrics = manifest.get("metrics", {})
    has_metrics = isinstance(metrics, dict) and bool(metrics)
    model_usage = _model_usage_summary(events)
    lvs_completed_count = event_types.count("lvs_video_understanding.completed")
    if mode == "graph" and lvs_completed_count > 1:
        message = (
            "Repeated long-video understanding detected in graph mode: "
            f"lvs_video_understanding.completed={lvs_completed_count}"
        )
        if os.getenv("VSA_STRICT_GRAPH_LVS") == "1":
            failures.append(message)
        else:
            warnings.append(message)

    if not (path / "frames").exists():
        warnings.append("frames directory is missing")
    if not (path / "tool-results").exists():
        warnings.append("tool-results directory is missing")

    summary = {
        "mode": mode,
        "active_profile": manifest.get("active_profile"),
        "llm_model": manifest.get("llm_model"),
        "vlm_model": manifest.get("vlm_model"),
        "event_count": len(events),
        "required_events_present": not missing_events,
        "has_understanding_evidence": has_understanding_evidence,
        "has_metrics": has_metrics,
        "total_elapsed_sec": metrics.get("total_elapsed_sec") if isinstance(metrics, dict) else None,
        "estimated_model_call_count": metrics.get("estimated_model_call_count") if isinstance(metrics, dict) else None,
        "model_call_count": model_usage["model_call_count"],
        "llm_call_count": model_usage["llm_call_count"],
        "vlm_call_count": model_usage["vlm_call_count"],
        "total_tokens": model_usage["total_tokens"],
        "lvs_completed_count": lvs_completed_count,
        "tool_error_count": len(tool_errors),
        "qa_status": manifest.get("qa", {}).get("status"),
        "report_status": manifest.get("report", {}).get("status"),
    }
    return LiveRunValidationResult(
        ok=not failures,
        run_dir=str(path),
        mode=mode,
        failures=failures,
        warnings=warnings,
        summary=summary,
    )


def format_validation_result(result: LiveRunValidationResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"{status}: live run validation",
        f"run_dir: {result.run_dir}",
        f"mode: {result.mode}",
        f"summary: {json.dumps(result.summary, ensure_ascii=False, sort_keys=True)}",
    ]
    if result.failures:
        lines.append("failures:")
        lines.extend(f"- {failure}" for failure in result.failures)
    if result.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines)
