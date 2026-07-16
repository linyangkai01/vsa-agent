from __future__ import annotations

import asyncio
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
from vsa_agent.recorded_video import es_index as es_index_module
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
    def __init__(self) -> None:
        self._block_probe = False
        self.probe_started = asyncio.Event()
        self.probe_release = asyncio.Event()

    def block_next_probe(self) -> None:
        self._block_probe = True
        self.probe_started = asyncio.Event()
        self.probe_release = asyncio.Event()

    def release_probe(self) -> None:
        self.probe_release.set()

    def reset_probe(self) -> None:
        self._block_probe = False
        self.probe_release.set()

    async def probe(self, path: str | Path) -> MediaProbe:
        if self._block_probe:
            self.probe_started.set()
            await self.probe_release.wait()
            self._block_probe = False
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

    async def attempts(self) -> set[int]:
        return {int(document["job_attempt"]) for document in self.documents.values()}

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

    async def attempts(self) -> set[int]:
        await self.client.indices.refresh(index=self.alias)
        response = await self.client.search(
            index=self.alias,
            query={"match_all": {}},
            size=10_000,
            _source_includes=["job_attempt"],
        )
        return {int(hit["_source"]["job_attempt"]) for hit in response["hits"]["hits"]}

    async def close(self) -> None:
        try:
            aliases = await self.client.indices.get_alias(name=self.alias)
            if aliases:
                await self.client.indices.delete(index=",".join(aliases))
        finally:
            await self.client.close()


class _ControlledBulkIndex:
    alias = "controlled-bulk-segments"

    async def bootstrap(self, model: str, dims: int) -> str:
        assert model == "embedding-it"
        assert dims == _EMBEDDING_DIMS
        return self.alias


class _ControlledBulkClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.partial_failure_once = False
        self.partial_failures = 0

    def options(self, **_kwargs):
        return self

    async def delete_by_query(self, *, query, **_kwargs):
        filters = query.get("bool", {}).get("filter", [])
        terms = {}
        for entry in filters:
            terms.update(entry.get("term", {}))
        terms.update(query.get("term", {}))
        before = len(self.documents)
        self.documents = {
            key: document
            for key, document in self.documents.items()
            if not all(document.get(field) == value for field, value in terms.items())
        }
        return {"deleted": before - len(self.documents), "failures": [], "timed_out": False}

    async def close(self) -> None:
        return None


async def _controlled_streaming_bulk(client, actions, **kwargs):
    assert kwargs == {
        "raise_on_error": False,
        "raise_on_exception": False,
        "refresh": "wait_for",
    }
    action_list = list(actions)
    fail_index = len(action_list) - 1 if client.partial_failure_once else -1
    client.partial_failure_once = False
    for index, action in enumerate(action_list):
        document_id = str(action["_id"])
        if index == fail_index:
            client.partial_failures += 1
            yield False, {"update": {"_id": document_id, "status": 503, "error": {"reason": "injected"}}}
            continue
        document = dict(action["script"]["params"]["document"])
        document["_id"] = document_id
        current = client.documents.get(document_id)
        if current is None or int(current["job_attempt"]) <= int(document["job_attempt"]):
            client.documents[document_id] = document
        yield True, {"update": {"_id": document_id, "status": 200, "result": "updated"}}


class _ControlledBulkProjection:
    def __init__(self) -> None:
        self.client = _ControlledBulkClient()
        self.store = ElasticsearchProjectionStore(self.client, index=_ControlledBulkIndex())

    async def project(self, documents, *, job_id: str, attempt: int) -> ProjectionResult:
        return await self.store.project(documents, job_id=job_id, attempt=attempt)

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        await self.store.delete_projection(asset_id, job_id, attempt)

    async def delete_asset(self, asset_id: str) -> None:
        await self.store.delete_asset(asset_id)

    async def close(self) -> None:
        await self.store.close()


class _FaultInjectingProjection:
    def __init__(self, backend: _MemoryProjection | _ElasticsearchProjection) -> None:
        self.backend = backend
        self.partial_backend = _ControlledBulkProjection()
        self._partial_armed = False
        self._partial_attempts: set[tuple[str, str, int]] = set()
        self.delete_failure_once = False

    async def project(self, documents, *, job_id: str, attempt: int) -> ProjectionResult:
        if self._partial_armed:
            self._partial_armed = False
            self.partial_backend.client.partial_failure_once = True
            asset_id = str(documents[0]["asset_id"])
            self._partial_attempts.add((asset_id, job_id, attempt))
            return await self.partial_backend.project(documents, job_id=job_id, attempt=attempt)
        return await self.backend.project(documents, job_id=job_id, attempt=attempt)

    async def delete_projection(self, asset_id: str, job_id: str, attempt: int) -> None:
        key = (asset_id, job_id, attempt)
        if key in self._partial_attempts:
            await self.partial_backend.delete_projection(asset_id, job_id, attempt)
            self._partial_attempts.remove(key)
            return
        await self.backend.delete_projection(asset_id, job_id, attempt)

    async def delete_asset(self, asset_id: str) -> None:
        if self.delete_failure_once:
            self.delete_failure_once = False
            raise RecordedVideoError(ErrorCode.ES_5XX, retryable=True, message="ES_5XX: injected delete interruption")
        await self.backend.delete_asset(asset_id)
        await self.partial_backend.delete_asset(asset_id)

    def inject_partial_bulk_failure(self) -> None:
        self._partial_armed = True

    @property
    def partial_bulk_failures(self) -> int:
        return self.partial_backend.client.partial_failures

    async def ids(self) -> set[str]:
        return await self.backend.ids()

    async def close(self) -> None:
        await self.backend.close()
        await self.partial_backend.close()


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


@dataclass(frozen=True)
class WorkerCrash:
    abandoned: Job
    recovered: Job
    heartbeat_seen: bool


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
        media: _ControlledMedia,
        pipeline: RecordedVideoPipeline,
    ) -> None:
        self.client = client
        self.repository = repository
        self.store = store
        self.worker = worker
        self.projection = projection
        self.provider = provider
        self.clock = clock
        self.media = media
        self.pipeline = pipeline

    def _worker(self, *, output=lambda _line: None, worker_id: str | None = None) -> RecordedVideoWorker:
        return RecordedVideoWorker(
            repository=self.repository,
            pipeline=self.pipeline,
            worker_concurrency=3,
            lease_sec=2,
            max_attempts=3,
            clock=self.clock,
            output=output,
            worker_id=worker_id,
        )

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

    async def kill_worker(self, job: UploadedJob) -> WorkerCrash:
        self.media.block_next_probe()
        heartbeat = asyncio.Event()

        def capture_event(line: str) -> None:
            if '"event":"job.heartbeat"' in line:
                heartbeat.set()

        crashed_worker = self._worker(output=capture_event, worker_id="crashed-worker")
        task = asyncio.create_task(crashed_worker.run())
        await asyncio.wait_for(self.media.probe_started.wait(), timeout=3)
        await asyncio.wait_for(heartbeat.wait(), timeout=3)
        abandoned = await self.repository.get_job(job.job_id)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.media.reset_probe()
        self.clock.advance(3)
        replacement = self._worker(worker_id="replacement-worker")
        assert await replacement.run_once() is not None
        recovered = await self.repository.get_job(job.job_id)
        return WorkerCrash(abandoned=abandoned, recovered=recovered, heartbeat_seen=heartbeat.is_set())

    async def cancel_running(self, job: UploadedJob) -> tuple[Job, httpx.Response, Job]:
        self.media.block_next_probe()
        task = asyncio.create_task(self.worker.run_once())
        await asyncio.wait_for(self.media.probe_started.wait(), timeout=3)
        running = await self.repository.get_job(job.job_id)
        response = await self.client.post(f"/api/v1/jobs/{job.job_id}/cancel")
        self.media.release_probe()
        cancelled = await asyncio.wait_for(task, timeout=3)
        self.media.reset_probe()
        assert isinstance(cancelled, Job)
        return running, response, cancelled

    def inject_partial_bulk_failure(self) -> None:
        self.projection.inject_partial_bulk_failure()

    @property
    def partial_bulk_failures(self) -> int:
        return self.projection.partial_bulk_failures

    async def projection_attempts(self) -> set[int]:
        return await self.projection.backend.attempts()

    def attempt_files(self, asset_id: str, attempt: int) -> set[str]:
        root = self.store.root / "assets" / asset_id / "derived" / "v1" / "attempts" / str(attempt)
        if not root.exists():
            return set()
        return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}

    async def job_count(self, asset_id: str) -> int:
        with sqlite3.connect(self.repository.database_path) as connection:
            row = connection.execute("SELECT COUNT(*) FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
        assert row is not None
        return int(row[0])

    async def reservation_count(self, session_id: str) -> int:
        with sqlite3.connect(self.repository.database_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM upload_chunks WHERE session_id = ? AND status = 'reserved'",
                (session_id,),
            ).fetchone()
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

    production_streaming_bulk = es_index_module.async_streaming_bulk

    async def streaming_bulk_dispatch(client, actions, **kwargs):
        if isinstance(client, _ControlledBulkClient):
            async for result in _controlled_streaming_bulk(client, actions, **kwargs):
                yield result
            return
        async for result in production_streaming_bulk(client, actions, **kwargs):
            yield result

    monkeypatch.setattr(es_index_module, "async_streaming_bulk", streaming_bulk_dispatch)

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
    media = _ControlledMedia()
    pipeline = RecordedVideoPipeline(
        repository=repository,
        asset_store=store,
        media=media,
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
        media=media,
        pipeline=pipeline,
    )
    try:
        yield stack
    finally:
        await client.aclose()
        await vision.aclose()
        await embedding.aclose()
        await projection.close()
