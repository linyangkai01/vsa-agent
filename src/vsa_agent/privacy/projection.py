"""Deterministic projection from local free text to closed remote-safe events."""

from __future__ import annotations

import re
from collections.abc import Iterable

from vsa_agent.privacy.schemas import (
    ConfidenceBucket,
    EventType,
    ObjectCategory,
    PPEItem,
    PPEStatus,
    RemoteSafeIngestEvent,
    RemoteSafeObjectCount,
    RemoteSafePPEState,
    RiskLevel,
    RuleTag,
    opaque_result_ref,
)


def _contains(text: str, *terms: str) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms)


def project_ingest_event(
    *,
    description: str,
    tags: Iterable[str],
    segment_id: str,
    job_id: str,
    start_offset_ms: int,
    end_offset_ms: int,
) -> RemoteSafeIngestEvent:
    """Classify local VLM output without forwarding any model-authored text."""

    local_text = " ".join([description, *tags]).lower()
    has_person = _contains(local_text, "person", "people", "worker", "workers", "woman", "man")
    has_forklift = _contains(local_text, "forklift", "lift truck")
    has_vehicle = has_forklift or _contains(local_text, "vehicle", "truck", "car")
    missing = _contains(local_text, "missing", "absent", "not wearing", "not worn", "without")
    has_helmet = _contains(local_text, "helmet", "hard hat", "hardhat")
    has_vest = _contains(local_text, "safety vest", "high visibility vest", "hi-vis", "reflective vest")
    has_respirator = _contains(local_text, "respirator", "respiratory protection", "dust mask")
    proximity = _contains(local_text, "near", "close", "closely", "proximity", "approach", "approaching")
    restricted = _contains(local_text, "restricted zone", "restricted area", "exclusion zone", "intrusion")
    fallen = _contains(local_text, "fallen", "person down", "lying on the ground", "collapse", "collapsed")
    smoke = _contains(local_text, "smoke", "smoking")
    fire = _contains(local_text, "fire", "flame", "flames")
    unsafe_vehicle = _contains(local_text, "unsafe driving", "speeding", "collision", "reckless")

    if fire or smoke:
        event_type = EventType.SMOKE_OR_FIRE
        risk = RiskLevel.CRITICAL
    elif fallen and has_person:
        event_type = EventType.FALL_OR_PERSON_DOWN
        risk = RiskLevel.HIGH
    elif restricted and has_person:
        event_type = EventType.RESTRICTED_ZONE_INTRUSION
        risk = RiskLevel.HIGH
    elif has_forklift and has_person and proximity:
        event_type = EventType.FORKLIFT_PERSON_PROXIMITY
        risk = RiskLevel.HIGH
    elif missing and (has_helmet or has_vest or has_respirator):
        event_type = EventType.PPE_MISSING
        risk = RiskLevel.MEDIUM
    elif unsafe_vehicle and has_vehicle:
        event_type = EventType.UNSAFE_VEHICLE_OPERATION
        risk = RiskLevel.HIGH
    elif any((has_person, has_vehicle, has_helmet, has_vest, has_respirator)):
        event_type = EventType.NO_SAFETY_EVENT
        risk = RiskLevel.NONE
    else:
        event_type = EventType.OTHER_SAFETY_EVENT
        risk = RiskLevel.LOW

    objects: list[RemoteSafeObjectCount] = []
    for present, category in (
        (has_person, ObjectCategory.PERSON),
        (has_forklift, ObjectCategory.FORKLIFT),
        (has_vehicle and not has_forklift, ObjectCategory.VEHICLE),
        (has_helmet, ObjectCategory.HELMET),
        (has_vest, ObjectCategory.SAFETY_VEST),
        (has_respirator, ObjectCategory.RESPIRATOR),
        (smoke, ObjectCategory.SMOKE),
        (fire, ObjectCategory.FIRE),
    ):
        if present:
            objects.append(RemoteSafeObjectCount(category=category, count=1))

    rules: list[RuleTag] = []
    if has_vehicle and has_person:
        rules.append(RuleTag.VEHICLE_PERSON_SEPARATION)
    if has_helmet:
        rules.append(RuleTag.PPE_HELMET)
    if has_vest:
        rules.append(RuleTag.PPE_SAFETY_VEST)
    if has_respirator:
        rules.append(RuleTag.PPE_RESPIRATORY)
    if restricted:
        rules.append(RuleTag.RESTRICTED_ZONE)
    if has_vehicle:
        rules.append(RuleTag.SAFE_VEHICLE_OPERATION)
    if fallen:
        rules.append(RuleTag.FALL_RESPONSE)
    if fire or smoke:
        rules.append(RuleTag.FIRE_RESPONSE)

    ppe = tuple(
        RemoteSafePPEState(item=item, status=PPEStatus.MISSING if missing else PPEStatus.PRESENT)
        for present, item in (
            (has_helmet, PPEItem.HELMET),
            (has_vest, PPEItem.SAFETY_VEST),
            (has_respirator, PPEItem.RESPIRATOR),
        )
        if present
    )
    return RemoteSafeIngestEvent(
        result_ref=opaque_result_ref(job_id, segment_id),
        event_type=event_type,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
        objects=tuple(objects),
        risk_level=risk,
        confidence=ConfidenceBucket.MEDIUM,
        rule_tags=tuple(dict.fromkeys(rules)),
        ppe=ppe,
    )
