from pathlib import Path

import pytest

from vsa_agent.archive.index import upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.search import LocalArchiveSearchStore


def _record(record_id: str, description: str, search_text: str) -> ArchiveRecord:
    return ArchiveRecord(
        record_id=record_id,
        video_name=f"{record_id}.mp4",
        video_path=f"/data/{record_id}.mp4",
        description=description,
        search_text=search_text,
        start_time="",
        end_time="",
        sensor_id=record_id,
    )


@pytest.mark.asyncio
async def test_local_archive_search_returns_ranked_matches(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(
        index_path,
        [
            _record("run-1", "worker near forklift", "worker near forklift loading dock safety risk"),
            _record("run-2", "empty hallway", "empty hallway no activity"),
        ],
    )
    store = LocalArchiveSearchStore(index_path)

    output = await store.search("forklift safety", top_k=5)

    assert len(output.data) == 1
    assert output.data[0].video_name == "run-1.mp4"
    assert output.data[0].similarity > 0


@pytest.mark.asyncio
async def test_local_archive_search_returns_empty_for_no_match(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(index_path, [_record("run-1", "worker near forklift", "worker near forklift")])
    store = LocalArchiveSearchStore(index_path)

    output = await store.search("ocean beach", top_k=5)

    assert output.data == []


@pytest.mark.asyncio
async def test_as_embed_search_returns_zero_arg_callable(tmp_path: Path):
    index_path = tmp_path / "index.jsonl"
    upsert_archive_records(index_path, [_record("run-1", "worker near forklift", "worker near forklift")])
    store = LocalArchiveSearchStore(index_path)

    callable_search = store.as_embed_search("forklift", top_k=1)
    output = await callable_search()

    assert output.data[0].video_name == "run-1.mp4"
