import json
import shutil
from pathlib import Path

import pytest

TEST_TRACE_DIR = Path("artifacts/test-report-agent-live-trace")


@pytest.fixture
def trace_dir():
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)
    TEST_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_TRACE_DIR
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)


@pytest.mark.asyncio
async def test_report_agent_logs_understanding_and_report_artifacts(trace_dir, monkeypatch):
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.data_models.understanding import UnderstandingResult

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))

    async def fake_video_understanding_fn(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type="video_file",
            summary_text="person walks near forklift",
            chunks=[],
            events=[],
        )

    async def fake_report_gen_fn(**kwargs):
        return {
            "markdown_content": "# Report\n\nperson walks near forklift",
            "downloads": {},
            "summary": "person walks near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="generate report"),
        video_understanding_fn=fake_video_understanding_fn,
        video_report_gen_fn=fake_report_gen_fn,
    )

    assert result.status == "success"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "report_agent.understanding_result" in event_types
    assert "report_agent.result" in event_types
    assert (trace_dir / "tool-results" / "report-agent-understanding.json").exists()
    assert (trace_dir / "report.md").exists()
