from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_type_hints

from vsa_agent.recorded_video.models import Asset, Job, JobStage, JobStep, Segment, UploadSession
from vsa_agent.recorded_video.ports import (
    AssetStore,
    Embedding,
    EmbeddingProvider,
    JobRepository,
    ProjectionResult,
    SearchProjectionStore,
    Segmenter,
    VisionDescription,
    VisionProvider,
)


class FakeAssetStore:
    root = Path(".")

    async def write_chunk(self, session: UploadSession, ordinal: int, data: bytes) -> str:
        return f"{session.session_id}/{ordinal}"

    async def assemble_source(self, session: UploadSession, asset: Asset) -> str:
        return asset.asset_id

    async def write_atomic(self, destination: str | Path, data: bytes) -> str:
        del data
        return str(destination)

    async def resolve_source_path(self, asset: Asset) -> Path:
        return Path(asset.asset_id)


class FakeJobRepository:
    async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
        return None

    async def checkpoint_step(self, job: Job, step: JobStep) -> None:
        return None

    async def get_asset(self, asset_id: str) -> Asset:
        raise KeyError(asset_id)

    async def list_job_steps(self, job_id: str) -> list[JobStep]:
        return []

    async def start_pipeline(self, job: Job) -> None:
        return None

    async def reset_steps_from(self, job: Job, stage: JobStage) -> None:
        return None

    async def complete_pipeline(
        self,
        job: Job,
        asset: Asset,
        segments: Sequence[Segment],
        step: JobStep,
    ) -> Job:
        return job


class FakeSegmenter:
    async def plan(self, asset: Asset, pipeline_version: str) -> Sequence[Segment]:
        return []


class FakeVisionProvider:
    model = "vision-model"

    async def describe(
        self,
        frame_keys: Sequence[str | Path],
        segment: Segment,
        *,
        job_id: str,
    ) -> VisionDescription:
        return VisionDescription(description="description", tags=())


class FakeEmbeddingProvider:
    model = "embedding-model"

    async def embed(
        self,
        text: str,
        *,
        expected_dims: int,
        asset_id: str,
        job_id: str,
    ) -> Embedding:
        return (0.1,) * expected_dims


class FakeProjectionStore:
    async def project(self, documents: Sequence[Mapping[str, Any]]) -> ProjectionResult:
        return ProjectionResult(indexed_ids=[], failed_ids=[])

    async def delete_asset(self, asset_id: str) -> None:
        return None


def test_all_ports_are_runtime_checkable_structural_protocols() -> None:
    assert isinstance(FakeAssetStore(), AssetStore)
    assert isinstance(FakeJobRepository(), JobRepository)
    assert isinstance(FakeSegmenter(), Segmenter)
    assert isinstance(FakeVisionProvider(), VisionProvider)
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(FakeProjectionStore(), SearchProjectionStore)


def test_model_provider_ports_match_pipeline_contract() -> None:
    vision = inspect.signature(VisionProvider.describe)
    assert list(vision.parameters) == ["self", "frame_keys", "segment", "job_id"]
    assert vision.parameters["job_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(VisionProvider.describe)["return"] is VisionDescription

    embedding = inspect.signature(EmbeddingProvider.embed)
    assert list(embedding.parameters) == [
        "self",
        "text",
        "expected_dims",
        "asset_id",
        "job_id",
    ]
    for name in ("expected_dims", "asset_id", "job_id"):
        assert embedding.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(EmbeddingProvider.embed)["return"] == Embedding


def test_projection_result_keeps_successes_and_failures_separate() -> None:
    result = ProjectionResult(indexed_ids=["segment-1"], failed_ids=["segment-2"])

    assert result.indexed_ids == ["segment-1"]
    assert result.failed_ids == ["segment-2"]


def test_claim_due_job_accepts_owner_and_explicit_clock() -> None:
    repository = FakeJobRepository()
    now = datetime(2026, 7, 12, 8, 30, tzinfo=UTC)

    assert asyncio.run(repository.claim_due_job(owner="worker-1", now=now)) is None
    assert asyncio.run(JobRepository.claim_due_job(repository, owner="worker-1", now=now)) is None


def test_claim_due_job_documents_timezone_aware_clock_contract() -> None:
    docstring = inspect.getdoc(JobRepository.claim_due_job)

    assert docstring is not None
    assert "timezone-aware" in docstring
