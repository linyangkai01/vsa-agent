from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from vsa_agent.archive.models import ArchiveRecord

logger = logging.getLogger(__name__)


def read_archive_index(index_path: str | Path) -> list[ArchiveRecord]:
    path = Path(index_path)
    if not path.exists():
        return []

    records: list[ArchiveRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ArchiveRecord.model_validate(json.loads(line)))
        except Exception as exc:
            logger.warning("Skipping invalid archive index line %s in %s: %s", line_number, path, exc)
    return records


def upsert_archive_records(index_path: str | Path, records: Iterable[ArchiveRecord]) -> int:
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = {record.record_id: record for record in read_archive_index(path)}
    incoming = list(records)
    for record in incoming:
        merged[record.record_id] = record

    ordered = sorted(merged.values(), key=lambda item: item.record_id)
    payload = "\n".join(record.model_dump_json() for record in ordered)
    path.write_text(f"{payload}\n" if payload else "", encoding="utf-8")
    return len(incoming)
