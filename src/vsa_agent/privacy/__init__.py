"""Typed privacy boundary for remote model providers."""

from vsa_agent.privacy.gateway import RemoteProviderGateway
from vsa_agent.privacy.projection import project_ingest_event
from vsa_agent.privacy.schemas import (
    CANONICAL_MAPPING_VERSION,
    PRIVACY_POLICY_VERSION,
    ConfidenceBucket,
    EventType,
    ObjectCategory,
    PPEItem,
    PPEStatus,
    RemoteSafeConversationTurn,
    RemoteSafeIngestEvent,
    RemoteSafeObjectCount,
    RemoteSafeSearchContext,
    RemoteSafeSearchQuery,
    RiskLevel,
    RuleTag,
    canonical_embedding_text,
)

__all__ = [
    "CANONICAL_MAPPING_VERSION",
    "PRIVACY_POLICY_VERSION",
    "ConfidenceBucket",
    "EventType",
    "ObjectCategory",
    "PPEItem",
    "PPEStatus",
    "RemoteProviderGateway",
    "RemoteSafeConversationTurn",
    "RemoteSafeIngestEvent",
    "RemoteSafeObjectCount",
    "RemoteSafeSearchContext",
    "RemoteSafeSearchQuery",
    "RiskLevel",
    "RuleTag",
    "canonical_embedding_text",
    "project_ingest_event",
]
