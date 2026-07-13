"""Persistable domain models for recorded-video ingestion."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from vsa_agent.recorded_video.errors import InvalidStateTransition


class AssetStatus(str, Enum):
    UPLOADING = "uploading"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(str, Enum):
    PROBING = "probing"
    SEGMENTING = "segmenting"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    PUBLISH = "publish"


class _FrozenDict(Mapping[str, Any]):
    """Read-only mapping used inside persisted configuration snapshots."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _freeze_json(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _serialize_frozen_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _serialize_frozen_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_frozen_json(item) for item in value]
    return value


ConfigSnapshot = Annotated[
    dict[str, JsonValue],
    AfterValidator(_freeze_json),
    PlainSerializer(
        _serialize_frozen_json,
        return_type=dict[str, JsonValue],
    ),
]
PipelineVersion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Asset(BaseModel):
    asset_id: str
    display_filename: str
    safe_filename: str
    size_bytes: int = Field(ge=0)
    sha256: str
    mime_type: str
    source_extension: str
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    timeline_origin: AwareDatetime
    status: AssetStatus
    current_job_id: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: AwareDatetime | None = None


class UploadSession(BaseModel):
    session_id: str
    identifier: str
    asset_id: str
    total_chunks: int = Field(gt=0)
    received_chunks: int = Field(default=0, ge=0)
    filename: str
    temp_dir: str
    status: AssetStatus
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_chunk_counts(self) -> UploadSession:
        if self.received_chunks > self.total_chunks:
            raise ValueError("received_chunks cannot exceed total_chunks")
        return self


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    asset_id: str
    pipeline_version: PipelineVersion
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage | None = None
    attempt: int = Field(default=0, ge=0)
    next_run_at: AwareDatetime | None = None
    lease_owner: str | None = None
    lease_until: AwareDatetime | None = None
    heartbeat_at: AwareDatetime | None = None
    config_snapshot: ConfigSnapshot = Field(default_factory=lambda: _FrozenDict({}))
    last_error: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class JobStep(BaseModel):
    job_id: str
    stage: JobStage
    status: JobStatus
    output_manifest: str | None = None
    output_checksum: str | None = None
    model: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)


class Segment(BaseModel):
    segment_id: str
    asset_id: str
    pipeline_version: PipelineVersion
    ordinal: int = Field(ge=0)
    start_offset_ms: int = Field(ge=0)
    end_offset_ms: int = Field(ge=0)
    start_time: AwareDatetime
    end_time: AwareDatetime
    description: str = ""
    thumbnail_key: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Segment:
        if self.end_offset_ms < self.start_offset_ms:
            raise ValueError("end_offset_ms cannot be earlier than start_offset_ms")
        if self.end_time < self.start_time:
            raise ValueError("end_time cannot be earlier than start_time")
        return self


ALLOWED_JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = MappingProxyType(
    {
        JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
        JobStatus.RUNNING: frozenset(
            {
                JobStatus.COMPLETED,
                JobStatus.RETRY_WAIT,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }
        ),
        JobStatus.RETRY_WAIT: frozenset({JobStatus.QUEUED}),
        JobStatus.COMPLETED: frozenset(),
        JobStatus.FAILED: frozenset(),
        JobStatus.CANCELLED: frozenset(),
    }
)


def transition_job(job: Job, target: JobStatus) -> Job:
    """Return a copy of ``job`` in ``target`` or reject the transition."""
    target = JobStatus(target)
    if target not in ALLOWED_JOB_TRANSITIONS[job.status]:
        raise InvalidStateTransition(job.status, target)
    return job.model_copy(update={"status": target})


def segment_id(asset_id: str, pipeline_version: str, ordinal: int) -> str:
    """Build the stable identifier for a pipeline segment."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{asset_id}:{pipeline_version}:{ordinal}"))
