"""Replaceable ports for recorded-video ingestion infrastructure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from vsa_agent.recorded_video.models import Asset, Job, JobStep, Segment, UploadSession


class ProjectionResult(BaseModel):
    indexed_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)


@runtime_checkable
class AssetStore(Protocol):
    async def write_chunk(self, session: UploadSession, ordinal: int, data: bytes) -> str: ...

    async def assemble_source(self, session: UploadSession, asset: Asset) -> str: ...


@runtime_checkable
class JobRepository(Protocol):
    async def claim_due_job(self, owner: str, now: datetime) -> Job | None: ...

    async def checkpoint_step(self, job: Job, step: JobStep) -> None: ...


@runtime_checkable
class Segmenter(Protocol):
    async def plan(self, asset: Asset, pipeline_version: str) -> Sequence[Segment]: ...


@runtime_checkable
class VisionProvider(Protocol):
    async def describe(self, segment: Segment, frame_keys: Sequence[str]) -> str: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@runtime_checkable
class SearchProjectionStore(Protocol):
    async def project(self, documents: Sequence[Mapping[str, Any]]) -> ProjectionResult: ...

    async def delete_asset(self, asset_id: str) -> None: ...
