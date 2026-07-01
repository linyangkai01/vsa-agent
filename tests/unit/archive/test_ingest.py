import json
from pathlib import Path

import pytest

from vsa_agent.archive.index import read_archive_index
from vsa_agent.archive.ingest import build_record_from_live_run
from vsa_agent.archive.ingest import ingest_live_run


def _write_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260701-102652",
                "video_path": "/data/project/lyk/video/1597042367-1-192.mp4",
                "mode": "graph",
                "llm_model": "qwen3.7-plus",
                "vlm_model": "qwen3-vl-flash-2025-10-15",
                "started_at": "2026-07-01T10:26:52",
                "ended_at": "2026-07-01T10:28:51",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text(
        "A worker walks near a forklift in a warehouse loading area. Safety risk: pedestrian and vehicle proximity.",
        encoding="utf-8",
    )
    (run_dir / "report-final.txt").write_text(
        "# Inspection Report\n\nForklift traffic and pedestrian movement overlap near the loading dock.",
        encoding="utf-8",
    )


def test_build_record_from_live_run_extracts_searchable_fields(tmp_path: Path):
    run_dir = tmp_path / "20260701-102652"
    _write_run(run_dir)

    record = build_record_from_live_run(run_dir)

    assert record.record_id == "20260701-102652"
    assert record.video_name == "1597042367-1-192.mp4"
    assert record.sensor_id == "1597042367-1-192"
    assert "worker walks near a forklift" in record.description
    assert "Inspection Report" in record.search_text
    assert "forklift" in record.object_ids
    assert record.metadata["mode"] == "graph"
    assert record.metadata["qa_status"] == "success"
    assert record.metadata["report_status"] == "success"


def test_ingest_live_run_writes_archive_index(tmp_path: Path):
    run_dir = tmp_path / "20260701-102652"
    index_path = tmp_path / "archive" / "index.jsonl"
    _write_run(run_dir)

    record = ingest_live_run(run_dir, index_path)
    records = read_archive_index(index_path)

    assert record.record_id == "20260701-102652"
    assert [item.record_id for item in records] == ["20260701-102652"]


def test_build_record_from_live_run_requires_manifest(tmp_path: Path):
    run_dir = tmp_path / "missing-manifest"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="manifest.json"):
        build_record_from_live_run(run_dir)
