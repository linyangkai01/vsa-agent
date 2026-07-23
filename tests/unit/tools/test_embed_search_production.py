from __future__ import annotations

import pytest

from vsa_agent.config import AppConfig, SearchBackendConfig
from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient
from vsa_agent.tools import embed_search


class ForbiddenFallbackStore:
    async def search(self, *, query: str, top_k: int):
        raise AssertionError(f"production fallback was called for {query!r}, top_k={top_k}")


class FakeIndices:
    async def exists(self, *, index: str) -> bool:
        assert index == "vsa-video-segments"
        return True


class FakeES:
    def __init__(self, hits: list[dict[str, object]]) -> None:
        self.indices = FakeIndices()
        self.hits = hits
        self.search_calls: list[tuple[str, dict[str, object]]] = []
        self.options_calls: list[dict[str, object]] = []
        self.closed = False

    def options(self, **kwargs):
        self.options_calls.append(kwargs)
        return self

    async def search(self, *, index: str, body: dict[str, object]):
        self.search_calls.append((index, body))
        return {"hits": {"hits": self.hits}}

    async def close(self) -> None:
        self.closed = True


class ReadyRepository:
    def __init__(self, ready_attempt: int = 2) -> None:
        self.ready_attempt = ready_attempt
        self.calls: list[tuple[str, str, str, int]] = []

    async def is_asset_search_ready(
        self,
        asset_id: str,
        job_id: str,
        pipeline_version: str,
        attempt: int,
    ) -> bool:
        self.calls.append((asset_id, job_id, pipeline_version, attempt))
        return attempt == self.ready_attempt


def _hit(*, attempt: int, score: float = 1.9) -> dict[str, object]:
    asset_id = "92db3bce-5caa-4d57-80ba-789851d2345b"
    return {
        "_score": score,
        "_source": {
            "asset_id": asset_id,
            "video_id": asset_id,
            "segment_id": f"segment-{attempt}",
            "sensor_id": asset_id,
            "source_type": "recorded_video",
            "job_id": "job-1",
            "job_attempt": attempt,
            "readiness": {
                "asset_id": asset_id,
                "job_id": "job-1",
                "pipeline_version": "v1",
                "attempt": attempt,
                "authority": "sqlite",
            },
            "pipeline_version": "v1",
            "video_name": "yard.mp4",
            "description": "forklift near worker",
            "start_time": "2026-07-14T08:00:00Z",
            "end_time": "2026-07-14T08:00:05Z",
            "screenshot_url": f"/api/v1/videos/{asset_id}/segments/segment-{attempt}/thumbnail",
        },
    }


@pytest.mark.asyncio
async def test_production_es_failure_never_uses_mock_or_store(monkeypatch) -> None:
    async def failing_search(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("https://user:secret@es.invalid private response")

    monkeypatch.setattr(
        "vsa_agent.config.get_config",
        lambda: AppConfig(
            search=SearchBackendConfig(
                enabled=True,
                es_endpoint="http://es:9200",
                allow_mock_fallback=False,
                force_mock_embedding=False,
            )
        ),
    )
    monkeypatch.setattr(embed_search, "_search_real_es", failing_search)

    with pytest.raises(Exception) as caught:
        await embed_search.embed_search_tool(
            "forklift near worker",
            store=ForbiddenFallbackStore(),
            top_k=3,
        )

    assert type(caught.value).__name__ == "SearchDependencyError"
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_production_embedding_failure_is_controlled_and_never_generates_mock(monkeypatch) -> None:
    class FailingEmbedClient:
        async def embed_query(self, query: str):
            del query
            raise RuntimeError("Authorization: Bearer secret")

    fake_es = FakeES([])
    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=False,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(embed_search, "_create_default_embed_client", lambda: FailingEmbedClient())

    with pytest.raises(Exception) as caught:
        await embed_search._search_real_es(
            "forklift near worker",
            3,
            config,
            readiness_repository=ReadyRepository(),
        )

    assert type(caught.value).__name__ == "SearchDependencyError"
    assert "secret" not in str(caught.value)
    assert fake_es.search_calls == []
    assert fake_es.closed is True


@pytest.mark.asyncio
async def test_production_search_passes_fail_closed_policy_to_default_embed_client(monkeypatch) -> None:
    fake_es = FakeES([])
    received_policy: list[bool] = []

    class FailingEmbedClient:
        async def embed_query(self, query: str):
            del query
            raise RuntimeError("Authorization: Bearer secret")

    def create_embed_client(*, allow_mock_fallback: bool):
        received_policy.append(allow_mock_fallback)
        return FailingEmbedClient()

    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=False,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(embed_search, "_create_default_embed_client", create_embed_client)

    with pytest.raises(embed_search.SearchDependencyError):
        await embed_search._search_real_es(
            "forklift near worker",
            3,
            config,
            readiness_repository=ReadyRepository(),
        )

    assert received_policy == [False]


@pytest.mark.asyncio
async def test_rtvi_embed_client_can_disable_its_internal_mock_fallback() -> None:
    class FailingEmbeddings:
        async def create(self, **kwargs):
            del kwargs
            raise RuntimeError("Authorization: Bearer secret")

    class FailingOpenAIClient:
        embeddings = FailingEmbeddings()

    client = RTVICVEmbedClient(
        base_url="http://embedding.invalid",
        api_key="test-key",
        allow_mock_fallback=False,
    )
    client._client = FailingOpenAIClient()

    with pytest.raises(RuntimeError, match="embedding request failed"):
        await client.embed_query("forklift near worker")


@pytest.mark.asyncio
async def test_production_search_filters_every_hit_through_sqlite_readiness(monkeypatch) -> None:
    fake_es = FakeES([_hit(attempt=1, score=1.95), _hit(attempt=2, score=1.8)])
    readiness = ReadyRepository(ready_attempt=2)

    class EmbedClient:
        async def embed_query(self, query: str):
            assert query == "forklift near worker"
            return [0.1, 0.2, 0.3]

    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=False,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(embed_search, "_create_default_embed_client", lambda **_: EmbedClient())

    output = await embed_search._search_real_es(
        "forklift near worker",
        10,
        config,
        readiness_repository=readiness,
        video_sources=["yard.mp4"],
        timestamp_start="2026-07-14T07:59:00Z",
        timestamp_end="2026-07-14T08:01:00Z",
        source_type="video_file",
        min_cosine_similarity=0.2,
    )

    assert [result.video_name for result in output.data] == ["yard.mp4"]
    assert output.data[0].sensor_id == "92db3bce-5caa-4d57-80ba-789851d2345b"
    assert output.data[0].start_time == "2026-07-14T08:00:00Z"
    assert output.data[0].screenshot_url.endswith("segment-2/thumbnail")
    assert [call[-1] for call in readiness.calls] == [1, 2]
    _, body = fake_es.search_calls[0]
    filters = body["query"]["script_score"]["query"]["bool"]["filter"]
    assert {"term": {"source_type": "recorded_video"}} in filters
    assert {"terms": {"video_name": ["yard.mp4"]}} in filters
    assert {"range": {"end_time": {"gte": "2026-07-14T07:59:00Z"}}} in filters
    assert {"range": {"start_time": {"lte": "2026-07-14T08:01:00Z"}}} in filters
    assert body["query"]["script_score"]["min_score"] == 1.2
    assert fake_es.options_calls == [{"headers": {"accept": "application/json", "content-type": "application/json"}}]
    assert fake_es.closed is True


@pytest.mark.asyncio
async def test_production_search_fails_closed_when_hit_readiness_is_malformed(monkeypatch) -> None:
    malformed_hit = _hit(attempt=2)
    malformed_hit["_source"]["readiness"] = {"asset_id": "not-the-top-level-asset"}
    fake_es = FakeES([malformed_hit])

    class EmbedClient:
        async def embed_query(self, query: str):
            assert query == "forklift near worker"
            return [0.1, 0.2, 0.3]

    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=False,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(embed_search, "_create_default_embed_client", lambda **_: EmbedClient())

    with pytest.raises(embed_search.SearchDependencyError):
        await embed_search._search_real_es(
            "forklift near worker",
            10,
            config,
            readiness_repository=ReadyRepository(),
        )

    assert fake_es.closed is True


@pytest.mark.asyncio
async def test_production_search_rejects_non_sqlite_readiness_authority(monkeypatch) -> None:
    malformed_hit = _hit(attempt=2)
    malformed_hit["_source"]["readiness"]["authority"] = "untrusted"
    fake_es = FakeES([malformed_hit])

    class EmbedClient:
        async def embed_query(self, query: str):
            assert query == "forklift near worker"
            return [0.1, 0.2, 0.3]

    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=False,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(embed_search, "_create_default_embed_client", lambda **_: EmbedClient())

    with pytest.raises(embed_search.SearchDependencyError):
        await embed_search._search_real_es(
            "forklift near worker",
            10,
            config,
            readiness_repository=ReadyRepository(),
        )

    assert fake_es.closed is True


@pytest.mark.asyncio
async def test_explicit_smoke_profile_can_read_legacy_index_without_sqlite(monkeypatch) -> None:
    class LegacyIndices:
        async def exists(self, *, index: str) -> bool:
            return index.endswith("-legacy-smoke")

    fake_es = FakeES([_hit(attempt=2)])
    fake_es.indices = LegacyIndices()
    config = SearchBackendConfig(
        enabled=True,
        es_endpoint="http://es:9200",
        embed_index="vsa-video-segments",
        allow_mock_fallback=True,
        force_mock_embedding=True,
    )
    monkeypatch.setattr(embed_search, "_create_es_client", lambda _config: fake_es)
    monkeypatch.setattr(
        embed_search,
        "_create_readiness_repository",
        lambda: (_ for _ in ()).throw(embed_search.SearchDependencyError("database unavailable")),
    )

    output = await embed_search._search_real_es("forklift", 1, config)

    assert output.data[0].video_name == "yard.mp4"
    assert fake_es.search_calls[0][0] == "vsa-video-segments-legacy-smoke"
