from pathlib import Path

from vsa_agent.archive.index import read_archive_index, upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord


def _record(record_id: str, description: str) -> ArchiveRecord:
    return ArchiveRecord(
        record_id=record_id,
        video_name=f"{record_id}.mp4",
        video_path=f"/data/{record_id}.mp4",
        description=description,
        search_text=description,
        start_time="",
        end_time="",
        sensor_id=record_id,
    )


def test_upsert_archive_records_replaces_duplicate_record_id(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"

    written = upsert_archive_records(index_path, [_record("run-1", "old forklift")])
    rewritten = upsert_archive_records(index_path, [_record("run-1", "new forklift")])
    records = read_archive_index(index_path)

    assert written == 1
    assert rewritten == 1
    assert len(records) == 1
    assert records[0].description == "new forklift"


def test_read_archive_index_skips_invalid_jsonl_lines(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        '{"record_id":"run-1","video_name":"a.mp4","description":"person","search_text":"person"}\nnot-json\n',
        encoding="utf-8",
    )

    records = read_archive_index(index_path)

    assert len(records) == 1
    assert records[0].record_id == "run-1"
