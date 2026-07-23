from pathlib import Path

import pytest

from vsa_agent.config import (
    AppConfig,
    BackendConfig,
    ProfileConfig,
    RecordedVideoConfig,
    RoleBindingConfig,
    SearchBackendConfig,
)
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.es_index import ElasticsearchProjectionStore
from vsa_agent.recorded_video.media import MediaProcessor
from vsa_agent.recorded_video.pipeline import RecordedVideoPipeline
from vsa_agent.recorded_video.providers import OpenAIEmbeddingProvider, OpenAIVisionProvider
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter
from vsa_agent.recorded_video.worker import RecordedVideoWorker, run_configured_worker


@pytest.fixture(autouse=True)
def _production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("PROVIDER_API_KEY", "secret-not-for-logs")


def _production_config(tmp_path: Path, *, enabled: bool = True) -> AppConfig:
    return AppConfig(
        active_profile="production",
        backends={
            "models": BackendConfig(
                provider="openai_compatible",
                base_url="https://models.example/v1",
                api_key_env="PROVIDER_API_KEY",
                api_key_required=True,
            )
        },
        profiles={
            "production": ProfileConfig(
                llm=RoleBindingConfig(backend="models", model="llm-model"),
                vlm=RoleBindingConfig(backend="models", model="vision-model"),
                embedding=RoleBindingConfig(backend="models", model="embedding-model"),
            )
        },
        recorded_video=RecordedVideoConfig(
            enabled=enabled,
            data_root=tmp_path,
            segment_duration_sec=17,
            representative_frames=3,
            worker_concurrency=2,
            provider_concurrency=1,
            lease_sec=45,
            max_attempts=4,
            ffmpeg_path="/opt/media/bin/ffmpeg",
            ffprobe_path="/opt/media/bin/ffprobe",
        ),
        search=SearchBackendConfig(
            enabled=True,
            es_endpoint="http://127.0.0.1:9200",
            embed_index="recorded-video-production",
            embedding_dimensions=768,
            verify_certs=False,
            allow_mock_fallback=False,
            force_mock_embedding=False,
        ),
    )


def test_build_recorded_video_worker_composes_production_dependencies(
    tmp_path: Path,
) -> None:
    from vsa_agent.recorded_video.composition import build_recorded_video_worker

    worker = build_recorded_video_worker(_production_config(tmp_path))

    assert isinstance(worker, RecordedVideoWorker)
    assert isinstance(worker._repository, JobRepository)
    assert worker._repository.database_path == tmp_path / "recorded-video.sqlite3"
    assert isinstance(worker._pipeline, RecordedVideoPipeline)
    assert isinstance(worker._pipeline._asset_store, LocalAssetStore)
    assert worker._pipeline._asset_store.root == tmp_path.resolve()
    assert isinstance(worker._pipeline._media, MediaProcessor)
    assert worker._pipeline._media._ffmpeg_path == "/opt/media/bin/ffmpeg"
    assert worker._pipeline._media._ffprobe_path == "/opt/media/bin/ffprobe"
    assert isinstance(worker._pipeline._segmenter, FixedDurationSegmenter)
    assert isinstance(worker._pipeline._vision, OpenAIVisionProvider)
    assert isinstance(worker._pipeline._embedding, OpenAIEmbeddingProvider)
    assert isinstance(worker._pipeline._projection, ElasticsearchProjectionStore)
    assert worker._pipeline._expected_embedding_dims == 768
    assert worker._pipeline._representative_frames == 3
    assert worker._worker_concurrency == 2
    assert worker._pipeline._vision._concurrency == 1
    assert worker._pipeline._embedding._concurrency == 1
    assert worker._lease_sec == 45
    assert worker._max_attempts == 4


def test_build_recorded_video_worker_fails_closed_for_invalid_runtime(
    tmp_path: Path,
) -> None:
    from vsa_agent.recorded_video.composition import build_recorded_video_worker

    with pytest.raises(ValueError, match="dependencies are not ready"):
        build_recorded_video_worker(_production_config(tmp_path, enabled=False))


@pytest.mark.asyncio
async def test_configured_worker_uses_default_composition_when_factory_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _production_config(tmp_path)
    ran: list[bool] = []

    class StubWorker:
        async def run(self) -> None:
            ran.append(True)

        def stop(self) -> None:
            return None

    monkeypatch.setattr(AppConfig, "from_yaml", lambda _path: config)
    monkeypatch.setattr(
        "vsa_agent.recorded_video.composition.build_recorded_video_worker",
        lambda _config: StubWorker(),
    )

    assert await run_configured_worker(tmp_path / "config.yaml") == 0
    assert ran == [True]


@pytest.mark.asyncio
async def test_configured_worker_preserves_explicit_factory_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _production_config(tmp_path)
    factories: list[str] = []

    class StubWorker:
        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    monkeypatch.setattr(AppConfig, "from_yaml", lambda _path: config)
    monkeypatch.setattr(
        "vsa_agent.recorded_video.composition.build_recorded_video_worker",
        lambda _config: factories.append("default"),
        raising=False,
    )

    result = await run_configured_worker(
        tmp_path / "config.yaml",
        worker_factory=lambda _config: factories.append("explicit") or StubWorker(),
    )

    assert result == 0
    assert factories == ["explicit"]


@pytest.mark.asyncio
async def test_worker_initializes_repository_before_first_claim() -> None:
    events: list[str] = []

    class InitializingRepository:
        async def initialize(self) -> None:
            events.append("initialize")

        async def claim_due_job(self, _owner: str, _now: object) -> None:
            events.append("claim")
            worker.stop()
            return None

    class UnusedPipeline:
        async def run(self, _job: object) -> None:
            raise AssertionError("no job should be claimed")

    worker = RecordedVideoWorker(
        repository=InitializingRepository(),  # type: ignore[arg-type]
        pipeline=UnusedPipeline(),  # type: ignore[arg-type]
        worker_concurrency=1,
        lease_sec=30,
        max_attempts=2,
    )

    await worker.run()

    assert events == ["initialize", "claim"]
