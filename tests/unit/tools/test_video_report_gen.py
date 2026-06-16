import pytest

from vsa_agent.tools.video_report_gen import VideoReportGenOutput
from vsa_agent.tools.video_report_gen import generate_video_report


@pytest.mark.anyio
async def test_generate_video_report_returns_markdown_and_download_metadata():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "query": "生成详细报告",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )

    assert isinstance(result, VideoReportGenOutput)
    assert result.markdown_content.startswith("# ")
    assert result.downloads["markdown"]["filename"].endswith(".md")


@pytest.mark.anyio
async def test_generate_video_report_uses_fixed_sections():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "query": "生成详细报告",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )

    assert result.markdown_content.startswith("# 单视频分析报告")
    assert "## 视频源" in result.markdown_content
    assert "## 用户问题" in result.markdown_content
    assert "## 摘要" in result.markdown_content
    assert "## 事件时间线" in result.markdown_content
    assert "- 无结构化事件" in result.markdown_content


@pytest.mark.anyio
async def test_generate_video_report_formats_event_timeline():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "query": "生成详细报告",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift",
                }
            ],
        },
    )

    assert "- [00:00:05 - 00:00:09] person walking near forklift" in result.markdown_content


def test_generate_video_report_is_registered_as_tool():
    assert getattr(generate_video_report, "_tool_name", "") == "video_report_gen"
