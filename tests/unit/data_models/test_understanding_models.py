"""Tests for data_models/understanding.py."""

from vsa_agent.data_models.understanding import (
    DetectedEvent,
    EvidenceRef,
    ObservationChunk,
    SummaryResult,
    UnderstandingResult,
)


def test_understanding_result_construction():
    evidence = EvidenceRef(source_type="video_file", video_path="a.mp4")
    chunk = ObservationChunk(
        chunk_id="c1",
        start_timestamp="2025-01-01T10:00:00Z",
        end_timestamp="2025-01-01T10:00:10Z",
        prompt_used="watch carefully",
        raw_model_output="person walking",
        normalized_text="person walking near forklift",
        evidence=evidence,
    )
    event = DetectedEvent(
        event_id="e1",
        label="walking",
        description="person walking near forklift",
        start_timestamp="2025-01-01T10:00:00Z",
        end_timestamp="2025-01-01T10:00:05Z",
        evidence=[evidence],
    )
    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person walking near forklift",
        chunks=[chunk],
        events=[event],
    )
    summary = SummaryResult(
        query="what happened",
        text_output="person walking near forklift",
        structured_output=result,
    )

    assert summary.structured_output.events[0].label == "walking"


def test_understanding_model_defaults():
    evidence = EvidenceRef(source_type="rtsp", sensor_id="cam-1")
    event = DetectedEvent(
        event_id="e2",
        label="idle",
        description="scene remains unchanged",
        start_timestamp="2025-01-01T10:00:00Z",
        end_timestamp="2025-01-01T10:00:05Z",
    )
    result = UnderstandingResult(
        query="status",
        source_type="rtsp",
        summary_text="scene remains unchanged",
        events=[event],
    )
    summary = SummaryResult(
        query="status",
        text_output="scene remains unchanged",
        structured_output=result,
    )

    assert evidence.frame_indices == []
    assert evidence.frame_timestamps == []
    assert event.actors == []
    assert event.objects == []
    assert event.evidence == []
    assert result.chunks == []
    assert result.metadata == {}
    assert summary.metadata == {}
