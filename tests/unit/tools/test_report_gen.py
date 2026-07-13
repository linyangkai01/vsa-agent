"""Tests for tools/report_gen.py."""

import pytest


@pytest.mark.anyio
async def test_generate_multi_report_calls_single_report_gen_and_template_gen():
    from vsa_agent.tools.report_gen import MultiReportGenOutput, ReportSectionInput, generate_multi_report

    single_calls = []
    template_calls = []

    async def fake_single_report_gen(**kwargs):
        single_calls.append(kwargs)
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "camera-1-report.md"}},
            "summary": "person walking near forklift",
        }

    async def fake_template_report_gen(**kwargs):
        template_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 报告摘要\n- 事件 1 - camera-1: person walking near forklift",
            "section_count": 1,
        }

    result = await generate_multi_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            ReportSectionInput(
                section_title="事件 1 - camera-1",
                sensor_id="camera-1",
                user_query="生成聚合报告",
                understanding_result={
                    "query": "生成聚合报告",
                    "source_type": "rtsp",
                    "summary_text": "person walking near forklift",
                    "chunks": [],
                    "events": [],
                },
            )
        ],
        single_report_gen_fn=fake_single_report_gen,
        template_report_gen_fn=fake_template_report_gen,
    )

    assert isinstance(result, MultiReportGenOutput)
    assert result.section_count == 1
    assert result.downloads["markdown"]["filename"] == "multi-report.md"
    assert single_calls[0]["sensor_id"] == "camera-1"
    assert template_calls[0]["report_title"] == "仓库巡检聚合报告"


@pytest.mark.anyio
async def test_generate_multi_report_includes_chart_payload_for_template():
    from vsa_agent.tools.report_gen import ReportSectionInput, generate_multi_report

    template_calls = []

    async def fake_single_report_gen(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "camera-1-report.md"}},
            "summary": "person walking near forklift",
        }

    async def fake_count_chart_builder(**kwargs):
        return {
            "counts": {"walking": 2},
            "chart": {
                "chart_type": "bar",
                "title": "事件计数统计",
                "spec": {"labels": ["walking"], "values": [2]},
                "markdown_table": "| 事件类型 | 次数 |\n| --- | --- |\n| walking | 2 |",
            },
        }

    async def fake_template_report_gen(**kwargs):
        template_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 统计概览\n- walking: 2",
            "section_count": 1,
        }

    await generate_multi_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            ReportSectionInput(
                section_title="事件 1 - camera-1",
                sensor_id="camera-1",
                user_query="生成聚合报告",
                understanding_result={
                    "query": "生成聚合报告",
                    "source_type": "rtsp",
                    "summary_text": "person walking near forklift",
                    "chunks": [],
                    "events": [{"label": "walking", "description": "person walking"}],
                },
            )
        ],
        single_report_gen_fn=fake_single_report_gen,
        template_report_gen_fn=fake_template_report_gen,
        count_chart_builder_fn=fake_count_chart_builder,
    )

    assert template_calls[0]["counts"] == {"walking": 2}
    assert template_calls[0]["chart"]["title"] == "事件计数统计"
