from vsa_agent.privacy.projection import project_ingest_event
from vsa_agent.privacy.schemas import EventType, canonical_embedding_text


def test_projection_does_not_forward_local_free_text_canaries():
    canaries = (
        "/data/private/Alice Example.mp4",
        "camera-77",
        "alice@example.com",
        "employee-secret-991",
    )
    description = "forklift close to worker " + " ".join(canaries)

    event = project_ingest_event(
        description=description,
        tags=("forklift", "worker", *canaries),
        segment_id="segment-private-name",
        job_id="job-private-name",
        start_offset_ms=1000,
        end_offset_ms=5000,
    )
    outbound = canonical_embedding_text(event)

    assert event.event_type is EventType.FORKLIFT_PERSON_PROXIMITY
    for canary in canaries:
        assert canary not in outbound
        assert canary not in event.model_dump_json()
    assert "segment-private-name" not in event.result_ref
    assert "job-private-name" not in event.result_ref
