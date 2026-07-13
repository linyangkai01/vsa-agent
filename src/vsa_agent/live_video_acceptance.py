from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage

from vsa_agent.agents.data_models import AgentState
from vsa_agent.agents.report_agent import (
    ReportAgentInput,
    VideoReportCallable,
    VideoUnderstandingCallable,
    execute_report_agent,
)
from vsa_agent.agents.top_agent import build_graph
from vsa_agent.config import resolve_runtime_config
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.observability.live_trace import write_live_trace_event
from vsa_agent.registry import temporary_tool_override
from vsa_agent.tools.video_understanding import analyze_video

DEFAULT_QA_QUERY = "Describe what happened in this video and identify any safety risks."
REPORT_QUERY = "Generate a single-video Markdown inspection report using this video as evidence."
LiveVideoMode = Literal["shared", "graph"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _print_failure_summary(manifest: dict, manifest_path: Path) -> None:
    print("Live video acceptance failed", file=sys.stderr)
    print(f"  output_dir: {manifest['output_dir']}", file=sys.stderr)
    print(f"  manifest: {manifest_path}", file=sys.stderr)
    for flow_name in ("qa", "report"):
        flow = manifest.get(flow_name, {})
        if flow.get("status") != "failed":
            continue
        error = flow.get("error", {})
        error_type = error.get("type", "Error")
        message = error.get("message", "")
        print(f"  {flow_name}: {error_type}: {message}", file=sys.stderr)


def _elapsed_seconds(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return round(max((ended - started).total_seconds(), 0.0), 3)


def _flow_elapsed_seconds(flow: dict[str, Any] | None) -> float | None:
    if not isinstance(flow, dict):
        return None
    return _elapsed_seconds(
        str(flow.get("started_at", "") or ""),
        str(flow.get("ended_at", "") or ""),
    )


def _estimate_shared_model_call_count(manifest: dict[str, Any]) -> int | None:
    if manifest.get("mode") != "shared":
        return None
    video_understanding = manifest.get("video_understanding", {})
    if not isinstance(video_understanding, dict) or video_understanding.get("status") != "success":
        return None
    chunk_count = video_understanding.get("chunk_count")
    if isinstance(chunk_count, int) and chunk_count > 0:
        return chunk_count
    return 1


def _build_run_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "total_elapsed_sec": _elapsed_seconds(
            str(manifest.get("started_at", "") or ""),
            str(manifest.get("ended_at", "") or ""),
        ),
        "qa_elapsed_sec": _flow_elapsed_seconds(manifest.get("qa", {})),
        "report_elapsed_sec": _flow_elapsed_seconds(manifest.get("report", {})),
        "video_understanding_elapsed_sec": _flow_elapsed_seconds(manifest.get("video_understanding", {})),
        "estimated_model_call_count": _estimate_shared_model_call_count(manifest),
    }
    if manifest.get("mode") == "graph":
        metrics["graph_qa_elapsed_sec"] = metrics["qa_elapsed_sec"]
        metrics["graph_report_elapsed_sec"] = metrics["report_elapsed_sec"]
    return metrics


async def _run_shared_video_understanding(*, video_path: Path, query: str) -> tuple[UnderstandingResult | None, dict]:
    started_at = _now()
    try:
        understanding_result = await analyze_video(video_path=str(video_path), query=query)
        write_live_trace_event(
            "live_video_acceptance.video_understanding.shared",
            {
                "video_path": str(video_path),
                "query": query,
                "summary_length": len(understanding_result.summary_text),
                "chunk_count": understanding_result.metadata.get("chunk_count"),
                "event_count": len(understanding_result.events),
            },
        )
        return understanding_result, {
            "status": "success",
            "started_at": started_at,
            "ended_at": _now(),
            "chunk_count": understanding_result.metadata.get("chunk_count"),
            "event_count": len(understanding_result.events),
            "summary_length": len(understanding_result.summary_text),
        }
    except Exception as exc:
        write_live_trace_event(
            "live_video_acceptance.video_understanding.shared.failed",
            {
                "video_path": str(video_path),
                "query": query,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        )
        return None, {
            "status": "failed",
            "started_at": started_at,
            "ended_at": _now(),
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
        }


async def _run_direct_report(
    *,
    video_path: Path,
    query: str,
    output_path: Path,
    understanding_result: UnderstandingResult | None = None,
) -> dict:
    started_at = _now()
    try:
        if understanding_result is None:
            raise ValueError("Shared understanding result is not available")

        async def reused_video_understanding(**_kwargs):
            return understanding_result

        result = await execute_report_agent(
            ReportAgentInput(video_path=str(video_path), query=query),
            video_understanding_fn=reused_video_understanding,
        )
        markdown_content = str(result.side_effects.get("markdown_content", ""))
        if not markdown_content.lstrip().startswith("#"):
            raise ValueError("Markdown report was not generated by report_agent")

        output_path.write_text(markdown_content, encoding="utf-8")
        report_md_path = output_path.with_name("report.md")
        report_md_path.write_text(markdown_content, encoding="utf-8")
        write_live_trace_event(
            "live_video_acceptance.report.direct_report_agent",
            {
                "video_path": str(video_path),
                "query": query,
                "output_path": str(output_path),
                "markdown_path": str(report_md_path),
                "markdown_length": len(markdown_content),
                "validation_passed": result.metadata.get("validation_passed"),
            },
        )
        return {
            "status": "success",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
            "markdown_path": str(report_md_path),
        }
    except Exception as exc:
        write_live_trace_event(
            "live_video_acceptance.report.direct_report_agent.failed",
            {
                "video_path": str(video_path),
                "query": query,
                "output_path": str(output_path),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        )
        return {
            "status": "failed",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
        }


async def _run_direct_video_qa(
    *,
    video_path: Path,
    query: str,
    output_path: Path,
    understanding_result: UnderstandingResult | None,
    understanding_flow: dict,
) -> dict:
    started_at = _now()
    try:
        if understanding_result is None:
            error = understanding_flow.get("error", {})
            raise RuntimeError(str(error.get("message", "Shared video understanding failed")))

        final_answer = understanding_result.summary_text
        output_path.write_text(str(final_answer), encoding="utf-8")
        write_live_trace_event(
            "live_video_acceptance.qa.from_shared_understanding",
            {
                "video_path": str(video_path),
                "query": query,
                "output_path": str(output_path),
                "answer_length": len(str(final_answer)),
                "chunk_count": understanding_result.metadata.get("chunk_count"),
            },
        )
        return {
            "status": "success",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
        }
    except Exception as exc:
        write_live_trace_event(
            "live_video_acceptance.qa.from_shared_understanding.failed",
            {
                "video_path": str(video_path),
                "query": query,
                "output_path": str(output_path),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        )
        return {
            "status": "failed",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
        }


def _extract_final_answer(result_state) -> str:
    if isinstance(result_state, dict):
        return str(result_state.get("final_answer", ""))
    return str(getattr(result_state, "final_answer", ""))


def _build_graph_report_prompt(video_path: Path, qa_answer: str) -> str:
    return (
        "Generate a Markdown inspection report from the existing QA/video understanding below. "
        "Do not call video_understanding again unless the QA understanding is empty or clearly insufficient. "
        "Prefer report_agent if a report tool is needed; do not call low-level report formatting tools directly. "
        f"Video path: {video_path}\n\n"
        f"Request: {REPORT_QUERY}\n\n"
        "Existing QA/video understanding to reuse:\n"
        f"{qa_answer}"
    )


def _build_reused_report_agent_tool(
    *,
    video_path: Path,
    qa_answer: str,
    video_understanding_fn: VideoUnderstandingCallable | None = None,
    video_report_gen_fn: VideoReportCallable | None = None,
):
    source_video_path = str(video_path)

    async def reused_video_understanding(**kwargs):
        del kwargs
        return UnderstandingResult(
            query=REPORT_QUERY,
            source_type="video_file",
            summary_text=qa_answer,
            chunks=[],
            events=[],
            metadata={"reused_from": "graph_qa_answer"},
        )

    async def reused_report_agent_tool(video_path: str = "", sensor_id: str = "", query: str = REPORT_QUERY) -> str:
        del video_path, sensor_id
        result = await execute_report_agent(
            ReportAgentInput(video_path=source_video_path, query=query or REPORT_QUERY),
            video_understanding_fn=video_understanding_fn or reused_video_understanding,
            video_report_gen_fn=video_report_gen_fn,
        )
        return str(result.side_effects.get("markdown_content", ""))

    reused_report_agent_tool._tool_name = "report_agent"
    reused_report_agent_tool._tool_description = (
        "Generate a Markdown report by reusing the existing graph QA/video understanding. "
        "Does not call video_understanding again."
    )
    return reused_report_agent_tool


def _build_deferred_report_agent_tool():
    async def deferred_report_agent_tool(video_path: str = "", sensor_id: str = "", query: str = REPORT_QUERY) -> str:
        del video_path, sensor_id, query
        return (
            "Report generation is deferred until after QA. "
            "Use the existing video_understanding result to answer the user."
        )

    deferred_report_agent_tool._tool_name = "report_agent"
    deferred_report_agent_tool._tool_description = (
        "Report generation is deferred during QA. Answer the user from video_understanding first."
    )
    return deferred_report_agent_tool


async def _run_graph_flow(
    graph,
    *,
    flow_name: str,
    run_id: str,
    prompt: str,
    output_path: Path,
) -> dict:
    started_at = _now()
    try:
        state = AgentState(current_message=HumanMessage(content=prompt))
        result_state = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": f"{run_id}-{flow_name}"}},
        )
        final_answer = _extract_final_answer(result_state)
        output_path.write_text(final_answer, encoding="utf-8")
        write_live_trace_event(
            "live_video_acceptance.graph_flow.completed",
            {
                "flow_name": flow_name,
                "output_path": str(output_path),
                "answer_length": len(final_answer),
            },
        )
        return {
            "status": "success",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
            "answer_preview": final_answer[:4000],
        }
    except Exception as exc:
        write_live_trace_event(
            "live_video_acceptance.graph_flow.failed",
            {
                "flow_name": flow_name,
                "output_path": str(output_path),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        )
        return {
            "status": "failed",
            "started_at": started_at,
            "ended_at": _now(),
            "output_path": str(output_path),
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
        }


async def _run_graph_video_acceptance(
    *,
    run_id: str,
    video_path: Path,
    qa_query: str,
    qa_output_path: Path,
    report_output_path: Path,
) -> tuple[dict, dict, dict | None]:
    graph = await build_graph()
    qa_prompt = (
        "You must analyze the local video file with available tools. "
        "Do not guess from the filename. "
        f"Video path: {video_path}\n\n"
        f"User question: {qa_query}"
    )
    deferred_report_agent = _build_deferred_report_agent_tool()
    with temporary_tool_override(
        "report_agent",
        deferred_report_agent,
        description=getattr(deferred_report_agent, "_tool_description", ""),
    ):
        qa_flow = await _run_graph_flow(
            graph,
            flow_name="qa",
            run_id=run_id,
            prompt=qa_prompt,
            output_path=qa_output_path,
        )
    qa_answer = qa_output_path.read_text(encoding="utf-8") if qa_output_path.exists() else ""
    reused_report_agent = _build_reused_report_agent_tool(video_path=video_path, qa_answer=qa_answer)
    with temporary_tool_override(
        "report_agent",
        reused_report_agent,
        description=getattr(reused_report_agent, "_tool_description", ""),
    ):
        report_flow = await _run_graph_flow(
            graph,
            flow_name="report",
            run_id=run_id,
            prompt=_build_graph_report_prompt(video_path, qa_answer),
            output_path=report_output_path,
        )
    return qa_flow, report_flow, None


async def run_live_top_agent_video_acceptance(
    video_path: str = "",
    qa_query: str | None = None,
    output_root: str | Path | None = None,
    mode: LiveVideoMode = "shared",
) -> int:
    if mode not in ("shared", "graph"):
        raise ValueError(f"Unknown live video acceptance mode: {mode}")

    runtime_config = resolve_runtime_config()
    video_path = video_path or runtime_config.runtime.video_path
    output_root = output_root or runtime_config.runtime.trace_dir
    qa_query = qa_query or runtime_config.runtime.qa_query

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    run_id = _new_run_id()
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tool-results").mkdir(exist_ok=True)
    (run_dir / "frames").mkdir(exist_ok=True)

    trace_path = run_dir / "trace.jsonl"
    os.environ["VSA_LIVE_TRACE_PATH"] = str(trace_path)
    os.environ["VSA_LIVE_ARTIFACT_DIR"] = str(run_dir)

    qa_text = qa_query or DEFAULT_QA_QUERY

    manifest = {
        "run_id": run_id,
        "video_path": str(path),
        "qa_query": qa_text,
        "report_query": REPORT_QUERY,
        "active_profile": runtime_config.active_profile,
        "llm_backend": runtime_config.llm.backend,
        "llm_base_url": runtime_config.llm.base_url,
        "llm_model": runtime_config.llm.model,
        "vlm_backend": runtime_config.vlm.backend,
        "vlm_base_url": runtime_config.vlm.base_url,
        "vlm_model": runtime_config.vlm.model,
        "config_path": os.getenv("VSA_CONFIG", ""),
        "mode": mode,
        "trace_path": str(trace_path),
        "output_dir": str(run_dir),
        "started_at": _now(),
    }
    write_live_trace_event(
        "live_video_acceptance.run.started",
        {
            "run_id": run_id,
            "video_path": str(path),
            "qa_query": qa_text,
            "report_query": REPORT_QUERY,
            "mode": mode,
        },
    )

    if mode == "graph":
        manifest["qa"], manifest["report"], manifest["video_understanding"] = await _run_graph_video_acceptance(
            run_id=run_id,
            video_path=path,
            qa_query=qa_text,
            qa_output_path=run_dir / "qa-final.txt",
            report_output_path=run_dir / "report-final.txt",
        )
    else:
        understanding_result, manifest["video_understanding"] = await _run_shared_video_understanding(
            video_path=path,
            query=qa_text,
        )
        manifest["qa"] = await _run_direct_video_qa(
            video_path=path,
            query=qa_text,
            output_path=run_dir / "qa-final.txt",
            understanding_result=understanding_result,
            understanding_flow=manifest["video_understanding"],
        )
        manifest["report"] = await _run_direct_report(
            video_path=path,
            query=REPORT_QUERY,
            output_path=run_dir / "report-final.txt",
            understanding_result=understanding_result,
        )
    manifest["ended_at"] = _now()
    manifest["metrics"] = _build_run_metrics(manifest)

    manifest_path = run_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    write_live_trace_event(
        "live_video_acceptance.run.completed",
        {
            "run_id": run_id,
            "qa_status": manifest["qa"]["status"],
            "report_status": manifest["report"]["status"],
            "output_dir": str(run_dir),
            "metrics": manifest["metrics"],
        },
    )
    if manifest["qa"]["status"] == "success" and manifest["report"]["status"] == "success":
        return 0
    _print_failure_summary(manifest, manifest_path)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", nargs="?", default="")
    parser.add_argument("qa_query", nargs="?", default=None)
    parser.add_argument("--mode", choices=["shared", "graph"], default="shared")
    args = parser.parse_args()
    return asyncio.run(run_live_top_agent_video_acceptance(args.video_path, args.qa_query, mode=args.mode))


if __name__ == "__main__":
    raise SystemExit(main())
