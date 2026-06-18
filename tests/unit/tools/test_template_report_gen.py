"""Tests for tools/template_report_gen.py."""

import pytest

from vsa_agent.utils.markdown_parser import split_sections


@pytest.mark.anyio
async def test_generate_template_report_returns_markdown_with_summary_sections():
    from vsa_agent.tools.template_report_gen import TemplateReportGenOutput
    from vsa_agent.tools.template_report_gen import generate_template_report

    result = await generate_template_report(
        report_title="聚合报告",
        report_sections=[
            {
                "section_title": "事件 1 - camera-1",
                "summary": "person walking near forklift",
                "markdown_content": "## 摘要\nperson walking near forklift",
            },
            {
                "section_title": "事件 2 - camera-2",
                "summary": "forklift stops near doorway",
                "markdown_content": "## 摘要\nforklift stops near doorway",
            },
        ],
    )

    assert isinstance(result, TemplateReportGenOutput)
    assert result.markdown_content.startswith("# 聚合报告")
    assert "## 报告摘要" in result.markdown_content
    assert "## 分事件报告" in result.markdown_content
    assert result.section_count == 2


@pytest.mark.anyio
async def test_generate_template_report_includes_counts_and_chart_sections():
    from vsa_agent.tools.template_report_gen import generate_template_report

    result = await generate_template_report(
        report_title="聚合报告",
        report_sections=[
            {
                "section_title": "事件 1 - camera-1",
                "summary": "person walking near forklift",
                "markdown_content": "## 摘要\nperson walking near forklift",
            }
        ],
        counts={"walking": 2},
        chart={
            "markdown_table": "| 事件类型 | 次数 |\n| --- | --- |\n| walking | 2 |",
        },
    )

    assert "## 统计概览" in result.markdown_content
    assert "- walking: 2" in result.markdown_content
    assert "## 图表" in result.markdown_content
    assert "| 事件类型 | 次数 |" in result.markdown_content


@pytest.mark.anyio
async def test_generate_template_report_uses_correct_empty_states():
    from vsa_agent.tools.template_report_gen import generate_template_report

    result = await generate_template_report(
        report_title="聚合报告",
        report_sections=[],
        counts={},
        chart={},
    )

    assert "- 无分事件内容" in result.markdown_content
    assert "- 无统计数据" in result.markdown_content
    assert "- 无图表数据" in result.markdown_content


@pytest.mark.anyio
async def test_generate_template_report_output_is_splitable_by_h2_sections():
    from vsa_agent.tools.template_report_gen import generate_template_report

    result = await generate_template_report(
        report_title="demo-report",
        report_sections=[
            {
                "section_title": "event-1",
                "summary": "person walking near forklift",
                "markdown_content": "## summary\nperson walking near forklift",
            }
        ],
        counts={"walking": 2},
        chart={"markdown_table": "| type | count |\n| --- | --- |\n| walking | 2 |"},
    )

    sections = split_sections(result.markdown_content, heading_level=2)
    titles = [section.title for section in sections]
    assert titles[:4] == ["报告摘要", "统计概览", "图表", "分事件报告"]
    assert sections[0].content.startswith("- ")
    assert "| type | count |" in sections[2].content
