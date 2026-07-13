import json
from pathlib import Path

import pytest

from vsa_agent.agents.search_agent import SearchAgentInput, execute_search_agent_flow
from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.search import LocalArchiveSearchStore


def _write_live_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "warehouse-safety-demo",
                "video_path": "/data/project/lyk/video/warehouse-safety-demo.mp4",
                "mode": "graph",
                "llm_model": "qwen3.7-plus",
                "vlm_model": "qwen3-vl-flash-2025-10-15",
                "started_at": "2026-06-23T10:00:00",
                "ended_at": "2026-06-23T10:00:08",
                "qa": {"status": "success"},
                "report": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qa-final.txt").write_text(
        "A worker is walking near a forklift in the warehouse loading area.",
        encoding="utf-8",
    )
    (run_dir / "report-final.txt").write_text(
        "Safety risk: pedestrian movement overlaps with forklift traffic near the dock.",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_local_archive_search_returns_matching_video_result(tmp_path: Path):
    run_dir = tmp_path / "warehouse-safety-demo"
    index_path = tmp_path / "archive" / "index.jsonl"
    _write_live_run(run_dir)
    ingest_live_run(run_dir, index_path)

    store = LocalArchiveSearchStore(index_path)
    query = "find a worker walking near a forklift"
    result = await execute_search_agent_flow(
        SearchAgentInput(
            query=query,
            agent_mode=False,
            use_critic=False,
            use_attribute_search=False,
        ),
        embed_search=store.as_embed_search(query, top_k=5),
    )

    assert result.search_output.data
    first = result.search_output.data[0]
    assert first.video_name == "warehouse-safety-demo.mp4"
    assert "forklift" in first.description.lower()
    assert first.start_time == "2026-06-23T10:00:00"
    assert first.end_time == "2026-06-23T10:00:08"
    assert first.sensor_id == "warehouse-safety-demo"
    assert first.similarity > 0
    assert "forklift" in first.object_ids
    assert result.incidents
    assert "forklift" in result.text_answer.lower()
