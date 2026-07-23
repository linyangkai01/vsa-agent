"""Production dependency composition for the recorded-video worker."""

from elasticsearch import AsyncElasticsearch

from vsa_agent.config import AppConfig, resolve_runtime_config, validate_recorded_video_runtime
from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.es_index import ElasticsearchProjectionStore, RecordedVideoIndex
from vsa_agent.recorded_video.media import MediaProcessor
from vsa_agent.recorded_video.pipeline import RecordedVideoPipeline
from vsa_agent.recorded_video.providers import OpenAIEmbeddingProvider, OpenAIVisionProvider
from vsa_agent.recorded_video.repository import JobRepository
from vsa_agent.recorded_video.segmenter import FixedDurationSegmenter
from vsa_agent.recorded_video.worker import RecordedVideoWorker

_PROMPT_VERSION = "recorded-video-prompt-v1"


def build_recorded_video_worker(config: AppConfig) -> RecordedVideoWorker:
    """Build the fail-closed production worker from validated application config."""
    diagnostics = validate_recorded_video_runtime(config)
    search = config.search
    if not config.recorded_video.enabled or not diagnostics.ok or not search.enabled or not search.es_endpoint.strip():
        raise ValueError("recorded-video worker dependencies are not ready")

    runtime = resolve_runtime_config(config)
    if runtime.embedding is None:
        raise ValueError("recorded-video worker dependencies are not ready")

    recorded_video = config.recorded_video
    repository = JobRepository(
        recorded_video.data_root / "recorded-video.sqlite3",
        lease_seconds=recorded_video.lease_sec,
        allowed_snapshot_models={runtime.vlm.model, runtime.embedding.model},
    )
    asset_store = LocalAssetStore(recorded_video.data_root, cleanup_repository=repository)
    media = MediaProcessor(
        asset_store,
        ffmpeg_path=recorded_video.ffmpeg_path,
        ffprobe_path=recorded_video.ffprobe_path,
    )
    segmenter = FixedDurationSegmenter(recorded_video.segment_duration_sec)
    vision = OpenAIVisionProvider(
        base_url=runtime.vlm.base_url,
        api_key=runtime.vlm.api_key,
        model=runtime.vlm.model,
        timeout_sec=search.request_timeout_sec,
        concurrency=recorded_video.provider_concurrency,
    )
    embedding = OpenAIEmbeddingProvider(
        base_url=runtime.embedding.base_url,
        api_key=runtime.embedding.api_key,
        model=runtime.embedding.model,
        timeout_sec=search.request_timeout_sec,
        concurrency=recorded_video.provider_concurrency,
    )
    es_client = AsyncElasticsearch(
        search.es_endpoint,
        request_timeout=search.request_timeout_sec,
        verify_certs=search.verify_certs,
    )
    projection = ElasticsearchProjectionStore(
        es_client,
        index=RecordedVideoIndex(es_client, alias=search.embed_index),
    )
    segmenter_version = f"fixed-{recorded_video.segment_duration_sec}s-v1"
    pipeline = RecordedVideoPipeline(
        repository=repository,
        asset_store=asset_store,
        media=media,
        segmenter=segmenter,
        vision=vision,
        embedding=embedding,
        projection=projection,
        expected_embedding_dims=search.embedding_dimensions,
        representative_frames=recorded_video.representative_frames,
        prompt_version=_PROMPT_VERSION,
        segmenter_version=segmenter_version,
    )
    return RecordedVideoWorker(
        repository=repository,
        pipeline=pipeline,
        worker_concurrency=recorded_video.worker_concurrency,
        lease_sec=recorded_video.lease_sec,
        max_attempts=recorded_video.max_attempts,
    )
