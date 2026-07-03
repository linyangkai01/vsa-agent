"""Tests for tools/embed_search.py."""
from vsa_agent.tools.embed_search import (
    EmbedSearchResultItem, EmbedSearchOutput, QueryInput,
    _build_es_query, _generate_query_embedding, _process_search_hit,
)
from vsa_agent.tools.search import SearchOutput

class TestEmbedSearchResultItem:
    def test_defaults(self):
        item = EmbedSearchResultItem()
        assert item.video_name == ""
        assert item.similarity_score == 0.0

class TestEmbedSearchOutput:
    def test_defaults(self):
        out = EmbedSearchOutput()
        assert out.results == []

class TestQueryInput:
    def test_defaults(self):
        qi = QueryInput()
        assert qi.source_type == "video_file"

class TestGenerateQueryEmbedding:
    async def test_with_query_text(self):
        qi = QueryInput(params={"query": "test query"})
        result = await _generate_query_embedding(qi)
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_empty_query(self):
        qi = QueryInput(params={"query": ""})
        result = await _generate_query_embedding(qi)
        assert result == []

class TestProcessSearchHit:
    async def test_basic_hit(self):
        hit = {"_score": 1.9, "_source": {"sensor": {"id": "s1", "description": "cam1"}, "timestamp": "t1", "end": "t2"}}
        result = await _process_search_hit(hit)
        assert result is not None
        assert result.sensor_id == "s1"
        assert result.similarity_score == 0.9  # score=1.9 -> similarity = 1.9 - 1.0 = 0.9

    async def test_below_threshold(self):
        hit = {"_score": 0.1, "_source": {"sensor": {"id": "s1"}}}
        result = await _process_search_hit(hit, min_cosine_similarity=0.5)
        assert result is None

    async def test_extracts_common_real_es_source_shapes(self):
        hit = {
            "_score": 1.83,
            "_source": {
                "sensor_id": "camera-7",
                "video_name": "site-a.mp4",
                "description": "worker enters restricted zone",
                "start_time": "2026-07-03T08:00:00Z",
                "end_time": "2026-07-03T08:00:05Z",
                "screenshot_url": "http://frames/1.jpg",
            },
        }

        result = await _process_search_hit(hit)

        assert result is not None
        assert result.video_name == "site-a.mp4"
        assert result.sensor_id == "camera-7"
        assert result.description == "worker enters restricted zone"
        assert result.start_time == "2026-07-03T08:00:00Z"
        assert result.end_time == "2026-07-03T08:00:05Z"
        assert result.screenshot_url == "http://frames/1.jpg"


class TestBuildEsQuery:
    def test_uses_configured_vector_field(self):
        query = _build_es_query(
            QueryInput(params={"query": "forklift near worker"}),
            [0.1, 0.2, 0.3],
            "video-index",
            top_k=3,
            min_cosine_similarity=0.25,
            vector_field="embedding.vector",
        )

        script = query["query"]["script_score"]["script"]
        assert "embedding.vector" in script["source"]
        assert script["params"]["query_vector"] == [0.1, 0.2, 0.3]
        assert query["query"]["script_score"]["min_score"] == 1.25


class TestEmbedSearchToolWithRealEs:
    async def test_uses_configured_es_and_embedding_client(self, monkeypatch):
        from vsa_agent.config import AppConfig, SearchBackendConfig
        from vsa_agent.tools import embed_search

        class FakeIndices:
            async def exists(self, index):
                assert index == "video-embeddings"
                return True

        class FakeES:
            def __init__(self):
                self.indices = FakeIndices()
                self.search_calls = []
                self.closed = False

            async def search(self, index, body):
                self.search_calls.append((index, body))
                return {
                    "hits": {
                        "hits": [
                            {
                                "_score": 1.91,
                                "_source": {
                                    "sensor_id": "cam-1",
                                    "video_name": "risk.mp4",
                                    "description": "forklift passes close to worker",
                                    "start_time": "2026-07-03T08:00:00Z",
                                    "end_time": "2026-07-03T08:00:06Z",
                                },
                            }
                        ]
                    }
                }

            async def close(self):
                self.closed = True

        class FakeEmbedClient:
            async def embed_query(self, query):
                assert query == "forklift near worker"
                return [0.1, 0.2, 0.3]

        fake_es = FakeES()
        monkeypatch.setattr(
            "vsa_agent.config.get_config",
            lambda: AppConfig(
                search=SearchBackendConfig(
                    enabled=True,
                    es_endpoint="http://es:9200",
                    embed_index="video-embeddings",
                    vector_field="embedding.vector",
                    embed_confidence_threshold=0.2,
                )
            ),
        )
        monkeypatch.setattr(embed_search, "_create_es_client", lambda _cfg: fake_es)
        monkeypatch.setattr(embed_search, "_create_default_embed_client", lambda: FakeEmbedClient())

        output = await embed_search.embed_search_tool("forklift near worker", top_k=3)

        assert isinstance(output, SearchOutput)
        assert output.data[0].video_name == "risk.mp4"
        assert output.data[0].similarity == 0.91
        assert fake_es.search_calls[0][0] == "video-embeddings"
        assert "embedding.vector" in fake_es.search_calls[0][1]["query"]["script_score"]["script"]["source"]
        assert fake_es.closed is True
