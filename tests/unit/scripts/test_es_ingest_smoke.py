import json

import pytest

from scripts.es_ingest_smoke import find_indexed_document
from scripts.es_ingest_smoke import mock_query_vector
from scripts.es_ingest_smoke import _parse_args
from scripts.es_ingest_smoke import post_ingest
from scripts.es_ingest_smoke import post_original_ui_search
from scripts.es_ingest_smoke import sample_payload
from scripts.es_ingest_smoke import search_indexed_document
from scripts.es_ingest_smoke import validate_indexed_document
from scripts.es_ingest_smoke import validate_ingest_response


def test_sample_payload_contains_required_metadata():
    payload = sample_payload("runtime-video-1", "forklift near worker")

    assert payload["video_id"] == "runtime-video-1"
    metadata = payload["metadata"]
    assert metadata["video_name"] == "runtime-validation.mp4"
    assert metadata["description"] == "forklift passes near worker in loading zone"
    assert metadata["sensor_id"] == "camera-runtime-1"
    assert metadata["start_time"] == "2026-07-04T08:00:00Z"
    assert metadata["end_time"] == "2026-07-04T08:00:05Z"
    assert metadata["screenshot_url"] == "http://example.invalid/frames/runtime-validation.jpg"
    assert metadata["vector"] == mock_query_vector("forklift near worker")


def test_default_smoke_video_id_is_stable():
    args = _parse_args(["--es-endpoint", "http://es:9200"])

    assert args.video_id == "runtime-validation-video"


def test_validate_ingest_response_returns_result_id():
    result_id = validate_ingest_response(
        {"status": "ingested", "video_id": "runtime-video-1", "indexed": True, "result_id": "abc123"},
        expected_video_id="runtime-video-1",
    )

    assert result_id == "abc123"


def test_validate_ingest_response_rejects_skipped_status():
    try:
        validate_ingest_response(
            {"status": "skipped", "video_id": "runtime-video-1", "indexed": False, "result_id": None},
            expected_video_id="runtime-video-1",
        )
    except RuntimeError as exc:
        assert "Expected ingested/indexed response" in str(exc)
    else:
        raise AssertionError("validate_ingest_response should reject skipped responses")


def test_validate_indexed_document_accepts_required_fields():
    validate_indexed_document(
        {
            "video_id": "runtime-video-1",
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": mock_query_vector("forklift near worker"),
            "metadata": {"site": "runtime-yard"},
        },
        expected_video_id="runtime-video-1",
    )


def test_validate_indexed_document_rejects_wrong_video_id():
    try:
        validate_indexed_document({"video_id": "other", "metadata": {}}, expected_video_id="runtime-video-1")
    except RuntimeError as exc:
        assert "video_id" in str(exc)
    else:
        raise AssertionError("validate_indexed_document should reject mismatched video_id")


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_post_ingest_posts_json_to_ingest_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        captured["content_type"] = request.headers["Content-type"]
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"status": "ingested", "video_id": "runtime-video-1", "indexed": True, "result_id": "abc123"})

    monkeypatch.setattr("scripts.es_ingest_smoke.urlopen", fake_urlopen)

    response = post_ingest("http://127.0.0.1:8000", {"video_id": "runtime-video-1"}, timeout_sec=7.5)

    assert response["result_id"] == "abc123"
    assert captured == {
        "url": "http://127.0.0.1:8000/api/search/ingest",
        "timeout": 7.5,
        "method": "POST",
        "content_type": "application/json",
        "body": {"video_id": "runtime-video-1"},
    }


def test_post_original_ui_search_posts_vss_contract(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"data": [{"video_name": "runtime-validation.mp4"}]})

    monkeypatch.setattr("scripts.es_ingest_smoke.urlopen", fake_urlopen)

    response = post_original_ui_search("http://127.0.0.1:8000", "forklift near worker", 1, 7.5)

    assert response["data"][0]["video_name"] == "runtime-validation.mp4"
    assert captured == {
        "url": "http://127.0.0.1:8000/api/v1/search",
        "timeout": 7.5,
        "body": {"query": "forklift near worker", "top_k": 1, "source_type": "video_file", "agent_mode": False},
    }


@pytest.mark.asyncio
async def test_find_indexed_document_refreshes_and_uses_match_fallback(monkeypatch):
    created_clients = []

    class FakeIndices:
        def __init__(self):
            self.refreshed = []

        async def refresh(self, index):
            self.refreshed.append(index)

    class FakeAsyncElasticsearch:
        def __init__(self, endpoint, request_timeout, verify_certs):
            self.endpoint = endpoint
            self.request_timeout = request_timeout
            self.verify_certs = verify_certs
            self.indices = FakeIndices()
            self.search_bodies = []
            self.closed = False
            created_clients.append(self)

        async def search(self, index, body):
            self.search_bodies.append((index, body))
            if "term" in body["query"]:
                return {"hits": {"hits": []}}
            return {"hits": {"hits": [{"_source": {"video_id": "runtime-video-1", "metadata": {"site": "runtime-yard"}}}]}}

        async def close(self):
            self.closed = True

    monkeypatch.setattr("scripts.es_ingest_smoke.AsyncElasticsearch", FakeAsyncElasticsearch)

    document = await find_indexed_document(
        "http://es:9200",
        index="vsa-video-embeddings",
        video_id="runtime-video-1",
        timeout_sec=9.5,
        verify_certs=False,
    )

    fake_client = created_clients[0]
    assert document["video_id"] == "runtime-video-1"
    assert fake_client.endpoint == "http://es:9200"
    assert fake_client.request_timeout == 9.5
    assert fake_client.verify_certs is False
    assert fake_client.indices.refreshed == ["vsa-video-embeddings"]
    assert fake_client.search_bodies == [
        ("vsa-video-embeddings", {"query": {"term": {"video_id.keyword": "runtime-video-1"}}, "size": 1}),
        ("vsa-video-embeddings", {"query": {"match": {"video_id": "runtime-video-1"}}, "size": 1}),
    ]
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_find_indexed_document_raises_when_missing(monkeypatch):
    class FakeIndices:
        async def refresh(self, index):
            pass

    class FakeAsyncElasticsearch:
        def __init__(self, *args, **kwargs):
            self.indices = FakeIndices()

        async def search(self, index, body):
            return {"hits": {"hits": []}}

        async def close(self):
            pass

    monkeypatch.setattr("scripts.es_ingest_smoke.AsyncElasticsearch", FakeAsyncElasticsearch)

    with pytest.raises(RuntimeError, match="Indexed document not found"):
        await find_indexed_document(
            "http://es:9200",
            index="vsa-video-embeddings",
            video_id="runtime-video-1",
            timeout_sec=30.0,
            verify_certs=True,
        )


@pytest.mark.asyncio
async def test_search_indexed_document_uses_description_match(monkeypatch):
    created_clients = []

    class FakeAsyncElasticsearch:
        def __init__(self, endpoint, request_timeout, verify_certs):
            self.endpoint = endpoint
            self.request_timeout = request_timeout
            self.verify_certs = verify_certs
            self.search_bodies = []
            self.closed = False
            created_clients.append(self)

        async def search(self, index, body):
            self.search_bodies.append((index, body))
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "video_id": "runtime-video-1",
                                "description": "forklift passes near worker in loading zone",
                            }
                        }
                    ]
                }
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr("scripts.es_ingest_smoke.AsyncElasticsearch", FakeAsyncElasticsearch)

    document = await search_indexed_document(
        "http://es:9200",
        index="vsa-video-embeddings",
        video_id="runtime-video-1",
        query="forklift worker",
        timeout_sec=5.0,
        verify_certs=False,
    )

    assert document["video_id"] == "runtime-video-1"
    assert created_clients[0].endpoint == "http://es:9200"
    assert created_clients[0].request_timeout == 5.0
    assert created_clients[0].verify_certs is False
    assert created_clients[0].search_bodies == [
        (
            "vsa-video-embeddings",
            {
                "query": {
                    "bool": {
                        "must": [{"multi_match": {
                            "query": "forklift worker",
                            "fields": ["description", "video_name", "sensor_id", "metadata.description", "metadata.site"],
                        }}],
                        "filter": [{"term": {"video_id.keyword": "runtime-video-1"}}],
                    }
                },
                "size": 1,
            },
        )
    ]
    assert created_clients[0].closed is True
