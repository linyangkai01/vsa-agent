from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md"
REPORT_FIELDS = ("runtime", "job_stages", "provider", "es", "search", "media", "delete")
INCOMPLETE_MARKERS = (
    "待采集",
    "等待 Task 24",
    "不声明服务器链路通过",
    "尚未验收",
    "未执行",
    "占位",
    "伪造",
    "TODO",
    "TBD",
    "SKIP",
)


def _section(report: str, name: str) -> str:
    heading = f"## {name}\n"
    assert heading in report, f"validation report is missing the {name!r} section"
    content = report.split(heading, maxsplit=1)[1]
    return content.split("\n## ", maxsplit=1)[0].strip()


def _assert_complete_server_evidence(report: str) -> None:
    report = report.replace("\r\n", "\n")
    assert "- 总体结果：PASS" in report
    assert not any(marker in report for marker in INCOMPLETE_MARKERS)

    sections = {name: _section(report, name) for name in REPORT_FIELDS}
    assert all(section.startswith("PASS\n") for section in sections.values())
    assert "无密钥" in sections["runtime"]
    assert "三并发" in sections["job_stages"]
    assert "Worker 重启" in sections["job_stages"]
    assert "真实 provider" in sections["provider"]
    assert "HTTP 206" in sections["media"]
    assert "删除清理" in sections["delete"]


def _complete_contract_report() -> str:
    return """# 录播视频生产运行验证报告

- 总体结果：PASS

## runtime

PASS
无密钥配置摘要与运行日志路径已记录。

## job_stages

PASS
三并发任务已完成，Worker 重启恢复轨迹已记录。

## provider

PASS
真实 provider 模型身份与调用结果已记录。

## es

PASS
Elasticsearch identity 与索引结果已记录。

## search

PASS
搜索 asset/segment identity 与 similarity 已记录。

## media

PASS
缩略图与 HTTP 206 Range 结果已记录。

## delete

PASS
删除清理结果已记录。
"""


def test_validation_report_records_all_required_server_evidence() -> None:
    _assert_complete_server_evidence(REPORT_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label", ("三并发", "Worker 重启", "HTTP 206", "删除清理", "无密钥"))
def test_validation_report_rejects_missing_required_server_evidence(label: str) -> None:
    report = _complete_contract_report().replace(label, "证据缺失", 1)

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(report)


@pytest.mark.parametrize("marker", ("占位", "伪造"))
def test_validation_report_rejects_explicitly_untrusted_evidence(marker: str) -> None:
    report = _complete_contract_report().replace("运行日志路径已记录", f"{marker}运行日志路径", 1)

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(report)


def test_validation_report_rejects_placeholder_keyword_stuffing() -> None:
    pending_report = REPORT_PATH.read_text(encoding="utf-8")
    forged_report = f"{pending_report}\n三并发 Worker 重启 HTTP 206 删除清理 无密钥\n"

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(forged_report)
