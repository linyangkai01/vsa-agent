"""RTSP stream analysis API."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from vsa_agent.tools.video_understanding import analyze_video

router = APIRouter(prefix="/api/rtsp", tags=["rtsp"])


class RTSPStreamRequest(BaseModel):
    sensor_id: str
    query: str
    start_timestamp: str = ""
    end_timestamp: str = ""


async def analyze_rtsp_stream(
    sensor_id: str,
    query: str,
    start_timestamp: str = "",
    end_timestamp: str = "",
) -> dict:
    result = await analyze_video(
        video_path="",
        query=query,
        source_type="rtsp",
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    return {
        "sensor_id": sensor_id,
        "query": query,
        "summary_text": result.summary_text,
        "metadata": result.metadata,
    }


@router.post("/analyze")
async def analyze_rtsp_stream_endpoint(request: RTSPStreamRequest) -> dict:
    return await analyze_rtsp_stream(**request.model_dump())
