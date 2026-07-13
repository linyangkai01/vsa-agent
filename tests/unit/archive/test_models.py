from vsa_agent.archive.models import ArchiveRecord, build_record_id
from vsa_agent.tools.search import SearchResult


def test_archive_record_converts_to_search_result():
    record = ArchiveRecord(
        record_id="run-123",
        video_name="warehouse.mp4",
        video_path="/data/video/warehouse.mp4",
        description="worker walking near forklift",
        search_text="worker walking near forklift loading dock",
        start_time="2026-07-01T10:00:00",
        end_time="2026-07-01T10:01:00",
        sensor_id="warehouse",
        screenshot_url="",
        object_ids=["worker", "forklift"],
        metadata={"mode": "graph"},
    )

    result = record.to_search_result(similarity=0.87)

    assert isinstance(result, SearchResult)
    assert result.video_name == "warehouse.mp4"
    assert result.description == "worker walking near forklift"
    assert result.start_time == "2026-07-01T10:00:00"
    assert result.end_time == "2026-07-01T10:01:00"
    assert result.sensor_id == "warehouse"
    assert result.similarity == 0.87
    assert result.object_ids == ["worker", "forklift"]


def test_build_record_id_prefers_run_id_and_is_stable():
    assert build_record_id("20260701-102652", "/data/video/a.mp4") == "20260701-102652"
    assert build_record_id("", "/data/video/a.mp4") == "a.mp4"
