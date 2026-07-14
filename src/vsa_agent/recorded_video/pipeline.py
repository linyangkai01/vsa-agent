"""Checkpointed orchestration for recorded-video processing."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.media import MediaProbe
from vsa_agent.recorded_video.models import Asset, Job, JobStage, JobStatus, JobStep, Segment
from vsa_agent.recorded_video.ports import (
    AssetStore,
    EmbeddingProvider,
    JobRepository,
    SearchProjectionStore,
    Segmenter,
    VisionProvider,
)

_MANIFEST_SCHEMA_VERSION = 1
_STAGE_ORDER = {stage: ordinal for ordinal, stage in enumerate(JobStage)}


class MediaPipelineProcessor(Protocol):
    async def probe(self, path: str | Path) -> MediaProbe: ...

    async def extract_representative_frames(
        self,
        source_path: str | Path,
        segment: Segment,
        destination_dir: str | Path,
        *,
        frame_count: int,
    ) -> list[Path]: ...


class PipelineResult(BaseModel):
    """Durable result returned after the publish transaction succeeds."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    asset_id: str
    status: JobStatus
    manifest_path: str
    manifest_checksum: str
    segment_count: int
    projected_ids: tuple[str, ...]


def load_verified_checkpoint(
    path: str | Path,
    stage: JobStage | str,
    *,
    expected_input_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Return a stage output only when inline and file checksums are valid."""
    manifest_path = Path(path)
    try:
        stage_name = JobStage(stage).value
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["stages"][stage_name]
        output = entry["output"]
        if not isinstance(entry, dict) or not isinstance(output, dict):
            return None
        if expected_input_sha256 is not None and entry.get("input_sha256") != expected_input_sha256:
            return None
        if entry.get("output_sha256") != _sha256_json(output):
            return None
        artifacts = output.get("artifacts", {})
        if not isinstance(artifacts, dict):
            return None
        derived_root = manifest_path.parent.resolve()
        for key, checksum in artifacts.items():
            if not isinstance(key, str) or not isinstance(checksum, str):
                return None
            artifact = (derived_root / key).resolve()
            if not artifact.is_relative_to(derived_root) or not artifact.is_file():
                return None
            if _sha256_bytes(artifact.read_bytes()) != checksum:
                return None
        return output
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


class RecordedVideoPipeline:
    """Run all processing stages for one repository-fenced job attempt."""

    def __init__(
        self,
        *,
        repository: JobRepository,
        asset_store: AssetStore,
        media: MediaPipelineProcessor,
        segmenter: Segmenter,
        vision: VisionProvider,
        embedding: EmbeddingProvider,
        projection: SearchProjectionStore,
        expected_embedding_dims: int,
        representative_frames: int,
        prompt_version: str,
        segmenter_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if expected_embedding_dims <= 0:
            raise ValueError("expected_embedding_dims must be positive")
        if not 1 <= representative_frames <= 16:
            raise ValueError("representative_frames must be within 1..16")
        if not prompt_version.strip() or not segmenter_version.strip():
            raise ValueError("pipeline version identifiers must not be blank")
        self._repository = repository
        self._asset_store = asset_store
        self._media = media
        self._segmenter = segmenter
        self._vision = vision
        self._embedding = embedding
        self._projection = projection
        self._expected_embedding_dims = expected_embedding_dims
        self._representative_frames = representative_frames
        self._prompt_version = prompt_version
        self._segmenter_version = segmenter_version
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, job: Job) -> PipelineResult:
        """Process or resume one actively leased job through atomic publication."""
        if job.status is not JobStatus.RUNNING or job.lease_owner is None:
            raise PermissionError("pipeline requires an actively leased running job")
        _safe_path_component(job.asset_id, "asset_id")
        _safe_path_component(job.pipeline_version, "pipeline_version")
        await self._repository.start_pipeline(job)
        asset = await self._repository.get_asset(job.asset_id)
        manifest_relative = f"assets/{asset.asset_id}/derived/{job.pipeline_version}/manifest.json"
        asset_root = self._asset_store.root.resolve()
        manifest_path = (asset_root / manifest_relative).resolve()
        if not manifest_path.is_relative_to(asset_root):
            raise RecordedVideoError(
                ErrorCode.CONFIGURATION,
                retryable=False,
                message="CONFIGURATION: manifest path escaped the asset store",
            )
        manifest = self._load_manifest(manifest_path, asset, job)
        stored_steps = {step.stage: step for step in await self._repository.list_job_steps(job.job_id)}
        source_path = await self._asset_store.resolve_source_path(asset)
        if _sha256_bytes(source_path.read_bytes()) != asset.sha256:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message="CORRUPT_MEDIA: source checksum does not match the uploaded asset",
            )

        async def run_stage(
            stage: JobStage,
            input_sha256: str,
            operation: Callable[[], Awaitable[dict[str, Any]]],
            *,
            model: str | None = None,
        ) -> tuple[dict[str, Any], str]:
            nonlocal manifest, stored_steps
            verified = load_verified_checkpoint(
                manifest_path,
                stage,
                expected_input_sha256=input_sha256,
            )
            stored = stored_steps.get(stage)
            entry = manifest.get("stages", {}).get(stage.value, {})
            output_checksum = entry.get("output_sha256") if isinstance(entry, dict) else None
            checkpoint_matches = stored is None or (
                stored.status is JobStatus.COMPLETED
                and stored.output_checksum == output_checksum
                and stored.output_manifest == _manifest_key(job.pipeline_version)
            )
            if verified is not None and checkpoint_matches and isinstance(output_checksum, str):
                if stored is None:
                    step = self._step(job, stage, output_checksum, entry, model=model)
                    await self._repository.checkpoint_step(job, step)
                    stored_steps[stage] = step
                return verified, output_checksum

            if stored is not None or stage.value in manifest.get("stages", {}):
                await self._repository.reset_steps_from(job, stage)
                stored_steps = {
                    candidate: step
                    for candidate, step in stored_steps.items()
                    if _STAGE_ORDER[candidate] < _STAGE_ORDER[stage]
                }
                manifest["stages"] = {
                    name: value
                    for name, value in manifest.get("stages", {}).items()
                    if _STAGE_ORDER[JobStage(name)] < _STAGE_ORDER[stage]
                }
                await self._write_manifest(manifest_relative, manifest)

            started_at = self._now()
            monotonic_start = time.monotonic()
            output = await operation()
            completed_at = self._now()
            output_checksum = _sha256_json(output)
            entry = {
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "elapsed_ms": max(0, round((time.monotonic() - monotonic_start) * 1_000)),
                "input_sha256": input_sha256,
                "output_sha256": output_checksum,
                "output": output,
            }
            manifest["stages"][stage.value] = entry
            await self._write_manifest(manifest_relative, manifest)
            step = self._step(job, stage, output_checksum, entry, model=model)
            await self._repository.checkpoint_step(job, step)
            stored_steps[stage] = step
            return output, output_checksum

        probe_output, probe_sha = await run_stage(
            JobStage.PROBING,
            asset.sha256,
            lambda: self._probe(source_path),
        )
        probed_asset = asset.model_copy(
            update={
                "duration_ms": probe_output["duration_ms"],
                "width": probe_output["width"],
                "height": probe_output["height"],
            }
        )
        segment_output, segment_sha = await run_stage(
            JobStage.SEGMENTING,
            probe_sha,
            lambda: self._segment(probed_asset, job.pipeline_version),
            model=self._segmenter_version,
        )
        segments = [Segment.model_validate(payload) for payload in segment_output["segments"]]
        extraction_output, extraction_sha = await run_stage(
            JobStage.EXTRACTING,
            segment_sha,
            lambda: self._extract(source_path, segments, manifest_path.parent, job.pipeline_version),
        )
        analysis_output, analysis_sha = await run_stage(
            JobStage.ANALYZING,
            extraction_sha,
            lambda: self._analyze(job, segments, extraction_output, manifest_path.parent),
            model=self._vision.model,
        )
        embedding_output, embedding_sha = await run_stage(
            JobStage.EMBEDDING,
            analysis_sha,
            lambda: self._embed(job, analysis_output),
            model=self._embedding.model,
        )
        completed_segments = self._completed_segments(segments, extraction_output, analysis_output)
        indexing_output, indexing_sha = await run_stage(
            JobStage.INDEXING,
            embedding_sha,
            lambda: self._index_documents(asset, completed_segments, embedding_output),
            model=self._embedding.model,
        )

        documents = indexing_output["documents"]
        publish_output = load_verified_checkpoint(
            manifest_path,
            JobStage.PUBLISH,
            expected_input_sha256=indexing_sha,
        )
        publish_entry = manifest.get("stages", {}).get(JobStage.PUBLISH.value, {})
        stored_publish = stored_steps.get(JobStage.PUBLISH)
        publish_checksum = publish_entry.get("output_sha256") if isinstance(publish_entry, dict) else None
        if not (
            publish_output is not None
            and isinstance(publish_checksum, str)
            and (
                stored_publish is None
                or (stored_publish.output_checksum == publish_checksum and stored_publish.status is JobStatus.COMPLETED)
            )
        ):
            if stored_publish is not None or JobStage.PUBLISH.value in manifest.get("stages", {}):
                await self._repository.reset_steps_from(job, JobStage.PUBLISH)
                manifest["stages"].pop(JobStage.PUBLISH.value, None)
                await self._write_manifest(manifest_relative, manifest)
            started_at = self._now()
            monotonic_start = time.monotonic()
            result = await self._projection.project(documents)
            expected_ids = [str(document["_id"]) for document in documents]
            if (
                result.failed_ids
                or len(result.indexed_ids) != len(expected_ids)
                or set(result.indexed_ids) != set(expected_ids)
            ):
                raise RecordedVideoError(
                    ErrorCode.ES_5XX,
                    retryable=True,
                    message="ES_5XX: projection did not acknowledge every deterministic document ID",
                )
            publish_output = {"artifacts": {}, "projected_ids": expected_ids}
            publish_checksum = _sha256_json(publish_output)
            publish_entry = {
                "started_at": started_at.isoformat(),
                "completed_at": self._now().isoformat(),
                "elapsed_ms": max(0, round((time.monotonic() - monotonic_start) * 1_000)),
                "input_sha256": indexing_sha,
                "output_sha256": publish_checksum,
                "output": publish_output,
            }
            manifest["stages"][JobStage.PUBLISH.value] = publish_entry
            await self._write_manifest(manifest_relative, manifest)

        assert publish_output is not None
        assert isinstance(publish_checksum, str)
        publish_step = self._step(
            job,
            JobStage.PUBLISH,
            publish_checksum,
            publish_entry,
        )
        completed_job = await self._repository.complete_pipeline(
            job,
            probed_asset,
            completed_segments,
            publish_step,
        )
        manifest_bytes = manifest_path.read_bytes()
        return PipelineResult(
            job_id=completed_job.job_id,
            asset_id=completed_job.asset_id,
            status=completed_job.status,
            manifest_path=str(manifest_path),
            manifest_checksum=_sha256_bytes(manifest_bytes),
            segment_count=len(completed_segments),
            projected_ids=tuple(publish_output["projected_ids"]),
        )

    async def _probe(self, source_path: Path) -> dict[str, Any]:
        probe = await self._media.probe(source_path)
        return {
            "artifacts": {},
            "duration_ms": probe.duration_ms,
            "width": probe.width,
            "height": probe.height,
            "format_names": sorted(probe.format_names),
            "video_codec": probe.video_codec,
            "pixel_format": probe.pixel_format,
            "audio_codec": probe.audio_codec,
        }

    async def _segment(self, asset: Asset, pipeline_version: str) -> dict[str, Any]:
        segments = await self._segmenter.plan(asset, pipeline_version)
        return {
            "artifacts": {},
            "segments": [segment.model_dump(mode="json") for segment in segments],
        }

    async def _extract(
        self,
        source_path: Path,
        segments: Sequence[Segment],
        derived_root: Path,
        pipeline_version: str,
    ) -> dict[str, Any]:
        artifacts: dict[str, str] = {}
        outputs: list[dict[str, Any]] = []
        frame_root = derived_root / "frames"
        for segment in segments:
            paths = await self._media.extract_representative_frames(
                source_path,
                segment,
                frame_root,
                frame_count=self._representative_frames,
            )
            frame_keys: list[str] = []
            for path in paths:
                resolved = Path(path).resolve()
                root = derived_root.resolve()
                if not resolved.is_relative_to(root):
                    raise RecordedVideoError(
                        ErrorCode.CONFIGURATION,
                        retryable=False,
                        message="CONFIGURATION: media processor emitted an uncontrolled frame path",
                    )
                key = resolved.relative_to(root).as_posix()
                artifacts[key] = _sha256_bytes(resolved.read_bytes())
                frame_keys.append(key)
            if not frame_keys:
                raise RecordedVideoError(
                    ErrorCode.CORRUPT_MEDIA,
                    retryable=False,
                    message="CORRUPT_MEDIA: representative frame extraction returned no frames",
                )
            outputs.append(
                {
                    "segment_id": segment.segment_id,
                    "frames": frame_keys,
                    "thumbnail_key": f"derived/{pipeline_version}/{frame_keys[0]}",
                }
            )
        return {"artifacts": artifacts, "segments": outputs}

    async def _analyze(
        self,
        job: Job,
        segments: Sequence[Segment],
        extraction: Mapping[str, Any],
        derived_root: Path,
    ) -> dict[str, Any]:
        extracted = {item["segment_id"]: item for item in extraction["segments"]}
        outputs = []
        for segment in segments:
            frame_paths = [derived_root / key for key in extracted[segment.segment_id]["frames"]]
            description = await self._vision.describe(frame_paths, segment, job_id=job.job_id)
            outputs.append(
                {
                    "segment_id": segment.segment_id,
                    "description": description.description,
                    "tags": list(description.tags),
                }
            )
        return {"artifacts": {}, "segments": outputs}

    async def _embed(self, job: Job, analysis: Mapping[str, Any]) -> dict[str, Any]:
        outputs = []
        for item in analysis["segments"]:
            vector = await self._embedding.embed(
                item["description"],
                expected_dims=self._expected_embedding_dims,
                asset_id=job.asset_id,
                job_id=job.job_id,
            )
            outputs.append({"segment_id": item["segment_id"], "vector": list(vector)})
        return {"artifacts": {}, "segments": outputs}

    def _completed_segments(
        self,
        segments: Sequence[Segment],
        extraction: Mapping[str, Any],
        analysis: Mapping[str, Any],
    ) -> list[Segment]:
        extracted = {item["segment_id"]: item for item in extraction["segments"]}
        analyzed = {item["segment_id"]: item for item in analysis["segments"]}
        return [
            segment.model_copy(
                update={
                    "description": analyzed[segment.segment_id]["description"],
                    "thumbnail_key": extracted[segment.segment_id]["thumbnail_key"],
                    "model": self._vision.model,
                    "prompt_version": self._prompt_version,
                }
            )
            for segment in segments
        ]

    async def _index_documents(
        self,
        asset: Asset,
        segments: Sequence[Segment],
        embeddings: Mapping[str, Any],
    ) -> dict[str, Any]:
        vectors = {item["segment_id"]: item["vector"] for item in embeddings["segments"]}
        documents = [
            {
                "_id": segment.segment_id,
                "asset_id": asset.asset_id,
                "video_id": asset.asset_id,
                "segment_id": segment.segment_id,
                "sensor_id": asset.asset_id,
                "source_type": "recorded_video",
                "pipeline_version": segment.pipeline_version,
                "embedding_model": self._embedding.model,
                "video_name": asset.display_filename,
                "description": segment.description,
                "start_time": segment.start_time.isoformat(),
                "end_time": segment.end_time.isoformat(),
                "start_offset_ms": segment.start_offset_ms,
                "end_offset_ms": segment.end_offset_ms,
                "screenshot_url": segment.thumbnail_key,
                "vector": vectors[segment.segment_id],
            }
            for segment in segments
        ]
        return {"artifacts": {}, "documents": documents}

    def _load_manifest(self, path: Path, asset: Asset, job: Job) -> dict[str, Any]:
        versions = {
            "embedding_model": self._embedding.model,
            "prompt": self._prompt_version,
            "segmenter": self._segmenter_version,
            "vision_model": self._vision.model,
        }
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            stages = manifest.get("stages")
            if (
                manifest.get("schema_version") == _MANIFEST_SCHEMA_VERSION
                and manifest.get("asset_id") == asset.asset_id
                and manifest.get("job_id") == job.job_id
                and manifest.get("pipeline_version") == job.pipeline_version
                and manifest.get("versions") == versions
                and isinstance(stages, dict)
                and set(stages) <= {stage.value for stage in JobStage}
            ):
                return manifest
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        now = self._now().isoformat()
        return {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "asset_id": asset.asset_id,
            "job_id": job.job_id,
            "pipeline_version": job.pipeline_version,
            "input_sha256": asset.sha256,
            "versions": versions,
            "created_at": now,
            "updated_at": now,
            "stages": {},
        }

    async def _write_manifest(self, relative_path: str, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = self._now().isoformat()
        await self._asset_store.write_atomic(relative_path, _canonical_json(manifest))

    @staticmethod
    def _step(
        job: Job,
        stage: JobStage,
        output_checksum: str,
        entry: Mapping[str, Any],
        *,
        model: str | None = None,
    ) -> JobStep:
        return JobStep(
            job_id=job.job_id,
            stage=stage,
            status=JobStatus.COMPLETED,
            output_manifest=_manifest_key(job.pipeline_version),
            output_checksum=output_checksum,
            model=model,
            elapsed_ms=int(entry.get("elapsed_ms", 0)),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pipeline clock must be timezone-aware")
        return value.astimezone(UTC)


def _manifest_key(pipeline_version: str) -> str:
    return f"derived/{pipeline_version}/manifest.json"


def _safe_path_component(value: str, name: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value
        )
    ):
        raise RecordedVideoError(
            ErrorCode.CONFIGURATION,
            retryable=False,
            message=f"CONFIGURATION: {name} must be a safe path component",
        )
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
