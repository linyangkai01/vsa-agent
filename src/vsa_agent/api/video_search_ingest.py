"""Video search ingest endpoint — submits a video for indexing.

Mirrors NVIDIA api/video_search_ingest.py pattern.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search/ingest")
async def video_search_ingest(video_id: str, metadata: dict | None = None):
    """Submit a video for search indexing.

    Simplified: returns mock response. Production needs ES index integration.
    """
    return {"status": "ingested", "video_id": video_id, "indexed": True}
