from scripts.es_ingest_smoke import sample_payload
from scripts.es_ingest_smoke import validate_indexed_document
from scripts.es_ingest_smoke import validate_ingest_response


def test_sample_payload_contains_required_metadata():
    payload = sample_payload("runtime-video-1")

    assert payload["video_id"] == "runtime-video-1"
    metadata = payload["metadata"]
    assert metadata["video_name"] == "runtime-validation.mp4"
    assert metadata["description"] == "forklift passes near worker in loading zone"
    assert metadata["sensor_id"] == "camera-runtime-1"
    assert metadata["start_time"] == "2026-07-04T08:00:00Z"
    assert metadata["end_time"] == "2026-07-04T08:00:05Z"
    assert metadata["screenshot_url"] == "http://example.invalid/frames/runtime-validation.jpg"
    assert metadata["vector"] == [0.11, 0.22, 0.33]


def test_validate_ingest_response_returns_result_id():
    result_id = validate_ingest_response(
        {"status": "ingested", "video_id": "runtime-video-1", "indexed": True, "result_id": "abc123"},
        expected_video_id="runtime-video-1",
    )

    assert result_id == "abc123"


def test_validate_ingest_response_rejects_skipped_status():
    try:
        validate_ingest_response(
            {"status": "skipped", "video_id": "runtime-video-1", "indexed": False, "result_id": None},
            expected_video_id="runtime-video-1",
        )
    except RuntimeError as exc:
        assert "Expected ingested/indexed response" in str(exc)
    else:
        raise AssertionError("validate_ingest_response should reject skipped responses")


def test_validate_indexed_document_accepts_required_fields():
    validate_indexed_document(
        {
            "video_id": "runtime-video-1",
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": [0.11, 0.22, 0.33],
            "metadata": {"site": "runtime-yard"},
        },
        expected_video_id="runtime-video-1",
    )


def test_validate_indexed_document_rejects_wrong_video_id():
    try:
        validate_indexed_document({"video_id": "other", "metadata": {}}, expected_video_id="runtime-video-1")
    except RuntimeError as exc:
        assert "video_id" in str(exc)
    else:
        raise AssertionError("validate_indexed_document should reject mismatched video_id")
