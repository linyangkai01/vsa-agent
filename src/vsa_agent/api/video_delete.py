"""Video delete API stub."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["video"])


@router.delete("/video/{video_id}")
async def delete_video(video_id: str) -> dict:
    return {"video_id": video_id, "deleted": True, "mode": "stub"}
