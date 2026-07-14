from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.media import MediaProbe
from vsa_agent.recorded_video.models import (
    Asset,
    AssetStatus,
    Job,
    JobStage,
    JobStatus,
    Segment,
    UploadSession,
)
from vsa_agent.recorded_video.pipeline import (
    RecordedVideoPipeline,
    load_verified_checkpoint,
)
from vsa_agent.recorded_video.ports import ProjectionResult, VisionDescription
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter

NOW = datetime(2026, 7, 14, 4, 0, tzinfo=UTC)


class FakeMediaProcessor:
    def __init__(self) -> None:
        self.probe_calls = 0
        self.extract_calls = 0

    async def probe(self, path: str | Path) -> MediaProbe:
        assert Path(path).read_bytes() == b"recorded-video"
        self.probe_calls += 1
        return MediaProbe(
            duration_ms=5_000,
            width=1280,
            height=720,
            format_names=frozenset({"mp4"}),
            video_codec="h264",
            pixel_format="yuv420p",
            audio_codec="aac",
        )

    async def extract_representative_frames(
        self,
        source_path: str | Path,
        segment: Segment,
        destination_dir: str | Path,
        *,
        frame_count: int,
    ) -> list[Path]:
        assert Path(source_path).read_bytes() == b"recorded-video"
        self.extract_calls += 1
        directory = Path(destination_dir)
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for ordinal in range(frame_count):
            path = directory / f"{segment.segment_id}-{ordinal + 1:02}.jpg"
            path.write_bytes(f"frame-{segment.segment_id}-{ordinal}".encode())
            paths.append(path)
        return paths


class FakeVisionProvider:
    model = "vision-model-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str]] = []
        self.api_key = "vision-secret-must-not-leak"

    async def describe(
        self,
        frame_keys: list[str | Path],
        segment: Segment,
        *,
        job_id: str,
    ) -> VisionDescription:
        self.calls.append(([str(path) for path in frame_keys], segment.segment_id, job_id))
        return VisionDescription(description=f"activity in segment {segment.ordinal}", tags=("activity",))


class FakeEmbeddingProvider:
    model = "embedding-model-v1"

    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[str] = []
        self.api_key = "embedding-secret-must-not-leak"

    async def embed(
        self,
        text: str,
        *,
        expected_dims: int,
        asset_id: str,
        job_id: str,
    ) -> tuple[float, ...]:
        del asset_id, job_id
        self.calls.append(text)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary embedding failure")
        assert expected_dims == 3
        return (0.1, 0.2, 0.3)


class FakeProjectionStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[dict[str, Any]]] = []

    async def project(self, documents: list[dict[str, Any]]) -> ProjectionResult:
        self.calls.append(documents)
        if self.fail:
            raise RuntimeError("projection unavailable")
        return ProjectionResult(indexed_ids=[str(document["_id"]) for document in documents])

    async def delete_asset(self, asset_id: str) -> None:
        del asset_id


async def _claimed_job(
    tmp_path: Path,
    clock: list[datetime],
    *,
    owner: str = "worker-1",
    pipeline_version: str = "pipeline-v1",
) -> tuple[JobRepository, LocalAssetStore, Job]:
    repository = JobRepository(
        tmp_path / "jobs.sqlite3",
        lease_seconds=30,
        clock=lambda: clock[0],
    )
    await repository.initialize()
    store = LocalAssetStore(tmp_path / "data")
    source = b"recorded-video"
    asset = Asset(
        asset_id="asset-1",
        display_filename="yard.mp4",
        safe_filename="yard.mp4",
        size_bytes=len(source),
        sha256=hashlib.sha256(source).hexdigest(),
        mime_type="video/mp4",
        source_extension="mp4",
        timeline_origin=NOW,
        status=AssetStatus.UPLOADING,
        created_at=NOW,
        updated_at=NOW,
    )
    session = UploadSession(
        session_id="session-1",
        identifier="upload-1",
        asset_id=asset.asset_id,
        total_chunks=1,
        filename=asset.display_filename,
        temp_dir="ignored",
        status=AssetStatus.UPLOADING,
        expires_at=NOW + timedelta(days=1),
    )
    await repository.create_upload_session(asset, session)
    await repository.record_chunk(session.session_id, 1, "chunk", size_bytes=len(source), path="000001.part")
    await repository.complete_upload(asset.asset_id, pipeline_version, now=NOW)
    await store.write_atomic("assets/asset-1/source/original.mp4", source)
    claimed = await repository.claim_due_job(owner, clock[0])
    assert claimed is not None
    return repository, store, claimed


def _pipeline(
    repository: JobRepository,
    store: LocalAssetStore,
    *,
    media: FakeMediaProcessor | None = None,
    vision: FakeVisionProvider | None = None,
    embedding: FakeEmbeddingProvider | None = None,
    projection: FakeProjectionStore | None = None,
    clock: list[datetime] | None = None,
) -> RecordedVideoPipeline:
    return RecordedVideoPipeline(
        repository=repository,
        asset_store=store,
        media=media or FakeMediaProcessor(),
        segmenter=FixedDurationSegmenter(10),
        vision=vision or FakeVisionProvider(),
        embedding=embedding or FakeEmbeddingProvider(),
        projection=projection or FakeProjectionStore(),
        expected_embedding_dims=3,
        representative_frames=2,
        prompt_version="prompt-v1",
        segmenter_version="fixed-10s-v1",
        clock=(lambda: clock[0]) if clock is not None else (lambda: NOW),
    )


@pytest.mark.asyncio
async def test_valid_analysis_checkpoint_skips_second_vision_call(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    vision = FakeVisionProvider()
    embedding = FakeEmbeddingProvider(failures=1)
    projection = FakeProjectionStore()
    pipeline = _pipeline(
        repository,
        store,
        vision=vision,
        embedding=embedding,
        projection=projection,
        clock=clock,
    )

    with pytest.raises(RuntimeError, match="temporary embedding failure"):
        await pipeline.run(job)

    clock[0] += timedelta(seconds=31)
    reclaimed_job = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed_job is not None
    result = await pipeline.run(reclaimed_job)

    assert len(vision.calls) == 1
    assert len(embedding.calls) == 2
    assert result.status is JobStatus.COMPLETED
    assert (await repository.get_job(job.job_id)).status is JobStatus.COMPLETED
    assert [asset.asset_id for asset in await repository.list_ready_assets()] == ["asset-1"]
    assert len(projection.calls) == 1


@pytest.mark.asyncio
async def test_manifest_records_versions_checksums_and_deterministic_projection(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    projection = FakeProjectionStore()

    result = await _pipeline(repository, store, projection=projection, clock=clock).run(job)

    manifest_path = Path(result.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path == store.root / "assets/asset-1/derived/pipeline-v1/manifest.json"
    assert manifest["pipeline_version"] == "pipeline-v1"
    assert manifest["versions"] == {
        "embedding_model": "embedding-model-v1",
        "prompt": "prompt-v1",
        "segmenter": "fixed-10s-v1",
        "vision_model": "vision-model-v1",
    }
    assert set(manifest["stages"]) == {stage.value for stage in JobStage}
    assert all(stage["input_sha256"] and stage["output_sha256"] for stage in manifest["stages"].values())
    assert all(stage["started_at"].endswith("+00:00") for stage in manifest["stages"].values())
    serialized = manifest_path.read_text(encoding="utf-8")
    assert "secret-must-not-leak" not in serialized
    assert not list(manifest_path.parent.glob("*.tmp"))

    documents = projection.calls[0]
    segments = await repository.list_segments("asset-1")
    assert [document["_id"] for document in documents] == [segment.segment_id for segment in segments]
    assert all(document["_id"] == document["segment_id"] for document in documents)
    assert result.projected_ids == tuple(document["_id"] for document in documents)
    assert [step.stage for step in await repository.list_job_steps(job.job_id)] == list(JobStage)


@pytest.mark.asyncio
async def test_corrupt_analysis_checkpoint_is_not_reused(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    vision = FakeVisionProvider()
    embedding = FakeEmbeddingProvider(failures=1)
    pipeline = _pipeline(repository, store, vision=vision, embedding=embedding, clock=clock)

    with pytest.raises(RuntimeError, match="temporary embedding failure"):
        await pipeline.run(job)
    manifest_path = store.root / "assets/asset-1/derived/pipeline-v1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stages"]["analyzing"]["output"]["segments"][0]["description"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert load_verified_checkpoint(manifest_path, JobStage.ANALYZING) is None

    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed is not None
    await pipeline.run(reclaimed)

    assert len(vision.calls) == 2


@pytest.mark.asyncio
async def test_projection_failure_does_not_publish_completed_state(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    pipeline = _pipeline(repository, store, projection=FakeProjectionStore(fail=True), clock=clock)

    with pytest.raises(RuntimeError, match="projection unavailable"):
        await pipeline.run(job)

    persisted_job = await repository.get_job(job.job_id)
    assert persisted_job.status is JobStatus.RUNNING
    assert await repository.list_ready_assets() == []
    assert await repository.list_segments(job.asset_id) == []
    steps = await repository.list_job_steps(job.job_id)
    assert [step.stage for step in steps] == list(JobStage)[:-1]


@pytest.mark.asyncio
async def test_changed_provider_version_invalidates_analysis_checkpoint(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    first_vision = FakeVisionProvider()
    pipeline = _pipeline(
        repository,
        store,
        vision=first_vision,
        embedding=FakeEmbeddingProvider(failures=1),
        clock=clock,
    )
    with pytest.raises(RuntimeError, match="temporary embedding failure"):
        await pipeline.run(job)

    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed is not None
    changed_vision = FakeVisionProvider()
    changed_vision.model = "vision-model-v2"
    await _pipeline(repository, store, vision=changed_vision, clock=clock).run(reclaimed)

    assert len(first_vision.calls) == 1
    assert len(changed_vision.calls) == 1


@pytest.mark.asyncio
async def test_unsafe_pipeline_version_is_rejected_before_media_access(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(
        tmp_path,
        clock,
        pipeline_version="../../../../outside",
    )
    media = FakeMediaProcessor()

    with pytest.raises(RecordedVideoError) as failure:
        await _pipeline(repository, store, media=media, clock=clock).run(job)

    assert failure.value.code is ErrorCode.CONFIGURATION
    assert media.probe_calls == 0


@pytest.mark.asyncio
async def test_cancel_requested_during_projection_prevents_publish(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class CancellingProjectionStore(FakeProjectionStore):
        async def project(self, documents: list[dict[str, Any]]) -> ProjectionResult:
            await repository.request_cancel(job.job_id, clock[0] + timedelta(seconds=1))
            return await super().project(documents)

    with pytest.raises(PermissionError, match="cancellation requested"):
        await _pipeline(
            repository,
            store,
            projection=CancellingProjectionStore(),
            clock=clock,
        ).run(job)

    assert (await repository.get_job(job.job_id)).status is JobStatus.RUNNING
    assert await repository.list_ready_assets() == []
    assert await repository.list_segments(job.asset_id) == []
