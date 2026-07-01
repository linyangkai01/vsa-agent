import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


TEST_VALIDATOR_DIR = Path("artifacts/test-live-run-validator")


@pytest.fixture
def validator_dir():
    shutil.rmtree(TEST_VALIDATOR_DIR, ignore_errors=True)
    TEST_VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_VALIDATOR_DIR
    shutil.rmtree(TEST_VALIDATOR_DIR, ignore_errors=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_trace(path: Path, event_types: list[str]) -> None:
    path.write_text(
        "\n".join(json.dumps({"event_type": event_type, "payload": {}}, ensure_ascii=False) for event_type in event_types)
        + "\n",
        encoding="utf-8",
    )


def _write_trace_events(path: Path, events: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def _create_base_run(base_dir: Path, *, mode: str = "graph") -> Path:
    run_dir = base_dir / "run"
    run_dir.mkdir()
    (run_dir / "qa-final.txt").write_text("qa answer", encoding="utf-8")
    (run_dir / "report-final.txt").write_text("# Report\n\nreport answer", encoding="utf-8")
    (run_dir / "report.md").write_text("# Report\n\nreport answer", encoding="utf-8")
    (run_dir / "frames").mkdir()
    (run_dir / "tool-results").mkdir()
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": "unit-run",
            "mode": mode,
            "active_profile": "dashscope_remote",
            "llm_model": "qwen3.7-plus",
            "vlm_model": "qwen3-vl-flash-2025-10-15",
            "video_path": "/data/project/lyk/video/1597042367-1-192.mp4",
            "qa": {"status": "success", "output_path": str(run_dir / "qa-final.txt")},
            "report": {
                "status": "success",
                "output_path": str(run_dir / "report-final.txt"),
                "markdown_path": str(run_dir / "report.md"),
            },
            "video_understanding": {"status": "success"},
            "metrics": {
                "total_elapsed_sec": 12.3,
                "qa_elapsed_sec": 4.0,
                "report_elapsed_sec": 5.0,
                "video_understanding_elapsed_sec": 3.0,
                "estimated_model_call_count": 1,
            },
        },
    )
    return run_dir


def test_validate_live_run_passes_for_complete_graph_business_flow(validator_dir):
    from vsa_agent.live_run_validator import validate_live_run

    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace(
        run_dir / "trace.jsonl",
        [
            "live_video_acceptance.run.started",
            "top_agent.agent.request",
            "top_agent.agent.response",
            "top_agent.tool.call",
            "video_understanding.result",
            "top_agent.tool.result",
            "top_agent.final",
            "live_video_acceptance.run.completed",
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is True
    assert result.mode == "graph"
    assert result.summary["required_events_present"] is True
    assert result.failures == []


def test_validate_live_run_passes_for_complete_shared_business_flow(validator_dir):
    from vsa_agent.live_run_validator import validate_live_run

    run_dir = _create_base_run(validator_dir, mode="shared")
    _write_trace(
        run_dir / "trace.jsonl",
        [
            "live_video_acceptance.run.started",
            "lvs_video_understanding.completed",
            "live_video_acceptance.video_understanding.shared",
            "live_video_acceptance.qa.from_shared_understanding",
            "live_video_acceptance.report.direct_report_agent",
            "live_video_acceptance.run.completed",
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is True
    assert result.mode == "shared"
    assert result.summary["has_understanding_evidence"] is True
    assert result.summary["has_metrics"] is True
    assert result.summary["total_elapsed_sec"] == 12.3


def test_validate_live_run_fails_when_graph_tool_call_is_missing(validator_dir):
    from vsa_agent.live_run_validator import validate_live_run

    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace(
        run_dir / "trace.jsonl",
        [
            "live_video_acceptance.run.started",
            "top_agent.agent.request",
            "top_agent.agent.response",
            "top_agent.final",
            "live_video_acceptance.run.completed",
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is False
    assert any("top_agent.tool.call" in failure for failure in result.failures)
    assert result.summary["required_events_present"] is False


def test_validate_live_run_fails_when_top_agent_tool_result_contains_error(validator_dir):
    from vsa_agent.live_run_validator import validate_live_run

    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace_events(
        run_dir / "trace.jsonl",
        [
            {"event_type": "live_video_acceptance.run.started", "payload": {}},
            {"event_type": "top_agent.agent.request", "payload": {}},
            {"event_type": "top_agent.agent.response", "payload": {"has_tool_calls": True}},
            {"event_type": "top_agent.tool.call", "payload": {"tool_name": "video_report_gen"}},
            {
                "event_type": "top_agent.tool.result",
                "payload": {
                    "tool_name": "video_report_gen",
                    "result_preview": "Error: generate_video_report() got an unexpected keyword argument 'section_id'",
                },
            },
            {"event_type": "video_understanding.result", "payload": {}},
            {"event_type": "top_agent.final", "payload": {"final_answer": "# Report"}},
            {"event_type": "live_video_acceptance.run.completed", "payload": {}},
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is False
    assert any("TopAgent tool returned an error" in failure for failure in result.failures)
    assert result.summary["tool_error_count"] == 1


def test_validate_live_run_summarizes_model_usage_and_warns_on_repeated_graph_lvs(validator_dir):
    from vsa_agent.live_run_validator import validate_live_run

    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace_events(
        run_dir / "trace.jsonl",
        [
            {"event_type": "live_video_acceptance.run.started", "payload": {}},
            {"event_type": "top_agent.agent.request", "payload": {}},
            {
                "event_type": "model.invoke.response",
                "payload": {
                    "model": "qwen3.7-plus",
                    "response": {"usage_metadata": {"total_tokens": 100}},
                },
            },
            {"event_type": "top_agent.agent.response", "payload": {"has_tool_calls": True}},
            {"event_type": "top_agent.tool.call", "payload": {"tool_name": "video_understanding"}},
            {
                "event_type": "model.invoke.response",
                "payload": {
                    "model": "qwen3-vl-flash-2025-10-15",
                    "response": {"usage_metadata": {"total_tokens": 200}},
                },
            },
            {"event_type": "video_understanding.result", "payload": {}},
            {"event_type": "top_agent.tool.result", "payload": {"tool_name": "video_understanding", "result_preview": "ok"}},
            {"event_type": "top_agent.final", "payload": {"final_answer": "answer"}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "live_video_acceptance.run.completed", "payload": {}},
        ],
    )

    result = validate_live_run(run_dir)

    assert result.summary["model_call_count"] == 2
    assert result.summary["llm_call_count"] == 1
    assert result.summary["vlm_call_count"] == 1
    assert result.summary["total_tokens"] == 300
    assert result.summary["lvs_completed_count"] == 2
    assert any("Repeated long-video understanding" in warning for warning in result.warnings)


def test_validate_live_run_can_fail_on_repeated_graph_lvs_when_strict(validator_dir, monkeypatch):
    from vsa_agent.live_run_validator import validate_live_run

    monkeypatch.setenv("VSA_STRICT_GRAPH_LVS", "1")
    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace_events(
        run_dir / "trace.jsonl",
        [
            {"event_type": "live_video_acceptance.run.started", "payload": {}},
            {"event_type": "top_agent.agent.request", "payload": {}},
            {"event_type": "top_agent.agent.response", "payload": {"has_tool_calls": True}},
            {"event_type": "top_agent.tool.call", "payload": {"tool_name": "video_understanding"}},
            {"event_type": "video_understanding.result", "payload": {}},
            {
                "event_type": "top_agent.tool.result",
                "payload": {"tool_name": "video_understanding", "result_preview": "ok"},
            },
            {"event_type": "top_agent.final", "payload": {"final_answer": "answer"}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "lvs_video_understanding.completed", "payload": {}},
            {"event_type": "live_video_acceptance.run.completed", "payload": {}},
        ],
    )

    result = validate_live_run(run_dir)

    assert result.ok is False
    assert any("Repeated long-video understanding" in failure for failure in result.failures)


def test_validate_run_cli_returns_nonzero_and_prints_failures(validator_dir):
    run_dir = _create_base_run(validator_dir, mode="graph")
    _write_trace(run_dir / "trace.jsonl", ["live_video_acceptance.run.started"])

    result = subprocess.run(
        [sys.executable, "-m", "vsa_agent", "validate-run", str(run_dir)],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": "src"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "top_agent.tool.call" in result.stdout
