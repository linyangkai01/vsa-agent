from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from vsa_agent.recorded_video.models import Asset, Job, JobStep, Segment, UploadSession
from vsa_agent.recorded_video.ports import (
    AssetStore,
    EmbeddingProvider,
    JobRepository,
    ProjectionResult,
    SearchProjectionStore,
    Segmenter,
    VisionProvider,
)


class FakeAssetStore:
    async def write_chunk(self, session: UploadSession, ordinal: int, data: bytes) -> str:
        return f"{session.session_id}/{ordinal}"

    async def assemble_source(self, session: UploadSession, asset: Asset) -> str:
        return asset.asset_id


class FakeJobRepository:
    async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
        return None

    async def checkpoint_step(self, job: Job, step: JobStep) -> None:
        return None


class FakeSegmenter:
    async def plan(self, asset: Asset, pipeline_version: str) -> Sequence[Segment]:
        return []


class FakeVisionProvider:
    async def describe(self, segment: Segment, frame_keys: Sequence[str]) -> str:
        return "description"


class FakeEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return []


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


def test_projection_result_keeps_successes_and_failures_separate() -> None:
    result = ProjectionResult(indexed_ids=["segment-1"], failed_ids=["segment-2"])

    assert result.indexed_ids == ["segment-1"]
    assert result.failed_ids == ["segment-2"]


def test_claim_due_job_accepts_owner_and_explicit_clock() -> None:
    repository = FakeJobRepository()
    now = datetime(2026, 7, 12, 8, 30, tzinfo=UTC)

    assert asyncio.run(repository.claim_due_job(owner="worker-1", now=now)) is None
    assert (
        asyncio.run(JobRepository.claim_due_job(repository, owner="worker-1", now=now))
        is None
    )
