import json
import shutil
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from vsa_agent.agents.data_models import AgentOutput, AgentState
from vsa_agent.data_models.understanding import UnderstandingResult

TEST_RUNNER_DIR = Path("artifacts/test-live-top-agent-video-runner")


@pytest.fixture
def runner_dir():
    shutil.rmtree(TEST_RUNNER_DIR, ignore_errors=True)
    TEST_RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_RUNNER_DIR
    shutil.rmtree(TEST_RUNNER_DIR, ignore_errors=True)


@pytest.mark.asyncio
async def test_live_video_runner_graph_mode_invokes_top_agent_graph_with_thread_ids(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance
    from vsa_agent.observability.live_trace import write_live_trace_event

    calls = []

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            calls.append((state, config))
            write_live_trace_event(
                "top_agent.final",
                {"final_answer": f"graph answer {len(calls)}"},
            )
            return AgentState(
                current_message=state.current_message,
                final_answer=f"graph answer {len(calls)}",
            )

    async def fake_build_graph():
        return FakeGraph()

    monkeypatch.setattr("vsa_agent.live_video_acceptance.build_graph", fake_build_graph)
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(
        str(video_path),
        qa_query="what happened",
        output_root=runner_dir / "runs",
        mode="graph",
    )

    assert exit_code == 0
    assert len(calls) == 2
    assert isinstance(calls[0][0].current_message, HumanMessage)
    assert "what happened" in calls[0][0].current_message.content
    assert str(video_path) in calls[0][0].current_message.content
    assert "Markdown inspection report" in calls[1][0].current_message.content
    assert calls[0][1]["configurable"]["thread_id"].endswith("-qa")
    assert calls[1][1]["configurable"]["thread_id"].endswith("-report")

    run_dir = next((runner_dir / "runs").iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "graph"
    assert manifest["qa"]["status"] == "success"
    assert manifest["report"]["status"] == "success"
    assert manifest["metrics"]["total_elapsed_sec"] >= 0
    assert manifest["metrics"]["qa_elapsed_sec"] >= 0
    assert manifest["metrics"]["report_elapsed_sec"] >= 0
    assert manifest["metrics"]["graph_qa_elapsed_sec"] >= 0
    assert manifest["metrics"]["graph_report_elapsed_sec"] >= 0
    assert (run_dir / "qa-final.txt").read_text(encoding="utf-8") == "graph answer 1"
    assert (run_dir / "report-final.txt").read_text(encoding="utf-8") == "graph answer 2"
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "top_agent.final" in trace_text


@pytest.mark.asyncio
async def test_live_video_runner_graph_report_prompt_reuses_qa_answer(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance

    calls = []

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            calls.append((state, config))
            if config["configurable"]["thread_id"].endswith("-qa"):
                return AgentState(
                    current_message=state.current_message,
                    final_answer="QA understanding: worker at height without harness",
                )
            return AgentState(
                current_message=state.current_message,
                final_answer="# Report\n\nuses previous QA understanding",
            )

    async def fake_build_graph():
        return FakeGraph()

    monkeypatch.setattr("vsa_agent.live_video_acceptance.build_graph", fake_build_graph)
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(
        str(video_path),
        qa_query="what happened",
        output_root=runner_dir / "runs",
        mode="graph",
    )

    assert exit_code == 0
    report_prompt = calls[1][0].current_message.content
    assert "QA understanding: worker at height without harness" in report_prompt
    assert "Do not call video_understanding again" in report_prompt


@pytest.mark.asyncio
async def test_live_video_runner_reused_report_tool_does_not_reanalyze_video(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import _build_reused_report_agent_tool

    async def fake_generate_video_report(**kwargs):
        structured_report = kwargs["structured_report"]
        return {
            "markdown_content": f"# Report\n\n{structured_report.sections[0].summary_text}",
            "summary": "report summary",
            "downloads": {},
        }

    reused_tool = _build_reused_report_agent_tool(
        video_path=runner_dir / "video.mp4",
        qa_answer="QA says: worker at height without harness",
        video_report_gen_fn=fake_generate_video_report,
    )

    markdown = await reused_tool(video_path=str(runner_dir / "video.mp4"), query="make report")

    assert markdown.startswith("# Report")
    assert "QA says: worker at height without harness" in markdown


@pytest.mark.asyncio
async def test_live_video_runner_qa_graph_uses_lightweight_report_placeholder(runner_dir, monkeypatch):
    from langchain_core.messages import ToolMessage

    from vsa_agent.live_video_acceptance import _run_graph_video_acceptance
    from vsa_agent.registry import ToolRegistry

    observed_report_results = []

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            if config["configurable"]["thread_id"].endswith("-qa"):
                report_tool = ToolRegistry.get("report_agent")
                result = await report_tool(video_path=str(runner_dir / "video.mp4"), query="make report")
                observed_report_results.append(result)
                return AgentState(
                    current_message=state.current_message,
                    agent_scratchpad=[ToolMessage(content=result, tool_call_id="call-report")],
                    final_answer="QA answer from video_understanding result",
                )
            return AgentState(
                current_message=state.current_message,
                final_answer="# Report\n\nreport from reused QA",
            )

    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    async def fake_build_graph():
        return FakeGraph()

    monkeypatch.setattr("vsa_agent.live_video_acceptance.build_graph", fake_build_graph)

    await _run_graph_video_acceptance(
        run_id="unit-run",
        video_path=video_path,
        qa_query="what happened",
        qa_output_path=runner_dir / "qa-final.txt",
        report_output_path=runner_dir / "report-final.txt",
    )

    assert observed_report_results == [
        "Report generation is deferred until after QA. Use the existing video_understanding result to answer the user."
    ]


@pytest.mark.asyncio
async def test_live_video_runner_writes_manifest_and_final_outputs(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance

    analyze_calls = []
    direct_report_calls = []
    injected_report_understanding_calls = []

    async def fake_analyze_video(**kwargs):
        analyze_calls.append(kwargs)
        return UnderstandingResult(
            query=kwargs["query"],
            source_type="video_file",
            summary_text="shared qa answer from analyze_video",
            chunks=[],
            events=[],
        )

    async def fake_execute_report_agent(report_input, video_understanding_fn=None):
        direct_report_calls.append(report_input)
        assert video_understanding_fn is not None
        injected_report_understanding_calls.append(await video_understanding_fn())
        return AgentOutput(
            status="success",
            side_effects={"markdown_content": "# Report\n\nreport answer"},
        )

    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.analyze_video",
        fake_analyze_video,
    )
    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.execute_report_agent",
        fake_execute_report_agent,
    )
    monkeypatch.setenv("LIVE_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LIVE_API_MODEL", "qwen-plus")
    monkeypatch.setenv("DASHSCOPE_VLM_MODEL", "qwen-vl-plus")
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(
        str(video_path),
        qa_query="what happened",
        output_root=runner_dir / "runs",
    )

    assert exit_code == 0
    run_dirs = list((runner_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "qa-final.txt").read_text(encoding="utf-8") == "shared qa answer from analyze_video"
    assert (run_dir / "report-final.txt").read_text(encoding="utf-8").startswith("# Report")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["qa"]["status"] == "success"
    assert manifest["report"]["status"] == "success"
    assert manifest["report"]["markdown_path"] == str(run_dir / "report.md")
    assert manifest["video_path"] == str(video_path)
    assert manifest["metrics"]["total_elapsed_sec"] >= 0
    assert manifest["metrics"]["video_understanding_elapsed_sec"] >= 0
    assert manifest["metrics"]["qa_elapsed_sec"] >= 0
    assert manifest["metrics"]["report_elapsed_sec"] >= 0
    assert manifest["metrics"]["estimated_model_call_count"] == 1
    assert analyze_calls == [{"video_path": str(video_path), "query": "what happened"}]
    assert len(direct_report_calls) == 1
    assert direct_report_calls[0].video_path == str(video_path)
    assert len(injected_report_understanding_calls) == 1
    assert injected_report_understanding_calls[0].summary_text == "shared qa answer from analyze_video"
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "live_video_acceptance.video_understanding.shared" in trace_text
    assert "live_video_acceptance.qa.from_shared_understanding" in trace_text
    assert "live_video_acceptance.report.direct_report_agent" in trace_text


@pytest.mark.asyncio
async def test_live_video_runner_records_failed_flow_and_returns_nonzero(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance

    async def fake_analyze_video(**kwargs):
        raise RuntimeError("boom")

    async def fake_execute_report_agent(report_input):
        return AgentOutput(
            status="success",
            side_effects={"markdown_content": "# Report\n\nreport answer"},
        )

    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.analyze_video",
        fake_analyze_video,
    )
    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.execute_report_agent",
        fake_execute_report_agent,
    )
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(str(video_path), output_root=runner_dir / "runs")

    assert exit_code == 1
    run_dir = next((runner_dir / "runs").iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["qa"]["status"] == "failed"
    assert "boom" in manifest["qa"]["error"]["message"]
    assert manifest["report"]["status"] == "failed"
    assert "Shared understanding result" in manifest["report"]["error"]["message"]


@pytest.mark.asyncio
async def test_live_video_runner_prints_failure_summary_to_stderr(runner_dir, monkeypatch, capsys):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance

    async def fake_analyze_video(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type="video_file",
            summary_text="shared qa answer",
            chunks=[],
            events=[],
        )

    async def fake_execute_report_agent(report_input, video_understanding_fn=None):
        raise RuntimeError("report boom")

    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.analyze_video",
        fake_analyze_video,
    )
    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.execute_report_agent",
        fake_execute_report_agent,
    )
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(str(video_path), output_root=runner_dir / "runs")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Live video acceptance failed" in captured.err
    assert "report: RuntimeError: report boom" in captured.err
    assert "manifest:" in captured.err


@pytest.mark.asyncio
async def test_live_video_runner_rejects_non_markdown_report_answer(runner_dir, monkeypatch):
    from vsa_agent.live_video_acceptance import run_live_top_agent_video_acceptance

    async def fake_analyze_video(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type="video_file",
            summary_text="direct qa answer",
            chunks=[],
            events=[],
        )

    async def fake_execute_report_agent(report_input, video_understanding_fn=None):
        return AgentOutput(
            status="success",
            side_effects={"markdown_content": "Now that I have the understanding, I'll generate a Markdown report."},
        )

    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.analyze_video",
        fake_analyze_video,
    )
    monkeypatch.setattr(
        "vsa_agent.live_video_acceptance.execute_report_agent",
        fake_execute_report_agent,
    )
    video_path = runner_dir / "video.mp4"
    video_path.write_bytes(b"fake")

    exit_code = await run_live_top_agent_video_acceptance(str(video_path), output_root=runner_dir / "runs")

    assert exit_code == 1
    run_dir = next((runner_dir / "runs").iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["report"]["status"] == "failed"
    assert "Markdown report" in manifest["report"]["error"]["message"]
