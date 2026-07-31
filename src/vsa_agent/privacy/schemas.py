"""Closed remote-safe DTOs and their canonical enum-only representation."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

PRIVACY_POLICY_VERSION = "remote-egress-v1"
CANONICAL_MAPPING_VERSION = "safety-event-map-v1"

BoundedQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
OpaqueResultRef = Annotated[str, StringConstraints(pattern=r"^r_[0-9a-f]{32}$")]


class PrivacyPolicyError(ValueError):
    """A value is not safe to send to a remote provider."""


class EventType(StrEnum):
    FORKLIFT_PERSON_PROXIMITY = "forklift_person_proximity"
    PPE_MISSING = "ppe_missing"
    RESTRICTED_ZONE_INTRUSION = "restricted_zone_intrusion"
    UNSAFE_VEHICLE_OPERATION = "unsafe_vehicle_operation"
    FALL_OR_PERSON_DOWN = "fall_or_person_down"
    SMOKE_OR_FIRE = "smoke_or_fire"
    NO_SAFETY_EVENT = "no_safety_event"
    OTHER_SAFETY_EVENT = "other_safety_event"


class ObjectCategory(StrEnum):
    PERSON = "person"
    FORKLIFT = "forklift"
    VEHICLE = "vehicle"
    HELMET = "helmet"
    SAFETY_VEST = "safety_vest"
    RESPIRATOR = "respirator"
    SMOKE = "smoke"
    FIRE = "fire"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceBucket(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RuleTag(StrEnum):
    VEHICLE_PERSON_SEPARATION = "vehicle_person_separation"
    PPE_HELMET = "ppe_helmet"
    PPE_SAFETY_VEST = "ppe_safety_vest"
    PPE_RESPIRATORY = "ppe_respiratory"
    RESTRICTED_ZONE = "restricted_zone"
    SAFE_VEHICLE_OPERATION = "safe_vehicle_operation"
    FALL_RESPONSE = "fall_response"
    FIRE_RESPONSE = "fire_response"


class PPEItem(StrEnum):
    HELMET = "helmet"
    SAFETY_VEST = "safety_vest"
    RESPIRATOR = "respirator"


class PPEStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


class _RemoteSafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class RemoteSafeObjectCount(_RemoteSafeModel):
    category: ObjectCategory
    count: int = Field(ge=1, le=100)


class RemoteSafePPEState(_RemoteSafeModel):
    item: PPEItem
    status: PPEStatus


class RemoteSafeIngestEvent(_RemoteSafeModel):
    policy_version: Literal[PRIVACY_POLICY_VERSION] = PRIVACY_POLICY_VERSION
    mapping_version: Literal[CANONICAL_MAPPING_VERSION] = CANONICAL_MAPPING_VERSION
    result_ref: OpaqueResultRef
    event_type: EventType
    start_offset_ms: int = Field(ge=0, le=604_800_000)
    end_offset_ms: int = Field(ge=0, le=604_800_000)
    objects: tuple[RemoteSafeObjectCount, ...] = Field(default=(), max_length=16)
    risk_level: RiskLevel
    confidence: ConfidenceBucket
    rule_tags: tuple[RuleTag, ...] = Field(default=(), max_length=16)
    ppe: tuple[RemoteSafePPEState, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def validate_offsets_and_uniqueness(self) -> RemoteSafeIngestEvent:
        if self.end_offset_ms < self.start_offset_ms:
            raise ValueError("end_offset_ms must not precede start_offset_ms")
        if len({item.category for item in self.objects}) != len(self.objects):
            raise ValueError("object categories must be unique")
        if len(set(self.rule_tags)) != len(self.rule_tags):
            raise ValueError("rule tags must be unique")
        if len({item.item for item in self.ppe}) != len(self.ppe):
            raise ValueError("PPE items must be unique")
        return self


class RemoteSafeSearchQuery(_RemoteSafeModel):
    policy_version: Literal[PRIVACY_POLICY_VERSION] = PRIVACY_POLICY_VERSION
    query: BoundedQuery

    @field_validator("query")
    @classmethod
    def reject_sensitive_query(cls, value: str) -> str:
        classification = classify_sensitive_query(value)
        if classification != "safe":
            raise PrivacyPolicyError(f"query rejected by privacy policy: {classification}")
        return value

    @property
    def query_sha256(self) -> str:
        return hashlib.sha256(self.query.encode("utf-8")).hexdigest()


class RemoteSafeSearchContext(_RemoteSafeModel):
    policy_version: Literal[PRIVACY_POLICY_VERSION] = PRIVACY_POLICY_VERSION
    events: tuple[RemoteSafeIngestEvent, ...] = Field(default=(), max_length=20)


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class RemoteSafeConversationTurn(_RemoteSafeModel):
    policy_version: Literal[PRIVACY_POLICY_VERSION] = PRIVACY_POLICY_VERSION
    role: ConversationRole
    query: RemoteSafeSearchQuery | None = None
    result_refs: tuple[OpaqueResultRef, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_role_payload(self) -> RemoteSafeConversationTurn:
        if self.role is ConversationRole.USER and self.query is None:
            raise ValueError("user conversation turns require a safe query")
        if self.role is ConversationRole.ASSISTANT and self.query is not None:
            raise ValueError("assistant turns cannot carry free text")
        return self


_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)/(?:home|data|mnt|srv|var|tmp)/|\\\\[^\s]+\\)", re.I)
_UUID_PATTERN = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)|(?<!\d)\+\d{7,15}(?!\d)")
_ABSOLUTE_TIME_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?)?\b"
)
_CAMERA_PATTERN = re.compile(r"\b(?:camera|cam|sensor|摄像头|相机|传感器|工号|employee)[-_:#\s]*[A-Z0-9]{2,}\b", re.I)
_LOCATION_PATTERN = re.compile(r"(?:位于|地点|位置|location|address|地址)\s*[:：]?\s*[\w\u4e00-\u9fff-]{2,}", re.I)


def classify_sensitive_query(value: str) -> str:
    """Return a stable classification without retaining or logging query text."""

    checks = (
        ("path", _PATH_PATTERN),
        ("uuid", _UUID_PATTERN),
        ("email", _EMAIL_PATTERN),
        ("phone", _PHONE_PATTERN),
        ("absolute_time", _ABSOLUTE_TIME_PATTERN),
        ("camera_or_employee_id", _CAMERA_PATTERN),
        ("location", _LOCATION_PATTERN),
    )
    for classification, pattern in checks:
        if pattern.search(value):
            return classification
    for token in re.findall(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])", value):
        try:
            ipaddress.ip_address(token)
        except ValueError:
            continue
        return "ip_address"
    return "safe"


def opaque_result_ref(*identity_parts: str) -> str:
    if not identity_parts or any(not isinstance(part, str) or not part for part in identity_parts):
        raise ValueError("opaque result reference requires nonblank identity parts")
    digest = hashlib.sha256("\x1f".join(identity_parts).encode("utf-8")).hexdigest()
    return f"r_{digest[:32]}"


def canonical_embedding_text(event: RemoteSafeIngestEvent) -> str:
    """Render only versioned enum and numeric fields in a stable order."""

    object_text = (
        ",".join(
            f"{item.category.value}:{item.count}"
            for item in sorted(event.objects, key=lambda item: item.category.value)
        )
        or "none"
    )
    rules = ",".join(sorted(item.value for item in event.rule_tags)) or "none"
    ppe = (
        ",".join(
            f"{item.item.value}:{item.status.value}" for item in sorted(event.ppe, key=lambda item: item.item.value)
        )
        or "none"
    )
    return (
        f"mapping={event.mapping_version};event={event.event_type.value};"
        f"offset_ms={event.start_offset_ms}-{event.end_offset_ms};objects={object_text};"
        f"risk={event.risk_level.value};confidence={event.confidence.value};rules={rules};ppe={ppe}"
    )
