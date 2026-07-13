"""Video search ingest endpoint - submits a video for indexing."""

from typing import Any

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from vsa_agent.config import SearchBackendConfig, get_config

router = APIRouter(prefix="/api", tags=["search"])


class VideoSearchIngestRequest(BaseModel):
    video_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoSearchIngestResponse(BaseModel):
    status: str
    video_id: str
    indexed: bool
    result_id: str | None = None


def _build_ingest_document(video_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    source = dict(metadata)
    sensor = source.get("sensor", {})
    if not isinstance(sensor, dict):
        sensor = {}

    return {
        "video_id": video_id,
        "video_name": source.get("video_name")
        or source.get("filename")
        or source.get("file_name")
        or source.get("videoPath")
        or source.get("video_path")
        or "",
        "description": source.get("description")
        or source.get("caption")
        or source.get("summary")
        or source.get("text")
        or sensor.get("description")
        or "",
        "sensor_id": source.get("sensor_id")
        or source.get("sensorId")
        or source.get("camera_id")
        or sensor.get("id")
        or "",
        "start_time": source.get("start_time") or source.get("timestamp") or source.get("start") or "",
        "end_time": source.get("end_time") or source.get("timestamp_end") or source.get("end") or "",
        "screenshot_url": source.get("screenshot_url") or source.get("thumbnail_url") or "",
        "vector": source.get("vector", []),
        "metadata": source,
    }


def _create_es_client(search_config: SearchBackendConfig) -> AsyncElasticsearch:
    return AsyncElasticsearch(
        search_config.es_endpoint,
        request_timeout=search_config.request_timeout_sec,
        verify_certs=search_config.verify_certs,
    )


async def _ensure_embed_index(es_client: AsyncElasticsearch, index: str, document: dict[str, Any]) -> None:
    vector = document.get("vector")
    if not isinstance(vector, list) or not vector:
        return
    if await es_client.indices.exists(index=index):
        return
    await es_client.indices.create(
        index=index,
        mappings={"properties": {"vector": {"type": "dense_vector", "dims": len(vector)}}},
    )


@router.post("/search/ingest")
async def video_search_ingest(request: VideoSearchIngestRequest) -> VideoSearchIngestResponse:
    """Submit a video for search indexing."""
    search_config = get_config().search
    if not search_config.enabled or not search_config.es_endpoint:
        return VideoSearchIngestResponse(status="skipped", video_id=request.video_id, indexed=False)

    es_client = _create_es_client(search_config)
    try:
        document = _build_ingest_document(request.video_id, request.metadata)
        await _ensure_embed_index(es_client, search_config.embed_index, document)
        response = await es_client.index(
            index=search_config.embed_index,
            document=document,
            id=request.video_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Elasticsearch indexing failed: {exc}") from exc
    finally:
        await es_client.close()

    return VideoSearchIngestResponse(
        status="ingested",
        video_id=request.video_id,
        indexed=True,
        result_id=response.get("_id"),
    )
