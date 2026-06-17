"""Tests for agents/multi_report_agent.py."""

import pytest

from vsa_agent.agents.data_models import AgentOutput


@pytest.mark.anyio
async def test_execute_multi_report_agent_for_multiple_sources():
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent

    understanding_calls = []
    report_calls = []

    async def fake_video_understanding(**kwargs):
        understanding_calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {kwargs.get('sensor_id') or kwargs.get('video_path')}",
            "chunks": [],
            "events": [],
        }

    async def fake_report_gen(**kwargs):
        report_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 报告摘要\n- 事件 1 - camera-1: summary for camera-1",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary for camera-1; summary for video-a.mp4",
            "section_count": 2,
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[
                MultiReportSourceItem(sensor_id="camera-1"),
                MultiReportSourceItem(video_path="video-a.mp4"),
            ],
        ),
        video_understanding_fn=fake_video_understanding,
        report_gen_fn=fake_report_gen,
    )

    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert result.metadata["report_type"] == "multi_video"
    assert result.side_effects["downloads"]["markdown"]["filename"] == "multi-report.md"
    assert len(understanding_calls) == 2
    assert report_calls[0]["report_title"] == "仓库巡检聚合报告"


@pytest.mark.anyio
async def test_default_multi_report_agent_path_uses_unified_analyze_video(monkeypatch):
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
    from vsa_agent.data_models.understanding import UnderstandingResult

    calls = []

    async def fake_analyze_video(**kwargs):
        calls.append(kwargs)
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="summary",
            chunks=[],
            events=[],
        )

    async def fake_report_gen(**kwargs):
        return {
            "markdown_content": "# 仓库巡检聚合报告",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary",
            "section_count": 1,
        }

    monkeypatch.setattr("vsa_agent.agents.multi_report_agent.analyze_video", fake_analyze_video)

    await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[MultiReportSourceItem(video_path="video-a.mp4")],
        ),
        report_gen_fn=fake_report_gen,
    )

    assert calls[0]["video_path"] == "video-a.mp4"


@pytest.mark.anyio
async def test_execute_multi_report_agent_builds_structured_sections_before_rendering():
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
    from vsa_agent.data_models.report import StructuredReport

    captured = {}

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {kwargs.get('sensor_id') or kwargs.get('video_path')}",
            "chunks": [],
            "events": [],
        }

    async def fake_report_gen(**kwargs):
        captured.update(kwargs)
        assert isinstance(kwargs["structured_report"], StructuredReport)
        return {
            "markdown_content": "# 仓库巡检聚合报告",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary",
            "section_count": 1,
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[MultiReportSourceItem(sensor_id="camera-1")],
        ),
        video_understanding_fn=fake_video_understanding,
        report_gen_fn=fake_report_gen,
    )

    assert result.status == "success"
    assert "structured_report" in captured


@pytest.mark.anyio
async def test_execute_multi_report_agent_keeps_external_section_title():
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "summary for camera-1",
            "chunks": [],
            "events": [{"label": "walking", "description": "person walking"}],
        }

    async def fake_report_gen(**kwargs):
        assert kwargs["report_sections"][0].section_title == "事件 1 - camera-1"
        return {
            "markdown_content": "# 浠撳簱宸℃鑱氬悎鎶ュ憡",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary for camera-1",
            "section_count": 1,
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="浠撳簱宸℃鑱氬悎鎶ュ憡",
            query="鐢熸垚鑱氬悎鎶ュ憡",
            sources=[MultiReportSourceItem(sensor_id="camera-1")],
        ),
        video_understanding_fn=fake_video_understanding,
        report_gen_fn=fake_report_gen,
    )

    assert result.status == "success"
