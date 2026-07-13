"""Persistable domain models for recorded-video ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

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


class Asset(BaseModel):
    asset_id: str
    display_filename: str
    safe_filename: str
    size_bytes: int
    sha256: str
    mime_type: str
    source_extension: str
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    timeline_origin: datetime
    status: AssetStatus
    current_job_id: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class UploadSession(BaseModel):
    session_id: str
    identifier: str
    asset_id: str
    total_chunks: int
    received_chunks: int = 0
    filename: str
    temp_dir: str
    status: AssetStatus
    expires_at: datetime


class Job(BaseModel):
    job_id: str
    asset_id: str
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage | None = None
    attempt: int = 0
    next_run_at: datetime | None = None
    lease_owner: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobStep(BaseModel):
    job_id: str
    stage: JobStage
    status: JobStatus
    output_manifest: str | None = None
    output_checksum: str | None = None
    model: str | None = None
    elapsed_ms: int | None = None


class Segment(BaseModel):
    segment_id: str
    asset_id: str
    pipeline_version: str
    ordinal: int
    start_offset_ms: int
    end_offset_ms: int
    start_time: datetime
    end_time: datetime
    description: str = ""
    thumbnail_key: str | None = None
    model: str | None = None
    prompt_version: str | None = None


ALLOWED_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.COMPLETED,
        JobStatus.RETRY_WAIT,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.RETRY_WAIT: {JobStatus.QUEUED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def transition_job(job: Job, target: JobStatus) -> Job:
    """Return a copy of ``job`` in ``target`` or reject the transition."""
    target = JobStatus(target)
    if target not in ALLOWED_JOB_TRANSITIONS[job.status]:
        raise InvalidStateTransition(job.status, target)
    return job.model_copy(update={"status": target})


def segment_id(asset_id: str, pipeline_version: str, ordinal: int) -> str:
    """Build the stable identifier for a pipeline segment."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{asset_id}:{pipeline_version}:{ordinal}"))
