import logging

from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def test_original_ui_search_preserves_vss_contract(monkeypatch):
    from vsa_agent.api import original_ui_search
    from vsa_agent.api.routes import app
    from vsa_agent.tools.search import SearchOutput, SearchResult

    captured = {}

    async def fake_execute_search(search_input):
        captured["input"] = search_input
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="runtime-validation.mp4",
                    description="forklift near worker",
                    start_time="2026-07-04T08:00:00Z",
                    end_time="2026-07-04T08:00:05Z",
                    sensor_id="camera-runtime-1",
                    similarity=0.91,
                )
            ]
        )

    monkeypatch.setattr(original_ui_search, "execute_search", fake_execute_search)
    client = TestClient(app)
    response = client.post(
        "/api/v1/search",
        json={
            "query": "forklift near worker",
            "top_k": 3,
            "source_type": "video_file",
            "video_sources": ["yard.mp4"],
            "timestamp_start": None,
            "timestamp_end": None,
            "min_cosine_similarity": "0.00",
            "agent_mode": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["video_name"] == "runtime-validation.mp4"
    assert captured["input"].query == "forklift near worker"
    assert captured["input"].top_k == 3
    assert captured["input"].max_results == 3
    assert captured["input"].agent_mode is False
    assert captured["input"].video_sources == ["yard.mp4"]
    assert captured["input"].start_time is None
    assert captured["input"].end_time is None
    assert captured["input"].min_cosine_similarity == 0.0


def test_original_ui_search_route_is_registered():
    from vsa_agent.api.routes import app

    assert "/api/v1/search" in {route.path for route in app.routes}


def test_original_ui_search_returns_controlled_503_for_production_dependency_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    from vsa_agent.api import original_ui_search
    from vsa_agent.api.routes import app
    from vsa_agent.tools.embed_search import SearchDependencyError

    async def fail_closed(_search_input):
        raise SearchDependencyError("production search dependency is unavailable")

    monkeypatch.setattr(original_ui_search, "execute_search", fail_closed)

    response = TestClient(app).post(
        "/api/v1/search",
        json={"query": "forklift near worker", "agent_mode": False},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "production search dependency is unavailable"}


def test_runtime_logging_writes_vsa_info_events_to_stdout(capsys):
    from vsa_agent.api.routes import configure_vsa_runtime_logging

    logger = logging.getLogger("vsa_agent")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    try:
        logger.handlers.clear()
        configure_vsa_runtime_logging()
        logger.info("original_ui.search.request query='forklift near worker'")

        assert "original_ui.search.request" in capsys.readouterr().out
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
