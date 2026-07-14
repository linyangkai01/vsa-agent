"""Replaceable ports for recorded-video ingestion infrastructure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vsa_agent.recorded_video.models import Asset, Job, JobStep, Segment, UploadSession

Embedding = tuple[float, ...]


class VisionDescription(BaseModel):
    """Validated structured output returned by a vision provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    tags: tuple[str, ...]

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("tags must not contain blank values")
            normalized.append(value)
        return tuple(normalized)


class ProjectionResult(BaseModel):
    indexed_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)


@runtime_checkable
class AssetStore(Protocol):
    async def write_chunk(self, session: UploadSession, ordinal: int, data: bytes) -> str: ...

    async def assemble_source(self, session: UploadSession, asset: Asset) -> str: ...


@runtime_checkable
class JobRepository(Protocol):
    async def claim_due_job(self, owner: str, now: datetime) -> Job | None:
        """Claim a due job using the caller's timezone-aware ``now`` clock."""
        ...

    async def checkpoint_step(self, job: Job, step: JobStep) -> None: ...


@runtime_checkable
class Segmenter(Protocol):
    async def plan(self, asset: Asset, pipeline_version: str) -> Sequence[Segment]: ...


@runtime_checkable
class VisionProvider(Protocol):
    async def describe(
        self,
        frame_keys: Sequence[str | Path],
        segment: Segment,
        *,
        job_id: str,
    ) -> VisionDescription: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(
        self,
        text: str,
        *,
        expected_dims: int,
        asset_id: str,
        job_id: str,
    ) -> Embedding: ...


@runtime_checkable
class SearchProjectionStore(Protocol):
    async def project(self, documents: Sequence[Mapping[str, Any]]) -> ProjectionResult: ...

    async def delete_asset(self, asset_id: str) -> None: ...
