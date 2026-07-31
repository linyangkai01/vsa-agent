import pytest
from pydantic import ValidationError

from vsa_agent.privacy.schemas import (
    EventType,
    PrivacyPolicyError,
    RemoteSafeIngestEvent,
    RemoteSafeSearchQuery,
    RiskLevel,
    canonical_embedding_text,
    opaque_result_ref,
)


@pytest.mark.parametrize(
    ("query", "classification"),
    [
        ("find /data/private/alice.mp4", "path"),
        ("alice@example.com without helmet", "email"),
        ("camera-77 forklift event", "camera_or_employee_id"),
        ("event at 2026-07-30 09:15", "absolute_time"),
        ("call 13800138000", "phone"),
        ("host 10.157.68.44", "ip_address"),
    ],
)
def test_remote_search_query_rejects_sensitive_text(query, classification):
    with pytest.raises((PrivacyPolicyError, ValidationError), match=classification):
        RemoteSafeSearchQuery(query=query)


def test_remote_event_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RemoteSafeIngestEvent(
            result_ref=opaque_result_ref("job", "segment"),
            event_type=EventType.NO_SAFETY_EVENT,
            start_offset_ms=0,
            end_offset_ms=1,
            risk_level=RiskLevel.NONE,
            video_path="/data/private/alice.mp4",
        )


def test_canonical_text_contains_only_closed_fields():
    event = RemoteSafeIngestEvent(
        result_ref=opaque_result_ref("job", "segment"),
        event_type=EventType.FORKLIFT_PERSON_PROXIMITY,
        start_offset_ms=1000,
        end_offset_ms=2000,
        risk_level=RiskLevel.HIGH,
        confidence="medium",
    )

    text = canonical_embedding_text(event)

    assert "forklift_person_proximity" in text
    assert event.result_ref not in text
    assert "/data/" not in text
