from __future__ import annotations

from typing import Any


def sample_payload(video_id: str) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "metadata": {
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": [0.11, 0.22, 0.33],
            "site": "runtime-yard",
        },
    }


def validate_ingest_response(payload: dict[str, Any], expected_video_id: str) -> str:
    if payload.get("status") != "ingested" or payload.get("indexed") is not True:
        raise RuntimeError(f"Expected ingested/indexed response, got: {payload}")
    if payload.get("video_id") != expected_video_id:
        raise RuntimeError(f"Expected video_id {expected_video_id!r}, got {payload.get('video_id')!r}")
    result_id = payload.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        raise RuntimeError(f"Expected non-empty result_id, got: {result_id!r}")
    return result_id


def validate_indexed_document(document: dict[str, Any], expected_video_id: str) -> None:
    expected = sample_payload(expected_video_id)["metadata"]
    checks = {
        "video_id": expected_video_id,
        "video_name": expected["video_name"],
        "description": expected["description"],
        "sensor_id": expected["sensor_id"],
        "start_time": expected["start_time"],
        "end_time": expected["end_time"],
        "screenshot_url": expected["screenshot_url"],
        "vector": expected["vector"],
    }
    for key, value in checks.items():
        if document.get(key) != value:
            raise RuntimeError(f"Indexed document field {key!r} mismatch: expected {value!r}, got {document.get(key)!r}")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("site") != "runtime-yard":
        raise RuntimeError(f"Indexed document metadata missing expected site: {metadata!r}")
