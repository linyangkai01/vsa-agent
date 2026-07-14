from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

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
        assert Path(path).is_file()
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
        assert Path(source_path).is_file()
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

    def __init__(self, *, endpoint: str = "https://vision.example/v1") -> None:
        self.calls: list[tuple[list[str], str, str]] = []
        self.api_key = "vision-secret-must-not-leak"
        self.checkpoint_identity = {
            "provider": "fake-openai-vision",
            "endpoint": endpoint,
            "model": self.model,
        }

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

    def __init__(self, *, failures: int = 0, vector: tuple[float, ...] | None = None) -> None:
        self.failures = failures
        self.calls: list[str] = []
        self.api_key = "embedding-secret-must-not-leak"
        self.vector = vector
        self.expected_dims: list[int] = []
        self.checkpoint_identity = {
            "provider": "fake-openai-embedding",
            "endpoint": "https://embedding.example/v1",
            "model": self.model,
        }

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
        self.expected_dims.append(expected_dims)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary embedding failure")
        if self.vector is not None:
            return self.vector
        return tuple(0.1 + ordinal / 10 for ordinal in range(expected_dims))


class FakeProjectionStore:
    def __init__(self, *, fail: bool = False, partial: bool = False) -> None:
        self.fail = fail
        self.partial = partial
        self.calls: list[list[dict[str, Any]]] = []
        self.deleted_assets: list[str] = []
        self.deleted_projections: list[tuple[str, str, int]] = []
        self.documents: dict[str, dict[str, Any]] = {}

    async def project(
        self,
        documents: list[dict[str, Any]],
        *,
        job_id: str | None = None,
        attempt: int | None = None,
    ) -> ProjectionResult:
        self.calls.append(documents)
        if documents:
            job_id = job_id or str(documents[0]["job_id"])
            attempt = attempt or int(documents[0]["job_attempt"])
        assert job_id is not None and attempt is not None
        if self.fail:
            raise RuntimeError("projection unavailable")
        if self.partial:
            return ProjectionResult(
                indexed_ids=[],
                failed_ids=[str(document["_id"]) for document in documents],
            )
        indexed_ids: list[str] = []
        failed_ids: list[str] = []
        for document in documents:
            document_id = str(document["_id"])
            current = self.documents.get(document_id)
            if current is not None and current["job_id"] == job_id and current["job_attempt"] > attempt:
                failed_ids.append(document_id)
                continue
            self.documents[document_id] = dict(document)
            indexed_ids.append(document_id)
        return ProjectionResult(indexed_ids=indexed_ids, failed_ids=failed_ids)

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        self.deleted_projections.append((asset_id, job_id, attempt))
        self.documents = {
            document_id: document
            for document_id, document in self.documents.items()
            if not (
                document["asset_id"] == asset_id and document["job_id"] == job_id and document["job_attempt"] == attempt
            )
        }

    async def delete_asset(self, asset_id: str) -> None:
        self.deleted_assets.append(asset_id)
        self.documents = {
            document_id: document
            for document_id, document in self.documents.items()
            if document["asset_id"] != asset_id
        }


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
    segmenter: FixedDurationSegmenter | None = None,
    expected_embedding_dims: int = 3,
    representative_frames: int = 2,
    segmenter_version: str = "fixed-10s-v1",
    clock: list[datetime] | None = None,
) -> RecordedVideoPipeline:
    return RecordedVideoPipeline(
        repository=repository,
        asset_store=store,
        media=media or FakeMediaProcessor(),
        segmenter=segmenter or FixedDurationSegmenter(10),
        vision=vision or FakeVisionProvider(),
        embedding=embedding or FakeEmbeddingProvider(),
        projection=projection or FakeProjectionStore(),
        expected_embedding_dims=expected_embedding_dims,
        representative_frames=representative_frames,
        prompt_version="prompt-v1",
        segmenter_version=segmenter_version,
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
    assert manifest_path == store.root / "assets/asset-1/derived/pipeline-v1/attempts/1/manifest.json"
    assert manifest["pipeline_version"] == "pipeline-v1"
    assert manifest["checkpoint_identity"] == {
        "embedding": {
            "endpoint": "https://embedding.example/v1",
            "model": "embedding-model-v1",
            "provider": "fake-openai-embedding",
        },
        "expected_embedding_dims": 3,
        "prompt_version": "prompt-v1",
        "representative_frames": 2,
        "segmenter": {
            "config": {"duration_ms": 10_000, "type": "fixed-duration"},
            "version": "fixed-10s-v1",
        },
        "vision": {
            "endpoint": "https://vision.example/v1",
            "model": "vision-model-v1",
            "provider": "fake-openai-vision",
        },
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
    assert all(document["job_id"] == job.job_id for document in documents)
    assert all(document["job_attempt"] == job.attempt for document in documents)
    assert all(
        document["readiness"]
        == {
            "asset_id": job.asset_id,
            "job_id": job.job_id,
            "pipeline_version": job.pipeline_version,
            "attempt": job.attempt,
            "authority": "sqlite",
        }
        for document in documents
    )
    assert not await repository.is_asset_search_ready(
        job.asset_id,
        job.job_id,
        job.pipeline_version,
        job.attempt + 1,
    )
    assert await repository.is_asset_search_ready(
        job.asset_id,
        job.job_id,
        job.pipeline_version,
        job.attempt,
    )
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
    manifest_path = store.root / "assets/asset-1/derived/pipeline-v1/attempts/1/manifest.json"
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
    projection = FakeProjectionStore(fail=True)
    pipeline = _pipeline(repository, store, projection=projection, clock=clock)

    with pytest.raises(RuntimeError, match="projection unavailable"):
        await pipeline.run(job)

    persisted_job = await repository.get_job(job.job_id)
    assert persisted_job.status is JobStatus.RUNNING
    assert await repository.list_ready_assets() == []
    assert await repository.list_segments(job.asset_id) == []
    steps = await repository.list_job_steps(job.job_id)
    assert [step.stage for step in steps] == list(JobStage)[:-1]
    assert projection.deleted_projections == [(job.asset_id, job.job_id, job.attempt)]


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
        async def project(self, documents, *, job_id=None, attempt=None) -> ProjectionResult:
            await repository.request_cancel(job.job_id, clock[0] + timedelta(seconds=1))
            return await super().project(documents, job_id=job_id, attempt=attempt)

    projection = CancellingProjectionStore()
    with pytest.raises(PermissionError, match="cancellation requested"):
        await _pipeline(
            repository,
            store,
            projection=projection,
            clock=clock,
        ).run(job)

    assert (await repository.get_job(job.job_id)).status is JobStatus.RUNNING
    assert await repository.list_ready_assets() == []
    assert await repository.list_segments(job.asset_id) == []
    assert projection.deleted_projections == [(job.asset_id, job.job_id, job.attempt)]


@pytest.mark.asyncio
async def test_stale_worker_cannot_write_manifest_after_provider_await(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class ReclaimingVision(FakeVisionProvider):
        async def describe(self, frame_keys, segment, *, job_id):
            result = await super().describe(frame_keys, segment, job_id=job_id)
            clock[0] += timedelta(seconds=31)
            reclaimed = await repository.claim_due_job("worker-2", clock[0])
            assert reclaimed is not None and reclaimed.attempt == 2
            return result

    with pytest.raises(PermissionError, match="active lease"):
        await _pipeline(repository, store, vision=ReclaimingVision(), clock=clock).run(job)

    manifest_path = store.root / "assets/asset-1/derived/pipeline-v1/attempts/1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert JobStage.ANALYZING.value not in manifest["stages"]


@pytest.mark.asyncio
async def test_partial_projection_is_compensated_and_never_ready(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    projection = FakeProjectionStore(partial=True)

    with pytest.raises(RecordedVideoError) as failure:
        await _pipeline(repository, store, projection=projection, clock=clock).run(job)

    assert failure.value.code is ErrorCode.ES_5XX
    assert projection.deleted_projections == [(job.asset_id, job.job_id, job.attempt)]
    assert not await repository.is_asset_search_ready(
        job.asset_id,
        job.job_id,
        job.pipeline_version,
        job.attempt,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [(0.1, 0.2), (0.1, math.nan, 0.3)])
async def test_projection_rejects_invalid_embedding_manifest(
    tmp_path: Path,
    vector: tuple[float, ...],
) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    projection = FakeProjectionStore()

    with pytest.raises(RecordedVideoError) as failure:
        await _pipeline(
            repository,
            store,
            embedding=FakeEmbeddingProvider(vector=vector),
            projection=projection,
            clock=clock,
        ).run(job)

    assert failure.value.code is ErrorCode.EMBEDDING_DIMENSION
    assert projection.calls == []


@pytest.mark.asyncio
async def test_projection_rejects_non_deterministic_segment_identity(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class InvalidSegmenter(FixedDurationSegmenter):
        checkpoint_identity: ClassVar[dict[str, Any]] = {"type": "invalid-test"}

        async def plan(self, asset, pipeline_version):
            segments = list(await super().plan(asset, pipeline_version))
            return [segments[0].model_copy(update={"segment_id": "not-deterministic"})]

    projection = FakeProjectionStore()
    with pytest.raises(RecordedVideoError, match="segment"):
        await _pipeline(
            repository,
            store,
            segmenter=InvalidSegmenter(10),
            projection=projection,
            clock=clock,
        ).run(job)

    assert projection.calls == []


@pytest.mark.asyncio
async def test_representative_frame_tamper_invalidates_checkpoint_reuse(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    media = FakeMediaProcessor()
    pipeline = _pipeline(
        repository,
        store,
        media=media,
        embedding=FakeEmbeddingProvider(failures=1),
        clock=clock,
    )
    with pytest.raises(RuntimeError, match="temporary embedding failure"):
        await pipeline.run(job)
    frame = next((store.root / "assets/asset-1/derived/pipeline-v1/attempts/1/frames").glob("*.jpg"))
    frame.write_bytes(b"tampered-frame")

    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed is not None
    await pipeline.run(reclaimed)

    assert media.extract_calls == 2


@pytest.mark.asyncio
async def test_checkpoint_identity_includes_runtime_frame_and_segmenter_config(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    first_media = FakeMediaProcessor()
    first_projection = FakeProjectionStore(fail=True)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        await _pipeline(
            repository,
            store,
            media=first_media,
            projection=first_projection,
            clock=clock,
        ).run(job)

    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed is not None
    second_media = FakeMediaProcessor()
    projection = FakeProjectionStore()
    await _pipeline(
        repository,
        store,
        media=second_media,
        segmenter=FixedDurationSegmenter(2),
        representative_frames=3,
        projection=projection,
        clock=clock,
    ).run(reclaimed)

    assert second_media.extract_calls == 3
    assert len(projection.calls[0]) == 3


@pytest.mark.asyncio
async def test_checkpoint_identity_includes_expected_embedding_dimensions(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        await _pipeline(
            repository,
            store,
            projection=FakeProjectionStore(fail=True),
            clock=clock,
        ).run(job)

    clock[0] += timedelta(seconds=31)
    reclaimed = await repository.claim_due_job("worker-2", clock[0])
    assert reclaimed is not None
    embedding = FakeEmbeddingProvider()
    await _pipeline(
        repository,
        store,
        embedding=embedding,
        expected_embedding_dims=4,
        clock=clock,
    ).run(reclaimed)

    assert embedding.expected_dims == [4]


@pytest.mark.asyncio
async def test_source_and_artifact_hashing_never_uses_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)
    original_read_bytes = Path.read_bytes

    def reject_large_artifact_reads(path: Path) -> bytes:
        if path.name == "original.mp4" or path.suffix == ".jpg":
            raise AssertionError("pipeline hashing must stream files")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_large_artifact_reads)

    result = await _pipeline(repository, store, clock=clock).run(job)

    assert result.status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_overlapping_stale_attempt_cannot_overwrite_or_delete_newer_projection(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    repository, store, first_job = await _claimed_job(tmp_path, clock)

    class BlockingProjectionStore(FakeProjectionStore):
        def __init__(self) -> None:
            super().__init__()
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def project(self, documents, *, job_id=None, attempt=None) -> ProjectionResult:
            attempt = attempt or int(documents[0]["job_attempt"])
            if attempt == 1:
                self.first_started.set()
                await self.release_first.wait()
            return await super().project(documents, job_id=job_id, attempt=attempt)

    projection = BlockingProjectionStore()
    first_run = asyncio.create_task(_pipeline(repository, store, projection=projection, clock=clock).run(first_job))
    await projection.first_started.wait()

    clock[0] += timedelta(seconds=31)
    second_job = await repository.claim_due_job("worker-2", clock[0])
    assert second_job is not None and second_job.attempt == 2
    second_result = await _pipeline(
        repository,
        store,
        projection=projection,
        clock=clock,
    ).run(second_job)

    projection.release_first.set()
    with pytest.raises(PermissionError, match="active lease"):
        await first_run

    assert second_result.status is JobStatus.COMPLETED
    assert projection.documents
    assert all(document["job_attempt"] == 2 for document in projection.documents.values())
    assert projection.deleted_projections == [(first_job.asset_id, first_job.job_id, 1)]


@pytest.mark.asyncio
async def test_reclaim_after_first_vision_segment_stops_later_provider_calls(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class ReclaimingVision(FakeVisionProvider):
        async def describe(self, frame_keys, segment, *, job_id):
            result = await super().describe(frame_keys, segment, job_id=job_id)
            if len(self.calls) == 1:
                clock[0] += timedelta(seconds=31)
                reclaimed = await repository.claim_due_job("worker-2", clock[0])
                assert reclaimed is not None and reclaimed.attempt == 2
            return result

    vision = ReclaimingVision()
    with pytest.raises(PermissionError, match="active lease"):
        await _pipeline(
            repository,
            store,
            vision=vision,
            segmenter=FixedDurationSegmenter(2),
            clock=clock,
        ).run(job)

    assert len(vision.calls) == 1


@pytest.mark.asyncio
async def test_cancel_after_first_embedding_segment_stops_later_provider_calls(tmp_path: Path) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class CancellingEmbedding(FakeEmbeddingProvider):
        async def embed(self, text, *, expected_dims, asset_id, job_id):
            vector = await super().embed(
                text,
                expected_dims=expected_dims,
                asset_id=asset_id,
                job_id=job_id,
            )
            if len(self.calls) == 1:
                await repository.request_cancel(job.job_id, clock[0] + timedelta(seconds=1))
            return vector

    embedding = CancellingEmbedding()
    with pytest.raises(PermissionError, match="cancellation requested"):
        await _pipeline(
            repository,
            store,
            embedding=embedding,
            segmenter=FixedDurationSegmenter(2),
            clock=clock,
        ).run(job)

    assert len(embedding.calls) == 1


@pytest.mark.asyncio
async def test_publish_timing_spans_projection_and_records_elapsed_time(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    repository, store, job = await _claimed_job(tmp_path, clock)

    class AdvancingProjectionStore(FakeProjectionStore):
        async def project(self, documents, *, job_id=None, attempt=None) -> ProjectionResult:
            await asyncio.sleep(0.02)
            clock[0] += timedelta(seconds=2)
            return await super().project(documents, job_id=job_id, attempt=attempt)

    result = await _pipeline(
        repository,
        store,
        projection=AdvancingProjectionStore(),
        clock=clock,
    ).run(job)

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    publish = manifest["stages"][JobStage.PUBLISH.value]
    assert publish["started_at"] == NOW.isoformat()
    assert publish["completed_at"] == (NOW + timedelta(seconds=2)).isoformat()
    assert publish["elapsed_ms"] >= 10
