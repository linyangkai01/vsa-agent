from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from vsa_agent.recorded_video.errors import (
    PERMANENT_ERROR_CODES,
    RETRYABLE_ERROR_CODES,
    ErrorCode,
    InvalidStateTransition,
    RecordedVideoError,
)
from vsa_agent.recorded_video.models import (
    ALLOWED_JOB_TRANSITIONS,
    Asset,
    AssetStatus,
    Job,
    JobStage,
    JobStatus,
    JobStep,
    Segment,
    UploadSession,
    segment_id,
    transition_job,
)

NOW = datetime(2026, 7, 12, 8, 30, tzinfo=UTC)


def _job(status: JobStatus) -> Job:
    return Job(
        job_id="job-1",
        asset_id="asset-1",
        status=status,
        pipeline_version="v1",
        stage=JobStage.PROBING,
        attempt=1,
        config_snapshot={"pipeline_version": "v1"},
        created_at=NOW,
        updated_at=NOW,
    )


def test_running_job_cannot_return_to_queued_and_segment_id_is_stable() -> None:
    with pytest.raises(InvalidStateTransition, match="running.*queued"):
        transition_job(_job(JobStatus.RUNNING), JobStatus.QUEUED)

    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "a:v1:2"))
    assert segment_id("a", "v1", 2) == expected
    assert segment_id("a", "v1", 2) == segment_id("a", "v1", 2)


def test_job_status_graph_contains_only_the_supported_transitions() -> None:
    assert ALLOWED_JOB_TRANSITIONS == {
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


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.RUNNING, JobStatus.COMPLETED),
        (JobStatus.RUNNING, JobStatus.RETRY_WAIT),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.CANCELLED),
        (JobStatus.RETRY_WAIT, JobStatus.QUEUED),
    ],
)
def test_transition_job_returns_an_updated_copy(source: JobStatus, target: JobStatus) -> None:
    original = _job(source)

    transitioned = transition_job(original, target)

    assert transitioned.status is target
    assert original.status is source
    assert transitioned.job_id == original.job_id


def test_invalid_transition_reports_source_and_target() -> None:
    with pytest.raises(InvalidStateTransition) as captured:
        transition_job(_job(JobStatus.COMPLETED), JobStatus.RUNNING)

    assert captured.value.source is JobStatus.COMPLETED
    assert captured.value.target is JobStatus.RUNNING
    assert "completed" in str(captured.value)
    assert "running" in str(captured.value)


def test_error_codes_are_partitioned_by_retryability() -> None:
    assert PERMANENT_ERROR_CODES == {
        ErrorCode.CORRUPT_MEDIA,
        ErrorCode.UNSUPPORTED_MEDIA,
        ErrorCode.FFMPEG_MISSING,
        ErrorCode.CONFIGURATION,
        ErrorCode.EMBEDDING_DIMENSION,
    }
    assert RETRYABLE_ERROR_CODES == {
        ErrorCode.MODEL_RATE_LIMIT,
        ErrorCode.MODEL_TIMEOUT,
        ErrorCode.MODEL_5XX,
        ErrorCode.ES_TIMEOUT,
        ErrorCode.ES_5XX,
    }
    assert not (PERMANENT_ERROR_CODES & RETRYABLE_ERROR_CODES)


def test_recorded_video_error_rejects_retryability_that_conflicts_with_code() -> None:
    with pytest.raises(ValueError):
        RecordedVideoError(ErrorCode.CORRUPT_MEDIA, retryable=True)
    with pytest.raises(ValueError):
        RecordedVideoError(ErrorCode.MODEL_TIMEOUT, retryable=False)


def test_job_requires_non_empty_pipeline_version_and_is_frozen() -> None:
    with pytest.raises(ValueError):
        Job(
            job_id="job-1",
            asset_id="asset-1",
            pipeline_version="",
            created_at=NOW,
            updated_at=NOW,
        )

    job = _job(JobStatus.QUEUED)
    with pytest.raises((TypeError, ValueError)):
        job.status = JobStatus.RUNNING


def test_job_transition_table_is_deeply_immutable() -> None:
    with pytest.raises((TypeError, AttributeError)):
        ALLOWED_JOB_TRANSITIONS[JobStatus.QUEUED].add(JobStatus.COMPLETED)


@pytest.mark.parametrize("code", sorted(PERMANENT_ERROR_CODES, key=str))
def test_recorded_video_error_preserves_permanent_classification(code: ErrorCode) -> None:
    error = RecordedVideoError(code, retryable=False)

    assert error.code is code
    assert error.retryable is False
    assert code.value in str(error)


@pytest.mark.parametrize("code", sorted(RETRYABLE_ERROR_CODES, key=str))
def test_recorded_video_error_preserves_retryable_classification(code: ErrorCode) -> None:
    error = RecordedVideoError(code, retryable=True)

    assert error.code is code
    assert error.retryable is True
    assert code.value in str(error)


def test_domain_models_expose_persistable_recorded_video_fields() -> None:
    asset = Asset(
        asset_id="asset-1",
        display_filename="Camera One.mp4",
        safe_filename="camera-one.mp4",
        size_bytes=1024,
        sha256="a" * 64,
        mime_type="video/mp4",
        source_extension="mp4",
        duration_ms=30_000,
        width=1920,
        height=1080,
        timeline_origin=NOW,
        status=AssetStatus.READY,
        current_job_id="job-1",
        created_at=NOW,
        updated_at=NOW,
    )
    upload = UploadSession(
        session_id="session-1",
        identifier="nvstreamer-id",
        asset_id=asset.asset_id,
        total_chunks=2,
        received_chunks=1,
        filename=asset.display_filename,
        temp_dir="video-data/uploads/session-1",
        status=AssetStatus.UPLOADING,
        expires_at=NOW,
    )
    step = JobStep(
        job_id="job-1",
        stage=JobStage.ANALYZING,
        status=JobStatus.COMPLETED,
        output_manifest="derived/v1/manifest.json",
        output_checksum="b" * 64,
        model="vision-model",
        elapsed_ms=1234,
    )
    segment = Segment(
        segment_id=segment_id(asset.asset_id, "v1", 0),
        asset_id=asset.asset_id,
        pipeline_version="v1",
        ordinal=0,
        start_offset_ms=0,
        end_offset_ms=30_000,
        start_time=NOW,
        end_time=NOW,
        description="A person enters the scene.",
        thumbnail_key="derived/v1/thumbnails/segment.jpg",
        model="vision-model",
        prompt_version="prompt-v1",
    )

    assert asset.model_dump(mode="json")["timeline_origin"] == "2026-07-12T08:30:00Z"
    assert upload.total_chunks == 2
    assert step.stage is JobStage.ANALYZING
    assert segment.end_offset_ms == 30_000


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Asset(
            asset_id="asset-1",
            display_filename="video.mp4",
            safe_filename="video.mp4",
            size_bytes=1,
            sha256="a" * 64,
            mime_type="video/mp4",
            source_extension="mp4",
            timeline_origin=datetime(2026, 7, 12, 8, 30),
            status=AssetStatus.READY,
            created_at=NOW,
            updated_at=NOW,
        ),
        lambda: UploadSession(
            session_id="session-1",
            identifier="id",
            asset_id="asset-1",
            total_chunks=1,
            filename="video.mp4",
            temp_dir="tmp",
            status=AssetStatus.UPLOADING,
            expires_at=datetime(2026, 7, 12, 8, 30),
        ),
    ],
)
def test_persisted_datetimes_must_be_timezone_aware(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_persistable_models_reject_invalid_numeric_and_cross_field_values() -> None:
    with pytest.raises(ValueError):
        UploadSession(
            session_id="session-1",
            identifier="id",
            asset_id="asset-1",
            total_chunks=1,
            received_chunks=2,
            filename="video.mp4",
            temp_dir="tmp",
            status=AssetStatus.UPLOADING,
            expires_at=NOW,
        )
    with pytest.raises(ValueError):
        Segment(
            segment_id="segment-1",
            asset_id="asset-1",
            pipeline_version="v1",
            ordinal=0,
            start_offset_ms=20,
            end_offset_ms=10,
            start_time=NOW,
            end_time=NOW,
        )
