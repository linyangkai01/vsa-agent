"""Checkpointed orchestration for recorded-video processing."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.media import MediaProbe
from vsa_agent.recorded_video.models import Asset, Job, JobStage, JobStatus, JobStep, Segment, segment_id
from vsa_agent.recorded_video.ports import (
    AssetStore,
    EmbeddingProvider,
    JobRepository,
    ProjectionReadiness,
    SearchProjectionStore,
    Segmenter,
    VisionProvider,
)

_MANIFEST_SCHEMA_VERSION = 2
_STAGE_ORDER = {stage: ordinal for ordinal, stage in enumerate(JobStage)}
_HASH_CHUNK_BYTES = 1024 * 1024


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
    """Return a stage output only when inline and streamed artifact checksums are valid."""
    manifest_path = Path(path)
    try:
        stage_name = JobStage(stage).value
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["stages"][stage_name]
        if not isinstance(entry, dict):
            return None
        output = entry["output"]
        if not isinstance(output, dict):
            return None
        if expected_input_sha256 is not None and entry.get("input_sha256") != expected_input_sha256:
            return None
        if entry.get("output_sha256") != _sha256_json(output):
            return None
        artifacts = output.get("artifacts", {})
        if not isinstance(artifacts, dict):
            return None
        asset_dir = _asset_dir_from_manifest_path(manifest_path)
        for key, checksum in artifacts.items():
            if not isinstance(key, str) or not isinstance(checksum, str):
                return None
            artifact = (asset_dir / PurePosixPath(key)).resolve()
            if not artifact.is_relative_to(asset_dir) or not artifact.is_file():
                return None
            if _sha256_file(artifact) != checksum:
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
        """Process or resume one actively leased job through fenced publication."""
        if job.status is not JobStatus.RUNNING or job.lease_owner is None:
            raise PermissionError("pipeline requires an actively leased running job")
        _safe_path_component(job.asset_id, "asset_id")
        _safe_path_component(job.pipeline_version, "pipeline_version")
        await self._repository.start_pipeline(job)
        asset = await self._repository.get_asset(job.asset_id)
        manifest_key = _manifest_key(job.pipeline_version, job.attempt)
        manifest_relative = f"assets/{asset.asset_id}/{manifest_key}"
        asset_root = self._asset_store.root.resolve()
        asset_dir = (asset_root / "assets" / asset.asset_id).resolve()
        manifest_path = (asset_root / manifest_relative).resolve()
        if not asset_dir.is_relative_to(asset_root) or not manifest_path.is_relative_to(asset_dir):
            raise _pipeline_error("manifest path escaped the asset store")
        manifest = self._new_manifest(asset, job)
        stored_steps = {step.stage: step for step in await self._repository.list_job_steps(job.job_id)}
        source_path = await self._asset_store.resolve_source_path(asset)
        if _sha256_file(source_path) != asset.sha256:
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message="CORRUPT_MEDIA: source checksum does not match the uploaded asset",
            )

        async def run_stage(
            stage: JobStage,
            input_sha256: str,
            operation: Callable[[], Awaitable[dict[str, Any]]],
            validator: Callable[[Mapping[str, Any]], None],
            *,
            model: str | None = None,
        ) -> tuple[dict[str, Any], str]:
            nonlocal stored_steps
            stored = stored_steps.get(stage)
            candidate_path = manifest_path
            if stored is not None and stored.output_manifest is not None:
                candidate_path = self._checkpoint_path(asset_dir, job.pipeline_version, stored.output_manifest)
            candidate_manifest = self._compatible_manifest(candidate_path, asset, job)
            entry = candidate_manifest.get("stages", {}).get(stage.value, {})
            output_checksum = entry.get("output_sha256") if isinstance(entry, dict) else None
            verified = load_verified_checkpoint(
                candidate_path,
                stage,
                expected_input_sha256=input_sha256,
            )
            checkpoint_matches = stored is None or (
                stored.status is JobStatus.COMPLETED
                and stored.output_checksum == output_checksum
                and stored.output_manifest == self._manifest_key_for_path(asset_dir, candidate_path)
            )
            if verified is not None and checkpoint_matches and isinstance(output_checksum, str):
                try:
                    validator(verified)
                except (KeyError, TypeError, ValueError, RecordedVideoError):
                    verified = None
                else:
                    manifest["stages"][stage.value] = entry
                    if stored is None:
                        step = self._step(job, stage, manifest_key, output_checksum, entry, model=model)
                        await self._repository.checkpoint_step(job, step)
                        stored_steps[stage] = step
                    return verified, output_checksum

            if stored is not None:
                await self._repository.reset_steps_from(job, stage)
                stored_steps = {
                    candidate: step
                    for candidate, step in stored_steps.items()
                    if _STAGE_ORDER[candidate] < _STAGE_ORDER[stage]
                }
            manifest["stages"] = {
                name: value
                for name, value in manifest["stages"].items()
                if _STAGE_ORDER[JobStage(name)] < _STAGE_ORDER[stage]
            }

            started_at = self._now()
            monotonic_start = time.monotonic()
            output = await operation()
            validator(output)
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
            await self._write_manifest(job, manifest_relative, manifest)
            step = self._step(job, stage, manifest_key, output_checksum, entry, model=model)
            await self._repository.checkpoint_step(job, step)
            stored_steps[stage] = step
            return output, output_checksum

        probe_output, probe_sha = await run_stage(
            JobStage.PROBING,
            asset.sha256,
            lambda: self._probe(source_path),
            self._validate_probe,
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
            lambda output: self._validate_segments(output, probed_asset, job.pipeline_version),
            model=self._segmenter_version,
        )
        segments = [Segment.model_validate(payload) for payload in segment_output["segments"]]
        extraction_output, extraction_sha = await run_stage(
            JobStage.EXTRACTING,
            segment_sha,
            lambda: self._extract(job, source_path, segments, asset_dir, manifest_path.parent),
            lambda output: self._validate_extraction(output, segments),
        )
        analysis_output, analysis_sha = await run_stage(
            JobStage.ANALYZING,
            extraction_sha,
            lambda: self._analyze(job, segments, extraction_output, asset_dir),
            lambda output: self._validate_analysis(output, segments),
            model=self._vision.model,
        )
        embedding_output, embedding_sha = await run_stage(
            JobStage.EMBEDDING,
            analysis_sha,
            lambda: self._embed(job, analysis_output),
            lambda output: self._validate_embeddings(output, segments),
            model=self._embedding.model,
        )
        completed_segments = self._completed_segments(segments, extraction_output, analysis_output)
        indexing_output, indexing_sha = await run_stage(
            JobStage.INDEXING,
            embedding_sha,
            lambda: self._index_documents(job, asset, completed_segments, embedding_output),
            lambda output: self._validate_projection_manifest(output, job, asset, completed_segments),
            model=self._embedding.model,
        )

        documents = indexing_output["documents"]
        projection_started = False
        try:
            await self._repository.assert_active_lease(job)
            projection_started = True
            projection_result = await self._projection.project(documents)
            await self._repository.assert_active_lease(job)
            expected_ids = [str(document["_id"]) for document in documents]
            if (
                projection_result.failed_ids
                or len(projection_result.indexed_ids) != len(expected_ids)
                or set(projection_result.indexed_ids) != set(expected_ids)
            ):
                raise RecordedVideoError(
                    ErrorCode.ES_5XX,
                    retryable=True,
                    message="ES_5XX: projection did not acknowledge every deterministic document ID",
                )
            publish_output = {"artifacts": {}, "projected_ids": expected_ids}
            publish_checksum = _sha256_json(publish_output)
            started_at = self._now()
            publish_entry = {
                "started_at": started_at.isoformat(),
                "completed_at": self._now().isoformat(),
                "elapsed_ms": 0,
                "input_sha256": indexing_sha,
                "output_sha256": publish_checksum,
                "output": publish_output,
            }
            manifest["stages"][JobStage.PUBLISH.value] = publish_entry
            await self._write_manifest(job, manifest_relative, manifest)
            publish_step = self._step(
                job,
                JobStage.PUBLISH,
                manifest_key,
                publish_checksum,
                publish_entry,
            )
            completed_job = await self._repository.complete_pipeline(
                job,
                probed_asset,
                completed_segments,
                publish_step,
            )
        except BaseException:
            if projection_started:
                with suppress(Exception):
                    await self._projection.delete_asset(job.asset_id)
            raise

        return PipelineResult(
            job_id=completed_job.job_id,
            asset_id=completed_job.asset_id,
            status=completed_job.status,
            manifest_path=str(manifest_path),
            manifest_checksum=_sha256_file(manifest_path),
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
        return {"artifacts": {}, "segments": [segment.model_dump(mode="json") for segment in segments]}

    async def _extract(
        self,
        job: Job,
        source_path: Path,
        segments: Sequence[Segment],
        asset_dir: Path,
        attempt_dir: Path,
    ) -> dict[str, Any]:
        artifacts: dict[str, str] = {}
        outputs: list[dict[str, Any]] = []
        frame_root = attempt_dir / "frames"
        for segment in segments:
            await self._repository.assert_active_lease(job)
            paths = await self._media.extract_representative_frames(
                source_path,
                segment,
                frame_root,
                frame_count=self._representative_frames,
            )
            frame_keys: list[str] = []
            for path in paths:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(attempt_dir):
                    raise _pipeline_error("media processor emitted an uncontrolled frame path")
                key = resolved.relative_to(asset_dir).as_posix()
                artifacts[key] = _sha256_file(resolved)
                frame_keys.append(key)
            outputs.append(
                {
                    "segment_id": segment.segment_id,
                    "frames": frame_keys,
                    "thumbnail_key": frame_keys[0] if frame_keys else None,
                }
            )
        return {"artifacts": artifacts, "segments": outputs}

    async def _analyze(
        self,
        job: Job,
        segments: Sequence[Segment],
        extraction: Mapping[str, Any],
        asset_dir: Path,
    ) -> dict[str, Any]:
        extracted = {item["segment_id"]: item for item in extraction["segments"]}
        outputs = []
        for segment in segments:
            frame_paths = [asset_dir / PurePosixPath(key) for key in extracted[segment.segment_id]["frames"]]
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
        job: Job,
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
                "ordinal": segment.ordinal,
                "sensor_id": asset.asset_id,
                "source_type": "recorded_video",
                "job_id": job.job_id,
                "job_attempt": job.attempt,
                "readiness": ProjectionReadiness(
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    pipeline_version=job.pipeline_version,
                    attempt=job.attempt,
                ).model_dump(),
                "pipeline_version": segment.pipeline_version,
                "embedding_model": self._embedding.model,
                "vision_model": self._vision.model,
                "prompt_version": self._prompt_version,
                "segmenter_version": self._segmenter_version,
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

    @staticmethod
    def _validate_probe(output: Mapping[str, Any]) -> None:
        if output.get("artifacts") != {}:
            raise _pipeline_error("probe manifest artifacts must be empty")
        if type(output.get("duration_ms")) is not int or output["duration_ms"] <= 0:
            raise _pipeline_error("probe duration must be positive")
        for name in ("width", "height"):
            if type(output.get(name)) is not int or output[name] <= 0:
                raise _pipeline_error(f"probe {name} must be positive")

    @staticmethod
    def _validate_segments(output: Mapping[str, Any], asset: Asset, pipeline_version: str) -> None:
        try:
            payloads = output["segments"]
            segments = [Segment.model_validate(payload) for payload in payloads]
        except (KeyError, TypeError, ValueError) as error:
            raise _pipeline_error("segment manifest is incomplete") from error
        if output.get("artifacts") != {} or not segments:
            raise _pipeline_error("segment manifest is incomplete")
        expected_start = 0
        for ordinal, segment in enumerate(segments):
            if (
                segment.asset_id != asset.asset_id
                or segment.pipeline_version != pipeline_version
                or segment.ordinal != ordinal
                or segment.segment_id != segment_id(asset.asset_id, pipeline_version, ordinal)
                or segment.start_offset_ms != expected_start
                or segment.start_time != asset.timeline_origin + timedelta(milliseconds=segment.start_offset_ms)
                or segment.end_time != asset.timeline_origin + timedelta(milliseconds=segment.end_offset_ms)
                or segment.end_offset_ms <= segment.start_offset_ms
            ):
                raise _pipeline_error("segment identity or order is invalid")
            expected_start = segment.end_offset_ms
        if expected_start != asset.duration_ms:
            raise _pipeline_error("segments do not cover the complete asset")

    def _validate_extraction(self, output: Mapping[str, Any], segments: Sequence[Segment]) -> None:
        try:
            items = output["segments"]
            artifacts = output["artifacts"]
        except KeyError as error:
            raise _pipeline_error("extraction manifest is incomplete") from error
        if not isinstance(items, list) or not isinstance(artifacts, dict) or len(items) != len(segments):
            raise _pipeline_error("extraction manifest is incomplete")
        all_frames: list[str] = []
        for segment, item in zip(segments, items, strict=True):
            if not isinstance(item, dict):
                raise _pipeline_error("extraction manifest is incomplete")
            frames = item.get("frames")
            if (
                item.get("segment_id") != segment.segment_id
                or not isinstance(frames, list)
                or len(frames) != self._representative_frames
                or len(set(frames)) != len(frames)
                or item.get("thumbnail_key") != frames[0]
                or any(not isinstance(frame, str) for frame in frames)
            ):
                raise RecordedVideoError(
                    ErrorCode.CORRUPT_MEDIA,
                    retryable=False,
                    message="CORRUPT_MEDIA: representative frame output is incomplete",
                )
            all_frames.extend(frames)
        if len(set(all_frames)) != len(all_frames) or set(artifacts) != set(all_frames):
            raise _pipeline_error("representative frame artifact ownership is invalid")

    @staticmethod
    def _validate_analysis(output: Mapping[str, Any], segments: Sequence[Segment]) -> None:
        items = output.get("segments")
        if output.get("artifacts") != {} or not isinstance(items, list) or len(items) != len(segments):
            raise _pipeline_error("analysis manifest is incomplete")
        for segment, item in zip(segments, items, strict=True):
            if (
                not isinstance(item, dict)
                or item.get("segment_id") != segment.segment_id
                or not isinstance(item.get("description"), str)
                or not item["description"].strip()
                or not isinstance(item.get("tags"), list)
                or any(not isinstance(tag, str) for tag in item["tags"])
            ):
                raise _pipeline_error("analysis manifest is incomplete")

    def _validate_embeddings(self, output: Mapping[str, Any], segments: Sequence[Segment]) -> None:
        items = output.get("segments")
        if output.get("artifacts") != {} or not isinstance(items, list) or len(items) != len(segments):
            raise _embedding_error("embedding manifest is incomplete")
        for segment, item in zip(segments, items, strict=True):
            if not isinstance(item, dict):
                raise _embedding_error("embedding manifest is incomplete")
            vector = item.get("vector")
            if (
                item.get("segment_id") != segment.segment_id
                or not isinstance(vector, list)
                or len(vector) != self._expected_embedding_dims
                or any(type(value) is not float or not math.isfinite(value) for value in vector)
            ):
                raise _embedding_error("embedding vector dimensions or values are invalid")

    def _validate_projection_manifest(
        self,
        output: Mapping[str, Any],
        job: Job,
        asset: Asset,
        segments: Sequence[Segment],
    ) -> None:
        documents = output.get("documents")
        if output.get("artifacts") != {} or not isinstance(documents, list) or len(documents) != len(segments):
            raise _pipeline_error("projection manifest is incomplete")
        required = {
            "_id",
            "asset_id",
            "video_id",
            "segment_id",
            "ordinal",
            "sensor_id",
            "source_type",
            "job_id",
            "job_attempt",
            "readiness",
            "pipeline_version",
            "embedding_model",
            "vision_model",
            "prompt_version",
            "segmenter_version",
            "video_name",
            "description",
            "start_time",
            "end_time",
            "start_offset_ms",
            "end_offset_ms",
            "screenshot_url",
            "vector",
        }
        seen_ids: set[str] = set()
        for segment, document in zip(segments, documents, strict=True):
            if not isinstance(document, dict) or not required <= set(document):
                raise _pipeline_error("projection document fields are incomplete")
            expected = {
                "_id": segment.segment_id,
                "asset_id": asset.asset_id,
                "video_id": asset.asset_id,
                "segment_id": segment.segment_id,
                "ordinal": segment.ordinal,
                "sensor_id": asset.asset_id,
                "source_type": "recorded_video",
                "job_id": job.job_id,
                "job_attempt": job.attempt,
                "readiness": ProjectionReadiness(
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    pipeline_version=job.pipeline_version,
                    attempt=job.attempt,
                ).model_dump(),
                "pipeline_version": job.pipeline_version,
                "embedding_model": self._embedding.model,
                "vision_model": self._vision.model,
                "prompt_version": self._prompt_version,
                "segmenter_version": self._segmenter_version,
                "video_name": asset.display_filename,
                "description": segment.description,
                "start_time": segment.start_time.isoformat(),
                "end_time": segment.end_time.isoformat(),
                "start_offset_ms": segment.start_offset_ms,
                "end_offset_ms": segment.end_offset_ms,
                "screenshot_url": segment.thumbnail_key,
            }
            if any(document.get(key) != value for key, value in expected.items()):
                raise _pipeline_error("projection document identity or model metadata is invalid")
            if document["_id"] in seen_ids:
                raise _pipeline_error("projection document IDs must be unique")
            seen_ids.add(document["_id"])
            vector = document["vector"]
            if (
                not isinstance(vector, list)
                or len(vector) != self._expected_embedding_dims
                or any(type(value) is not float or not math.isfinite(value) for value in vector)
            ):
                raise _embedding_error("projection vector dimensions or values are invalid")

    def _new_manifest(self, asset: Asset, job: Job) -> dict[str, Any]:
        now = self._now().isoformat()
        return {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "asset_id": asset.asset_id,
            "job_id": job.job_id,
            "pipeline_version": job.pipeline_version,
            "input_sha256": asset.sha256,
            "checkpoint_identity": self._checkpoint_identity(),
            "created_at": now,
            "updated_at": now,
            "stages": {},
        }

    def _compatible_manifest(self, path: Path, asset: Asset, job: Job) -> dict[str, Any]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            stages = manifest.get("stages")
            if (
                manifest.get("schema_version") == _MANIFEST_SCHEMA_VERSION
                and manifest.get("asset_id") == asset.asset_id
                and manifest.get("job_id") == job.job_id
                and manifest.get("pipeline_version") == job.pipeline_version
                and manifest.get("input_sha256") == asset.sha256
                and manifest.get("checkpoint_identity") == self._checkpoint_identity()
                and isinstance(stages, dict)
                and set(stages) <= {stage.value for stage in JobStage}
            ):
                return manifest
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return {"stages": {}}

    def _checkpoint_identity(self) -> dict[str, Any]:
        vision_identity = dict(self._vision.checkpoint_identity)
        vision_identity["model"] = self._vision.model
        embedding_identity = dict(self._embedding.checkpoint_identity)
        embedding_identity["model"] = self._embedding.model
        identity = {
            "representative_frames": self._representative_frames,
            "expected_embedding_dims": self._expected_embedding_dims,
            "prompt_version": self._prompt_version,
            "segmenter": {
                "version": self._segmenter_version,
                "config": dict(self._segmenter.checkpoint_identity),
            },
            "vision": vision_identity,
            "embedding": embedding_identity,
        }
        _canonical_json(identity)
        if _contains_secret_key(identity):
            raise _pipeline_error("checkpoint identity contains a secret-like field")
        return identity

    async def _write_manifest(self, job: Job, relative_path: str, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = self._now().isoformat()
        await self._repository.assert_active_lease(job)
        await self._asset_store.write_atomic(relative_path, _canonical_json(manifest))

    @staticmethod
    def _checkpoint_path(asset_dir: Path, pipeline_version: str, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if (
            len(parts) != 5
            or parts[:3] != ("derived", pipeline_version, "attempts")
            or parts[4] != "manifest.json"
            or not parts[3].isdigit()
            or int(parts[3]) <= 0
        ):
            raise _pipeline_error("checkpoint manifest key is not canonical")
        path = (asset_dir / PurePosixPath(key)).resolve()
        if not path.is_relative_to(asset_dir):
            raise _pipeline_error("checkpoint manifest path escaped its asset")
        return path

    @staticmethod
    def _manifest_key_for_path(asset_dir: Path, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(asset_dir):
            raise _pipeline_error("checkpoint manifest path escaped its asset")
        return resolved.relative_to(asset_dir).as_posix()

    @staticmethod
    def _step(
        job: Job,
        stage: JobStage,
        manifest_key: str,
        output_checksum: str,
        entry: Mapping[str, Any],
        *,
        model: str | None = None,
    ) -> JobStep:
        return JobStep(
            job_id=job.job_id,
            stage=stage,
            status=JobStatus.COMPLETED,
            output_manifest=manifest_key,
            output_checksum=output_checksum,
            model=model,
            elapsed_ms=int(entry.get("elapsed_ms", 0)),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pipeline clock must be timezone-aware")
        return value.astimezone(UTC)


def _manifest_key(pipeline_version: str, attempt: int) -> str:
    return f"derived/{pipeline_version}/attempts/{attempt}/manifest.json"


def _asset_dir_from_manifest_path(path: Path) -> Path:
    resolved = path.resolve()
    parts = resolved.parts
    try:
        derived_index = max(index for index, part in enumerate(parts) if part == "derived")
    except ValueError as error:
        raise ValueError("manifest is not beneath an asset derived directory") from error
    if derived_index < 1:
        raise ValueError("manifest has no asset directory")
    return Path(*parts[:derived_index]).resolve()


def _safe_path_component(value: str, name: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value
        )
    ):
        raise _pipeline_error(f"{name} must be a safe path component")
    return value


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(token in normalized for token in ("api_key", "authorization", "password", "secret", "token")):
                return True
            if _contains_secret_key(item):
                return True
    elif isinstance(value, list | tuple):
        return any(_contains_secret_key(item) for item in value)
    return False


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _pipeline_error(message: str) -> RecordedVideoError:
    return RecordedVideoError(
        ErrorCode.CONFIGURATION,
        retryable=False,
        message=f"CONFIGURATION: {message}",
    )


def _embedding_error(message: str) -> RecordedVideoError:
    return RecordedVideoError(
        ErrorCode.EMBEDDING_DIMENSION,
        retryable=False,
        message=f"EMBEDDING_DIMENSION: {message}",
    )
