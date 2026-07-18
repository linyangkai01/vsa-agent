import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md"
REPORT_FIELDS = ("runtime", "job_stages", "provider", "es", "search", "media", "delete")
COMMON_EVIDENCE_FIELDS = ("run_id", "timestamp_utc", "asset_id", "job_id", "segment_id", "provider", "model")
PRODUCTION_PROVIDERS = {"openai_compatible", "vllm"}
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


def _field(section: str, name: str) -> str:
    pattern = rf"(?m)^-\s*{re.escape(name)}:\s*(\S(?:.*\S)?)\s*$"
    matches = re.findall(pattern, section)
    assert len(matches) == 1, f"section is missing exactly one {name!r} field"
    value = matches[0]
    assert value.casefold() not in {"unknown", "none", "n/a", "na", "provider", "model"}
    return value


def _assert_common_evidence_fields(sections: dict[str, str]) -> dict[str, str]:
    stable_values: dict[str, str] = {}
    for section_name, section in sections.items():
        fields = {field_name: _field(section, field_name) for field_name in COMMON_EVIDENCE_FIELDS}
        run_id = fields["run_id"]
        try:
            assert str(UUID(run_id)) == run_id.lower()
        except (AssertionError, ValueError):
            raise AssertionError(f"{section_name} run_id is not a canonical UUID") from None

        timestamp = fields["timestamp_utc"]
        assert timestamp.endswith("Z")
        try:
            parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
        except ValueError:
            raise AssertionError(f"{section_name} timestamp_utc is not ISO-8601") from None
        assert parsed.utcoffset() == timedelta(0)

        for field_name in ("asset_id", "job_id", "segment_id"):
            value = fields[field_name]
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,}", value)
        provider = fields["provider"]
        assert provider in PRODUCTION_PROVIDERS
        model = fields["model"]
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{2,}", model)

        for field_name in ("run_id", "asset_id", "job_id", "segment_id"):
            value = fields[field_name]
            previous = stable_values.setdefault(field_name, value)
            assert value == previous, f"{field_name} differs between evidence sections"
    return stable_values


def _assert_complete_server_evidence(report: str) -> None:
    report = report.replace("\r\n", "\n")
    assert "- 总体结果：PASS" in report
    assert not any(marker in report for marker in INCOMPLETE_MARKERS)

    sections = {name: _section(report, name) for name in REPORT_FIELDS}
    assert all(section.startswith("PASS\n") for section in sections.values())
    common = _assert_common_evidence_fields(sections)
    assert "无密钥" in sections["runtime"]
    log_ref = _field(sections["runtime"], "log_ref")
    log_path = Path(log_ref)
    assert log_ref.endswith(".log") and _field(sections["runtime"], "run_id") in log_ref
    assert log_path.is_file()
    log_contents = log_path.read_text(encoding="utf-8")
    assert common["run_id"] in log_contents
    manifest = json.loads((log_path.parent / "processes.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == common["run_id"]
    assert not re.search(r"(?i)(authorization\s*:\s*bearer|api[_ -]?key\s*[:=]\s*\S+)", log_contents)
    assert _field(sections["runtime"], "secret_scan") == "PASS (无密钥)"
    assert "三并发" in sections["job_stages"]
    assert "Worker 重启" in sections["job_stages"]
    assert "真实 provider" in sections["provider"]
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,}", _field(sections["es"], "index"))
    segment_ids = _field(sections["es"], "segment_ids").split(",")
    assert len(segment_ids) == len(set(segment_ids)) > 0
    expected_count = int(_field(sections["es"], "expected_segment_count"))
    document_count = int(_field(sections["es"], "document_count"))
    dedup_count = int(_field(sections["es"], "dedup_count"))
    assert document_count == expected_count == dedup_count == len(segment_ids)
    assert _field(sections["search"], "result_asset_id") == common["asset_id"]
    assert _field(sections["search"], "result_job_id") == common["job_id"]
    assert _field(sections["search"], "result_segment_id") in segment_ids
    similarity = float(_field(sections["search"], "similarity"))
    assert 0.0 <= similarity <= 1.0
    assert _field(sections["media"], "HTTP 206") == "PASS"
    assert _field(sections["media"], "Accept-Ranges").lower() == "bytes"
    assert re.fullmatch(r"bytes 0-0/[1-9][0-9]*", _field(sections["media"], "Content-Range"))
    cleanup_path = _field(sections["delete"], "cleanup_path")
    assert re.fullmatch(r"/[^\s]+", cleanup_path)
    assert not Path(cleanup_path).exists()
    assert _field(sections["delete"], "cleanup_status") == "PASS"
    assert "删除清理" in sections["delete"]


def _complete_contract_report(tmp_path: Path) -> str:
    run_id = "123e4567-e89b-12d3-a456-426614174000"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    log_path = run_dir / "stack.log"
    log_path.write_text(f"run_id={run_id}\nredaction=clean\n", encoding="utf-8")
    (run_dir / "processes.json").write_text(
        json.dumps({"run_id": run_id, "processes": []}),
        encoding="utf-8",
    )
    common = """- run_id: 123e4567-e89b-12d3-a456-426614174000
- timestamp_utc: 2026-07-18T12:34:56Z
- asset_id: asset-20260718-0001
- job_id: job-20260718-0001
- segment_id: segment-20260718-0001
- provider: openai_compatible
- model: qwen-vl-plus
"""
    return f"""# 录播视频生产运行验证报告

- 总体结果：PASS

## runtime

PASS
{common}- log_ref: {log_path}
- secret_scan: PASS (无密钥)
无密钥配置摘要与运行日志路径已记录。

## job_stages

PASS
{common}- stage_history: 三并发任务已完成，Worker 重启恢复轨迹已记录。

## provider

PASS
{common}
真实 provider 模型身份与调用结果已记录。

## es

PASS
{common}- index: vsa-video-embeddings
- document_count: 1
- expected_segment_count: 1
- dedup_count: 1
- segment_ids: segment-20260718-0001
Elasticsearch identity 与索引结果已记录。

## search

PASS
{common}
- similarity: 0.910
- result_asset_id: asset-20260718-0001
- result_job_id: job-20260718-0001
- result_segment_id: segment-20260718-0001
搜索 asset/segment identity 与 similarity 已记录。

## media

PASS
{common}- HTTP 206: PASS
- Accept-Ranges: bytes
- Content-Range: bytes 0-0/2048
缩略图与 HTTP 206 Range 结果已记录。

## delete

PASS
{common}- cleanup_path: /data/project/vsa-data/assets/asset-20260718-0001
- cleanup_status: PASS
删除清理结果已记录。
"""


def _keyword_only_report() -> str:
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


def test_validation_report_rejects_clean_keyword_only_report() -> None:
    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(_keyword_only_report())


def test_validation_report_accepts_explicit_evidence_fields(tmp_path: Path) -> None:
    _assert_complete_server_evidence(_complete_contract_report(tmp_path))


@pytest.mark.parametrize("label", ("三并发", "Worker 重启", "HTTP 206", "删除清理", "无密钥"))
def test_validation_report_rejects_missing_required_server_evidence(label: str, tmp_path: Path) -> None:
    report = _complete_contract_report(tmp_path).replace(label, "证据缺失", 1)

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(report)


@pytest.mark.parametrize("marker", ("占位", "伪造"))
def test_validation_report_rejects_explicitly_untrusted_evidence(marker: str, tmp_path: Path) -> None:
    report = _complete_contract_report(tmp_path).replace("运行日志路径已记录", f"{marker}运行日志路径", 1)

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(report)


def test_validation_report_rejects_placeholder_keyword_stuffing() -> None:
    pending_report = REPORT_PATH.read_text(encoding="utf-8")
    forged_report = f"{pending_report}\n三并发 Worker 重启 HTTP 206 删除清理 无密钥\n"

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(forged_report)
