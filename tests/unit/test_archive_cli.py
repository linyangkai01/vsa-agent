import json
from pathlib import Path

from vsa_agent.__main__ import main


def _write_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-cli",
                "video_path": "/data/video/warehouse.mp4",
                "started_at": "2026-07-01T10:00:00",
                "ended_at": "2026-07-01T10:01:00",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text("worker near forklift", encoding="utf-8")


def test_archive_ingest_cli_writes_summary(tmp_path: Path, capsys):
    run_dir = tmp_path / "run-cli"
    index_path = tmp_path / "index.jsonl"
    _write_run(run_dir)

    exit_code = main(["archive", "ingest", str(run_dir), "--index", str(index_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["records_written"] == 1
    assert output["record_id"] == "run-cli"
    assert output["index_path"] == str(index_path)


def test_archive_search_cli_prints_search_output(tmp_path: Path, capsys):
    run_dir = tmp_path / "run-cli"
    index_path = tmp_path / "index.jsonl"
    _write_run(run_dir)
    assert main(["archive", "ingest", str(run_dir), "--index", str(index_path)]) == 0
    capsys.readouterr()

    exit_code = main(["archive", "search", "forklift", "--index", str(index_path), "--top-k", "3"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["data"][0]["video_name"] == "warehouse.mp4"


def test_archive_ingest_cli_returns_clear_error_for_missing_manifest(tmp_path: Path, capsys):
    run_dir = tmp_path / "missing-manifest"
    run_dir.mkdir()

    exit_code = main(["archive", "ingest", str(run_dir), "--index", str(tmp_path / "index.jsonl")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR:" in captured.err
    assert "manifest.json" in captured.err
