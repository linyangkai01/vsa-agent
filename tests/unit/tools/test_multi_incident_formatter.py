"""Tests for tools/multi_incident_formatter.py."""

import asyncio

from vsa_agent.data_models.report import ReportIncident


def test_format_multi_incidents_renders_markdown_sections():
    from vsa_agent.tools.multi_incident_formatter import format_multi_incidents

    result = format_multi_incidents(
        [
            ReportIncident(
                incident_id="inc-1",
                category="intrusion",
                description="person enters restricted area",
                severity="high",
                confidence=0.91,
                start_timestamp="2026-06-23T10:00:00",
                end_timestamp="2026-06-23T10:00:08",
            )
        ]
    )

    assert "## 事件列表" in result
    assert "intrusion" in result
    assert "person enters restricted area" in result
    assert "2026-06-23T10:00:00" in result


def test_format_multi_incidents_accepts_plain_dict_payloads():
    from vsa_agent.tools.multi_incident_formatter import format_multi_incidents

    result = format_multi_incidents(
        [
            {
                "incident_id": "inc-2",
                "category": "vehicle",
                "description": "forklift crosses lane",
                "severity": "medium",
                "confidence": 0.8,
                "start_timestamp": "2026-06-23T11:00:00",
                "end_timestamp": "2026-06-23T11:00:05",
            }
        ],
        heading="多事件汇总",
    )

    assert "## 多事件汇总" in result
    assert "forklift crosses lane" in result


def test_format_multi_incidents_returns_fallback_for_empty_input():
    from vsa_agent.tools.multi_incident_formatter import format_multi_incidents

    assert format_multi_incidents([]) == "## 事件列表\n\n- 无事件"


def test_multi_incident_formatter_tool_returns_fallback_for_empty_input():
    from vsa_agent.tools.multi_incident_formatter import multi_incident_formatter_tool

    result = asyncio.run(multi_incident_formatter_tool())

    assert result == "## 事件列表\n\n- 无事件"
