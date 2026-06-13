"""Tests for data_models/understanding.py."""

import pytest
from pydantic import ValidationError

from vsa_agent.data_models import (
    DetectedEvent as ExportedDetectedEvent,
    EvidenceRef as ExportedEvidenceRef,
    ObservationChunk as ExportedObservationChunk,
    SummaryResult as ExportedSummaryResult,
    UnderstandingResult as ExportedUnderstandingResult,
)
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


def test_understanding_models_are_reexported():
    assert ExportedEvidenceRef is EvidenceRef
    assert ExportedObservationChunk is ObservationChunk
    assert ExportedDetectedEvent is DetectedEvent
    assert ExportedUnderstandingResult is UnderstandingResult
    assert ExportedSummaryResult is SummaryResult


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"source_type": "video_file"}, "video_path"),
        ({"source_type": "rtsp"}, "sensor_id"),
    ],
)
def test_evidence_ref_rejects_invalid_source_specific_payloads(payload, expected_message):
    with pytest.raises(ValidationError, match=expected_message):
        EvidenceRef(**payload)


def test_summary_result_construction_from_nested_dict_payload():
    summary = SummaryResult(
        query="what happened",
        text_output="person walking near forklift",
        structured_output={
            "query": "what happened",
            "source_type": "video_file",
            "summary_text": "person walking near forklift",
            "chunks": [
                {
                    "chunk_id": "c1",
                    "start_timestamp": "2025-01-01T10:00:00Z",
                    "end_timestamp": "2025-01-01T10:00:10Z",
                    "prompt_used": "watch carefully",
                    "raw_model_output": "person walking",
                    "normalized_text": "person walking near forklift",
                    "evidence": {
                        "source_type": "video_file",
                        "video_path": "a.mp4",
                    },
                }
            ],
            "events": [
                {
                    "event_id": "e1",
                    "label": "walking",
                    "description": "person walking near forklift",
                    "start_timestamp": "2025-01-01T10:00:00Z",
                    "end_timestamp": "2025-01-01T10:00:05Z",
                    "evidence": [
                        {
                            "source_type": "video_file",
                            "video_path": "a.mp4",
                        }
                    ],
                }
            ],
        },
    )

    assert isinstance(summary.structured_output, UnderstandingResult)
    assert isinstance(summary.structured_output.chunks[0], ObservationChunk)
    assert isinstance(summary.structured_output.events[0], DetectedEvent)
    assert isinstance(summary.structured_output.events[0].evidence[0], EvidenceRef)


def test_model_defaults_are_independent_between_instances():
    first = EvidenceRef(source_type="video_file", video_path="a.mp4")
    second = EvidenceRef(source_type="video_file", video_path="b.mp4")
    first.frame_indices.append(1)

    first_result = UnderstandingResult(
        query="first",
        source_type="video_file",
        summary_text="first summary",
    )
    second_result = UnderstandingResult(
        query="second",
        source_type="video_file",
        summary_text="second summary",
    )
    first_result.metadata["key"] = "value"

    assert second.frame_indices == []
    assert second_result.metadata == {}


@pytest.mark.parametrize(
    ("model_class", "payload", "expected_message"),
    [
        (
            EvidenceRef,
            {
                "source_type": "video_file",
                "video_path": "a.mp4",
                "unexpected": "value",
            },
            "unexpected",
        ),
        (
            ObservationChunk,
            {
                "chunk_id": "c1",
                "start_timestamp": "2025-01-01T10:00:00Z",
                "end_timestamp": "2025-01-01T10:00:10Z",
                "prompt_used": "watch carefully",
                "raw_model_output": "person walking",
                "normalized_text": "person walking near forklift",
                "evidence": {
                    "source_type": "video_file",
                    "video_path": "a.mp4",
                },
                "unexpected": "value",
            },
            "unexpected",
        ),
        (
            DetectedEvent,
            {
                "event_id": "e1",
                "label": "walking",
                "description": "person walking near forklift",
                "start_timestamp": "2025-01-01T10:00:00Z",
                "end_timestamp": "2025-01-01T10:00:05Z",
                "unexpected": "value",
            },
            "unexpected",
        ),
        (
            UnderstandingResult,
            {
                "query": "what happened",
                "source_type": "video_file",
                "summary_text": "person walking near forklift",
                "unexpected": "value",
            },
            "unexpected",
        ),
        (
            SummaryResult,
            {
                "query": "what happened",
                "text_output": "person walking near forklift",
                "structured_output": {
                    "query": "what happened",
                    "source_type": "video_file",
                    "summary_text": "person walking near forklift",
                },
                "unexpected": "value",
            },
            "unexpected",
        ),
    ],
)
def test_understanding_models_reject_unexpected_extra_keys(model_class, payload, expected_message):
    with pytest.raises(ValidationError, match=expected_message):
        model_class(**payload)


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "source_type": "video_file",
                "video_path": "a.mp4",
                "sensor_id": "cam-1",
            },
            "sensor_id",
        ),
        (
            {
                "source_type": "rtsp",
                "sensor_id": "cam-1",
                "video_path": "a.mp4",
            },
            "video_path",
        ),
    ],
)
def test_evidence_ref_rejects_mixed_source_fields(payload, expected_message):
    with pytest.raises(ValidationError, match=expected_message):
        EvidenceRef(**payload)


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "query": "what happened",
                "source_type": "video_file",
                "summary_text": "person walking near forklift",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "start_timestamp": "2025-01-01T10:00:00Z",
                        "end_timestamp": "2025-01-01T10:00:10Z",
                        "prompt_used": "watch carefully",
                        "raw_model_output": "person walking",
                        "normalized_text": "person walking near forklift",
                        "evidence": {
                            "source_type": "rtsp",
                            "sensor_id": "cam-1",
                        },
                    }
                ],
            },
            "chunks",
        ),
        (
            {
                "query": "what happened",
                "source_type": "rtsp",
                "summary_text": "person walking near forklift",
                "events": [
                    {
                        "event_id": "e1",
                        "label": "walking",
                        "description": "person walking near forklift",
                        "start_timestamp": "2025-01-01T10:00:00Z",
                        "end_timestamp": "2025-01-01T10:00:05Z",
                        "evidence": [
                            {
                                "source_type": "video_file",
                                "video_path": "a.mp4",
                            }
                        ],
                    }
                ],
            },
            "events",
        ),
    ],
)
def test_understanding_result_rejects_mixed_nested_source_types(payload, expected_message):
    with pytest.raises(ValidationError, match=expected_message):
        UnderstandingResult(**payload)


def test_summary_result_rejects_mismatched_query():
    with pytest.raises(ValidationError, match="query"):
        SummaryResult(
            query="what happened",
            text_output="person walking near forklift",
            structured_output={
                "query": "different query",
                "source_type": "video_file",
                "summary_text": "person walking near forklift",
            },
        )


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "source_type": "video_file",
                "video_path": "   ",
            },
            "video_path",
        ),
        (
            {
                "source_type": "rtsp",
                "sensor_id": "   ",
            },
            "sensor_id",
        ),
    ],
)
def test_evidence_ref_rejects_whitespace_only_source_identifiers(payload, expected_message):
    with pytest.raises(ValidationError, match=expected_message):
        EvidenceRef(**payload)
