"""Tests for api/video_search_ingest.py."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vsa_agent.config import AppConfig
from vsa_agent.config import SearchBackendConfig


def _client_for_router(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestVideoSearchIngest:
    def test_router_imports(self):
        from vsa_agent.api.video_search_ingest import router

        assert router is not None

    def test_build_ingest_document_normalizes_video_segment_aliases(self):
        from vsa_agent.api.video_search_ingest import _build_ingest_document

        document = _build_ingest_document(
            "video-42",
            {
                "filename": "dock-camera.mp4",
                "caption": "worker walks through loading dock",
                "sensor": {"id": "camera-7"},
                "timestamp": "2026-07-04T09:00:00Z",
                "timestamp_end": "2026-07-04T09:00:04Z",
                "thumbnail_url": "http://example.invalid/thumb.jpg",
                "vector": [0.2, 0.3, 0.4],
                "site": "dock-a",
            },
        )

        assert document == {
            "video_id": "video-42",
            "video_name": "dock-camera.mp4",
            "description": "worker walks through loading dock",
            "sensor_id": "camera-7",
            "start_time": "2026-07-04T09:00:00Z",
            "end_time": "2026-07-04T09:00:04Z",
            "screenshot_url": "http://example.invalid/thumb.jpg",
            "vector": [0.2, 0.3, 0.4],
            "metadata": {
                "filename": "dock-camera.mp4",
                "caption": "worker walks through loading dock",
                "sensor": {"id": "camera-7"},
                "timestamp": "2026-07-04T09:00:00Z",
                "timestamp_end": "2026-07-04T09:00:04Z",
                "thumbnail_url": "http://example.invalid/thumb.jpg",
                "vector": [0.2, 0.3, 0.4],
                "site": "dock-a",
            },
        }

    def test_ingest_skips_when_search_disabled(self, monkeypatch: pytest.MonkeyPatch):
        from vsa_agent.api import video_search_ingest

        def fail_if_es_client_is_created(*args, **kwargs):
            raise AssertionError("Elasticsearch client should not be created when search is disabled")

        monkeypatch.setattr(
            video_search_ingest,
            "get_config",
            lambda: AppConfig(search=SearchBackendConfig(enabled=False, es_endpoint="http://es:9200")),
            raising=False,
        )
        monkeypatch.setattr(video_search_ingest, "AsyncElasticsearch", fail_if_es_client_is_created, raising=False)
        client = _client_for_router(video_search_ingest.router)

        response = client.post("/api/search/ingest", json={"video_id": "video-1", "metadata": {"video_name": "a.mp4"}})

        assert response.status_code == 200
        assert response.json() == {
            "status": "skipped",
            "video_id": "video-1",
            "indexed": False,
            "result_id": None,
        }

    def test_ingest_indexes_document_when_search_enabled(self, monkeypatch: pytest.MonkeyPatch):
        from vsa_agent.api import video_search_ingest

        created_clients = []

        class FakeAsyncElasticsearch:
            def __init__(self, endpoint, request_timeout, verify_certs):
                self.endpoint = endpoint
                self.request_timeout = request_timeout
                self.verify_certs = verify_certs
                self.index_calls = []
                self.closed = False
                created_clients.append(self)

            async def index(self, index, document):
                self.index_calls.append((index, document))
                return {"_id": "es-doc-1", "result": "created"}

            async def close(self):
                self.closed = True

        monkeypatch.setattr(
            video_search_ingest,
            "get_config",
            lambda: AppConfig(
                search=SearchBackendConfig(
                    enabled=True,
                    es_endpoint="http://es:9200",
                    embed_index="video-embeddings",
                    request_timeout_sec=12.5,
                    verify_certs=False,
                )
            ),
            raising=False,
        )
        monkeypatch.setattr(video_search_ingest, "AsyncElasticsearch", FakeAsyncElasticsearch, raising=False)
        client = _client_for_router(video_search_ingest.router)

        response = client.post(
            "/api/search/ingest",
            json={
                "video_id": "video-1",
                "metadata": {
                    "video_name": "risk.mp4",
                    "description": "forklift passes near worker",
                    "sensor_id": "camera-7",
                    "start_time": "2026-07-03T08:00:00Z",
                    "end_time": "2026-07-03T08:00:05Z",
                    "screenshot_url": "http://frames/1.jpg",
                    "vector": [0.1, 0.2, 0.3],
                    "site": "warehouse-a",
                },
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ingested",
            "video_id": "video-1",
            "indexed": True,
            "result_id": "es-doc-1",
        }
        fake_client = created_clients[0]
        assert fake_client.endpoint == "http://es:9200"
        assert fake_client.request_timeout == 12.5
        assert fake_client.verify_certs is False
        assert fake_client.closed is True
        assert fake_client.index_calls[0][0] == "video-embeddings"
        indexed_document = fake_client.index_calls[0][1]
        assert indexed_document["video_id"] == "video-1"
        assert indexed_document["video_name"] == "risk.mp4"
        assert indexed_document["description"] == "forklift passes near worker"
        assert indexed_document["sensor_id"] == "camera-7"
        assert indexed_document["start_time"] == "2026-07-03T08:00:00Z"
        assert indexed_document["end_time"] == "2026-07-03T08:00:05Z"
        assert indexed_document["screenshot_url"] == "http://frames/1.jpg"
        assert indexed_document["vector"] == [0.1, 0.2, 0.3]
        assert indexed_document["metadata"]["site"] == "warehouse-a"

    def test_ingest_returns_502_when_elasticsearch_fails(self, monkeypatch: pytest.MonkeyPatch):
        from vsa_agent.api import video_search_ingest

        class FailingAsyncElasticsearch:
            def __init__(self, *args, **kwargs):
                pass

            async def index(self, index, document):
                raise RuntimeError("index rejected")

            async def close(self):
                pass

        monkeypatch.setattr(
            video_search_ingest,
            "get_config",
            lambda: AppConfig(
                search=SearchBackendConfig(
                    enabled=True,
                    es_endpoint="http://es:9200",
                    embed_index="video-embeddings",
                )
            ),
            raising=False,
        )
        monkeypatch.setattr(video_search_ingest, "AsyncElasticsearch", FailingAsyncElasticsearch, raising=False)
        client = _client_for_router(video_search_ingest.router)

        response = client.post("/api/search/ingest", json={"video_id": "video-1", "metadata": {}})

        assert response.status_code == 502
        assert "Elasticsearch indexing failed" in response.json()["detail"]

    def test_ingest_route_is_registered_on_app(self):
        from vsa_agent.api.routes import app

        route_paths = {route.path for route in app.routes}

        assert "/api/search/ingest" in route_paths
