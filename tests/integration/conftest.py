from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from vsa_agent.api import recorded_video as recorded_video_api
from vsa_agent.config import AppConfig, RecordedVideoConfig, SearchBackendConfig
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.es_index import ElasticsearchProjectionStore, RecordedVideoIndex
from vsa_agent.recorded_video.media import MediaProbe
from vsa_agent.recorded_video.models import Job, JobStatus, Segment
from vsa_agent.recorded_video.pipeline import RecordedVideoPipeline
from vsa_agent.recorded_video.ports import ProjectionResult
from vsa_agent.recorded_video.providers import OpenAIEmbeddingProvider, OpenAIVisionProvider
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter
from vsa_agent.recorded_video.worker import RecordedVideoWorker

_EMBEDDING_DIMS = 4


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises the recorded-video API, persistence, pipeline, and worker stack",
    )


class _Clock:
    def __init__(self) -> None:
        # API-created jobs use wall time. Staying ahead avoids sub-millisecond races.
        self.value = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance_past(self, value: datetime | None) -> None:
        if value is not None and self.value <= value:
            self.value = value + timedelta(milliseconds=1)


class _ProviderController:
    def __init__(self) -> None:
        self.vision_statuses: deque[int] = deque()
        self.embedding_statuses: deque[int] = deque()
        self.calls: list[tuple[str, int]] = []

    def fail_next(self, endpoint: str, status: int) -> None:
        target = self.vision_statuses if endpoint == "vision" else self.embedding_statuses
        target.append(status)

    def vision(self, _request: Request) -> Response:
        status = self.vision_statuses.popleft() if self.vision_statuses else 200
        self.calls.append(("vision", status))
        if status != 200:
            return Response(
                json.dumps({"error": {"message": "injected"}}),
                status=status,
                content_type="application/json",
            )
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"description": "worker crosses the loading area", "tags": ["worker", "loading"]}
                        )
                    }
                }
            ]
        }
        return Response(json.dumps(body), content_type="application/json")

    def embedding(self, _request: Request) -> Response:
        status = self.embedding_statuses.popleft() if self.embedding_statuses else 200
        self.calls.append(("embedding", status))
        if status != 200:
            return Response(
                json.dumps({"error": {"message": "injected"}}),
                status=status,
                content_type="application/json",
            )
        body = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}
        return Response(json.dumps(body), content_type="application/json")


class _ControlledMedia:
    async def probe(self, path: str | Path) -> MediaProbe:
        source = Path(path)
        if source.read_bytes().startswith(b"CORRUPT"):
            raise RecordedVideoError(
                ErrorCode.CORRUPT_MEDIA,
                retryable=False,
                message="CORRUPT_MEDIA: injected invalid media",
            )
        return MediaProbe(
            duration_ms=4_000,
            width=640,
            height=360,
            format_names=frozenset({"matroska" if source.suffix == ".mkv" else "mp4"}),
            video_codec="h264",
            pixel_format="yuv420p",
            audio_codec="aac",
        )

    async def extract_representative_frames(
        self,
        _source_path: str | Path,
        segment: Segment,
        output_dir: str | Path,
        *,
        frame_count: int,
    ) -> Sequence[Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        paths = []
        for ordinal in range(frame_count):
            path = root / f"{segment.segment_id}-{ordinal}.jpg"
            path.write_bytes(b"integration-jpeg")
            paths.append(path)
        return paths


class _MemoryProjection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def project(
        self,
        documents: Sequence[Mapping[str, Any]],
        *,
        job_id: str,
        attempt: int,
    ) -> ProjectionResult:
        ids = []
        for value in documents:
            document = dict(value)
            document_id = str(document["_id"])
            current = self.documents.get(document_id)
            if current is None or int(current["job_attempt"]) <= attempt:
                self.documents[document_id] = document
            ids.append(document_id)
        return ProjectionResult(indexed_ids=ids)

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        self.documents = {
            key: value
            for key, value in self.documents.items()
            if not (value["asset_id"] == asset_id and value["job_id"] == job_id and value["job_attempt"] == attempt)
        }

    async def delete_asset(self, asset_id: str) -> None:
        self.documents = {key: value for key, value in self.documents.items() if value["asset_id"] != asset_id}

    async def ids(self) -> set[str]:
        return set(self.documents)

    async def close(self) -> None:
        return None


class _ElasticsearchProjection:
    def __init__(self, client: AsyncElasticsearch, alias: str) -> None:
        self.client = client
        self.alias = alias
        self.index = RecordedVideoIndex(client, alias=alias)
        self.store = ElasticsearchProjectionStore(client, index=self.index)

    async def bootstrap(self) -> None:
        await self.index.bootstrap(model="embedding-it", dims=_EMBEDDING_DIMS)

    async def project(self, documents, *, job_id: str, attempt: int) -> ProjectionResult:
        return await self.store.project(documents, job_id=job_id, attempt=attempt)

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        await self.store.delete_projection(asset_id, job_id, attempt)

    async def delete_asset(self, asset_id: str) -> None:
        await self.store.delete_asset(asset_id)

    async def ids(self) -> set[str]:
        await self.client.indices.refresh(index=self.alias)
        response = await self.client.search(index=self.alias, query={"match_all": {}}, size=10_000, _source=False)
        return {str(hit["_id"]) for hit in response["hits"]["hits"]}

    async def close(self) -> None:
        try:
            aliases = await self.client.indices.get_alias(name=self.alias)
            if aliases:
                await self.client.indices.delete(index=",".join(aliases))
        finally:
            await self.client.close()


class _FaultInjectingProjection:
    def __init__(self, backend: _MemoryProjection | _ElasticsearchProjection) -> None:
        self.backend = backend
        self.partial_failure_once = False
        self.delete_failure_once = False

    async def project(self, documents, *, job_id: str, attempt: int) -> ProjectionResult:
        result = await self.backend.project(documents, job_id=job_id, attempt=attempt)
        if self.partial_failure_once and result.indexed_ids:
            self.partial_failure_once = False
            return ProjectionResult(indexed_ids=result.indexed_ids[:-1], failed_ids=result.indexed_ids[-1:])
        return result

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        await self.backend.delete_projection(asset_id, job_id, attempt)

    async def delete_asset(self, asset_id: str) -> None:
        if self.delete_failure_once:
            self.delete_failure_once = False
            raise RecordedVideoError(ErrorCode.ES_5XX, retryable=True, message="ES_5XX: injected delete interruption")
        await self.backend.delete_asset(asset_id)

    async def ids(self) -> set[str]:
        return await self.backend.ids()

    async def close(self) -> None:
        await self.backend.close()


class _FaultyAssetStore(LocalAssetStore):
    disk_full = False

    async def write_chunk(self, session, ordinal: int, data: bytes) -> str:
        if type(self).disk_full:
            raise RecordedVideoError(
                ErrorCode.DISK_FULL,
                retryable=False,
                message="DISK_FULL: injected capacity failure",
            )
        return await super().write_chunk(session, ordinal, data)


@dataclass(frozen=True)
class UploadTicket:
    asset_id: str
    session_id: str
    upload_url: str
    filename: str
    identifier: str


@dataclass(frozen=True)
class UploadedJob:
    asset_id: str
    job_id: str
    session_id: str
    filename: str
    content: bytes


class RecordedVideoStack:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        repository: JobRepository,
        store: LocalAssetStore,
        worker: RecordedVideoWorker,
        projection: _FaultInjectingProjection,
        provider: _ProviderController,
        clock: _Clock,
    ) -> None:
        self.client = client
        self.repository = repository
        self.store = store
        self.worker = worker
        self.projection = projection
        self.provider = provider
        self.clock = clock

    async def begin_upload(self, filename: str) -> UploadTicket:
        response = await self.client.post("/api/v1/videos", json={"filename": filename})
        assert response.status_code == 200, response.text
        payload = response.json()
        return UploadTicket(
            asset_id=payload["asset_id"],
            session_id=payload["upload_session_id"],
            upload_url=payload["url"],
            filename=filename,
            identifier=str(uuid.uuid4()),
        )

    async def upload_chunk(self, ticket: UploadTicket, content: bytes) -> httpx.Response:
        return await self.client.post(
            ticket.upload_url,
            headers={
                "nvstreamer-identifier": ticket.identifier,
                "nvstreamer-file-name": ticket.filename,
                "nvstreamer-chunk-number": "1",
                "nvstreamer-total-chunks": "1",
                "nvstreamer-is-last-chunk": "true",
            },
            files={"mediaFile": (ticket.filename, content, "video/mp4")},
        )

    async def complete(self, ticket: UploadTicket) -> httpx.Response:
        return await self.client.post(f"/api/v1/videos/{ticket.asset_id}/complete", json={})

    async def upload_and_complete(
        self,
        filename: str,
        *,
        content: bytes | None = None,
        duplicate_chunk: bool = False,
        duplicate_complete: bool = False,
    ) -> UploadedJob:
        body = content if content is not None else f"integration-video:{filename}".encode()
        ticket = await self.begin_upload(filename)
        chunk = await self.upload_chunk(ticket, body)
        assert chunk.status_code == 200, chunk.text
        if duplicate_chunk:
            repeated_chunk = await self.upload_chunk(ticket, body)
            assert repeated_chunk.status_code == 200, repeated_chunk.text
            assert repeated_chunk.json() == chunk.json()
        completion = await self.complete(ticket)
        assert completion.status_code == 202, completion.text
        if duplicate_complete:
            repeated_completion = await self.complete(ticket)
            assert repeated_completion.status_code == 202, repeated_completion.text
            assert repeated_completion.json() == completion.json()
        return UploadedJob(
            asset_id=ticket.asset_id,
            job_id=completion.json()["job_id"],
            session_id=ticket.session_id,
            filename=filename,
            content=body,
        )

    async def wait_completed(self, jobs: Sequence[UploadedJob]) -> list[Job]:
        for _ in range(12):
            await self.worker.run_until_idle()
            current = [await self.repository.get_job(job.job_id) for job in jobs]
            if all(job.status is JobStatus.COMPLETED for job in current):
                return current
            terminal = [job for job in current if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}]
            if terminal:
                raise AssertionError(
                    "jobs reached unexpected terminal state: "
                    + ", ".join(f"{job.job_id}={job.status.value}:{job.last_error}" for job in terminal)
                )
            for job in current:
                self.clock.advance_past(job.next_run_at)
        raise AssertionError("jobs did not complete within bounded worker drains")

    async def es_ids(self) -> set[str]:
        return await self.projection.ids()

    async def expected_segment_ids(self, jobs: Sequence[UploadedJob] | None = None) -> set[str]:
        if jobs is None:
            with sqlite3.connect(self.repository.database_path) as connection:
                rows = connection.execute("SELECT segment_id FROM segments").fetchall()
            return {str(row[0]) for row in rows}
        ids: set[str] = set()
        for job in jobs:
            ids.update(segment.segment_id for segment in await self.repository.list_segments(job.asset_id))
        return ids

    async def kill_worker(self) -> Job:
        claimed = await self.repository.claim_due_job("killed-worker", self.clock())
        assert claimed is not None
        self.clock.advance(3)
        return claimed

    async def job_count(self, asset_id: str) -> int:
        with sqlite3.connect(self.repository.database_path) as connection:
            row = connection.execute("SELECT COUNT(*) FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
        assert row is not None
        return int(row[0])

    def source_path(self, job: UploadedJob) -> Path:
        return self.store.root / "assets" / job.asset_id / "source" / f"original.{Path(job.filename).suffix[1:]}"

    def files_for(self, asset_id: str) -> set[str]:
        root = self.store.root / "assets" / asset_id
        if not root.exists():
            return set()
        return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}

    def temporary_files(self) -> set[str]:
        return {
            path.relative_to(self.store.root).as_posix()
            for path in self.store.root.rglob("*")
            if path.is_file() and ".tmp" in path.suffixes
        }


@pytest.fixture
async def recorded_video_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    httpserver: HTTPServer,
) -> RecordedVideoStack:
    es_url = os.environ.get("VSA_TEST_ES_URL", "").strip()
    fallback = os.environ.get("VSA_RECORDED_VIDEO_TEST_FALLBACK") == "1"
    if not es_url and not fallback:
        pytest.fail(
            "recorded-video integration requires VSA_TEST_ES_URL for real Elasticsearch or "
            "VSA_RECORDED_VIDEO_TEST_FALLBACK=1 for the explicit local projection fallback"
        )

    provider = _ProviderController()
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_handler(provider.vision)
    httpserver.expect_request("/v1/embeddings", method="POST").respond_with_handler(provider.embedding)

    config = AppConfig(
        recorded_video=RecordedVideoConfig(
            enabled=True,
            data_root=tmp_path,
            max_upload_bytes=1024 * 1024,
            segment_duration_sec=2,
            representative_frames=1,
            worker_concurrency=3,
            lease_sec=2,
            max_attempts=3,
        ),
        search=SearchBackendConfig(
            enabled=bool(es_url),
            es_endpoint=es_url,
            embed_index=f"vsa-recorded-video-it-{uuid.uuid4().hex}",
            verify_certs=False,
            allow_mock_fallback=fallback,
        ),
    )
    monkeypatch.setattr(recorded_video_api, "get_config", lambda: config)
    _FaultyAssetStore.disk_full = False
    monkeypatch.setattr(recorded_video_api, "LocalAssetStore", _FaultyAssetStore)

    clock = _Clock()
    repository = JobRepository(
        tmp_path / "recorded-video.sqlite3",
        lease_seconds=2,
        clock=clock,
        allowed_snapshot_models={"vision-it", "embedding-it"},
    )
    await repository.initialize()
    store = _FaultyAssetStore(tmp_path, cleanup_repository=repository)

    if es_url:
        es_client = AsyncElasticsearch(es_url, request_timeout=10, verify_certs=False)
        if not await es_client.ping():
            await es_client.close()
            pytest.fail(f"VSA_TEST_ES_URL is not reachable: {es_url}")
        backend: _MemoryProjection | _ElasticsearchProjection = _ElasticsearchProjection(
            es_client,
            config.search.embed_index,
        )
        await backend.bootstrap()
    else:
        backend = _MemoryProjection()
    projection = _FaultInjectingProjection(backend)

    base_url = httpserver.url_for("/v1/")
    vision = OpenAIVisionProvider(
        base_url=base_url,
        api_key="integration-secret",
        model="vision-it",
        timeout_sec=5,
        concurrency=3,
    )
    embedding = OpenAIEmbeddingProvider(
        base_url=base_url,
        api_key="integration-secret",
        model="embedding-it",
        timeout_sec=5,
        concurrency=3,
    )
    pipeline = RecordedVideoPipeline(
        repository=repository,
        asset_store=store,
        media=_ControlledMedia(),
        segmenter=FixedDurationSegmenter(2),
        vision=vision,
        embedding=embedding,
        projection=projection,
        expected_embedding_dims=_EMBEDDING_DIMS,
        representative_frames=1,
        prompt_version="integration-prompt-v1",
        segmenter_version="fixed-2s-v1",
        clock=clock,
    )
    worker = RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=3,
        lease_sec=2,
        max_attempts=3,
        clock=clock,
        output=lambda _line: None,
    )

    app = FastAPI()
    app.include_router(recorded_video_api.router)
    app.state.recorded_video_projection_store = projection
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    stack = RecordedVideoStack(
        client=client,
        repository=repository,
        store=store,
        worker=worker,
        projection=projection,
        provider=provider,
        clock=clock,
    )
    try:
        yield stack
    finally:
        await client.aclose()
        await vision.aclose()
        await embedding.aclose()
        await projection.close()
