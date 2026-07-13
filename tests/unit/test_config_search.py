from vsa_agent.config import AppConfig, SearchBackendConfig


def test_search_backend_config_defaults_to_disabled():
    cfg = AppConfig()

    assert cfg.search.enabled is False
    assert cfg.search.es_endpoint == ""
    assert cfg.search.embed_index == "vsa-video-embeddings"
    assert cfg.search.force_mock_embedding is False


def test_search_backend_config_accepts_real_es_settings():
    cfg = AppConfig(
        search=SearchBackendConfig(
            enabled=True,
            es_endpoint="http://localhost:9200",
            embed_index="video-embeddings",
            behavior_index="video-behavior",
            frames_index="video-frames",
            vector_field="embedding.vector",
        )
    )

    assert cfg.search.enabled is True
    assert cfg.search.es_endpoint == "http://localhost:9200"
    assert cfg.search.vector_field == "embedding.vector"


def test_search_backend_config_allows_temporary_mock_embedding_override():
    cfg = SearchBackendConfig(force_mock_embedding=True)

    assert cfg.force_mock_embedding is True
