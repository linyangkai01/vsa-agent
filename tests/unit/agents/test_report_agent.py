"""Tests for agents/report_agent.py."""

import pytest

from vsa_agent.agents.data_models import AgentOutput

VALIDATION_FEEDBACK = "[non_empty_response_validator] FAILED: Response is empty"


class TestReportAgentInput:
    def test_defaults(self):
        from vsa_agent.agents.report_agent import ReportAgentInput

        report_input = ReportAgentInput()
        assert report_input.video_path is None
        assert report_input.sensor_id is None
        assert report_input.query == "生成详细报告"


@pytest.mark.anyio
async def test_execute_report_agent_for_uploaded_video_path():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent

    understanding_calls = []
    report_calls = []

    async def fake_video_understanding(**kwargs):
        understanding_calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        }

    async def fake_video_report_gen(**kwargs):
        report_calls.append(kwargs)
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "person walking near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
    )

    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert result.messages == ["person walking near forklift"]
    assert result.side_effects["markdown_content"].startswith("# 单视频分析报告")
    assert result.side_effects["downloads"]["markdown"]["filename"] == "report.md"
    assert result.metadata["report_type"] == "single_video"
    assert result.metadata["validation_passed"] is True
    assert result.metadata["validation_feedback"] == []
    assert understanding_calls[0]["video_path"] == "video.mp4"
    assert understanding_calls[0]["source_type"] == "video_file"
    assert report_calls[0]["sensor_id"] == "uploaded-video"


@pytest.mark.anyio
async def test_execute_report_agent_for_sensor_path_uses_rtsp_source_type():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent

    understanding_calls = []
    report_calls = []

    async def fake_video_understanding(**kwargs):
        understanding_calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "forklift stops near doorway",
            "chunks": [],
            "events": [],
        }

    async def fake_video_report_gen(**kwargs):
        report_calls.append(kwargs)
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nforklift stops near doorway",
            "downloads": {"markdown": {"filename": "camera-1-report.md"}},
            "summary": "forklift stops near doorway",
        }

    result = await execute_report_agent(
        ReportAgentInput(sensor_id="camera-1", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
    )

    assert result.status == "success"
    assert understanding_calls[0]["source_type"] == "rtsp"
    assert understanding_calls[0]["sensor_id"] == "camera-1"
    assert report_calls[0]["sensor_id"] == "camera-1"


@pytest.mark.anyio
async def test_execute_report_agent_requires_video_path_or_sensor_id():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent

    async def fake_video_understanding(**kwargs):
        return kwargs

    async def fake_video_report_gen(**kwargs):
        return kwargs

    with pytest.raises(ValueError, match="video_path"):
        await execute_report_agent(
            ReportAgentInput(),
            video_understanding_fn=fake_video_understanding,
            video_report_gen_fn=fake_video_report_gen,
        )


@pytest.mark.anyio
async def test_default_report_agent_path_uses_unified_analyze_video(monkeypatch):
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.data_models.understanding import UnderstandingResult

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="long video summary",
            chunks=[],
            events=[],
        )

    async def fake_video_report_gen(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nlong video summary",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "long video summary",
        }

    monkeypatch.setattr("vsa_agent.agents.report_agent.analyze_video", fake_analyze_video)

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_report_gen_fn=fake_video_report_gen,
    )

    assert result.status == "success"
    assert captured["video_path"] == "video.mp4"


@pytest.mark.anyio
async def test_execute_report_agent_builds_structured_report_before_rendering():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.data_models.report import StructuredReport

    captured = {}

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        }

    async def fake_video_report_gen(**kwargs):
        captured.update(kwargs)
        assert isinstance(kwargs["structured_report"], StructuredReport)
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "person walking near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
    )

    assert result.status == "success"
    assert "structured_report" in captured


@pytest.mark.anyio
async def test_execute_report_agent_accepts_lax_event_dicts():
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift",
                }
            ],
        }

    async def fake_video_report_gen(**kwargs):
        assert kwargs["structured_report"].sections[0].summary_text == "person walking near forklift"
        return {
            "markdown_content": "# report",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "person walking near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
    )

    assert result.status == "success"


@pytest.mark.anyio
async def test_execute_report_agent_keeps_success_status_and_exposes_validation_feedback():
    from vsa_agent.agents.postprocessing.pipeline import PostprocessingResult, ValidationPipeline
    from vsa_agent.agents.report_agent import ReportAgentInput, execute_report_agent
    from vsa_agent.data_models.report import StructuredReport

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "",
            "chunks": [],
            "events": [],
        }

    class FailingValidationPipeline(ValidationPipeline):
        async def process(self, output: str) -> PostprocessingResult:
            return PostprocessingResult(passed=False, feedback=VALIDATION_FEEDBACK)

    async def fake_video_report_gen(**kwargs):
        assert isinstance(kwargs["structured_report"], StructuredReport)
        assert kwargs["structured_report"].global_validation_feedback == [VALIDATION_FEEDBACK]
        return {
            "markdown_content": "# 单视频分析报告\n\n## 校验反馈\n- [non_empty_response_validator] FAILED: Response is empty",  # noqa: E501
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
        validation_pipeline=FailingValidationPipeline(),
    )

    assert result.status == "success"
    assert result.metadata["validation_passed"] is False
    assert result.metadata["validation_feedback"] == [VALIDATION_FEEDBACK]
