"""Compatibility caption tool built on top of video understanding."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.video_understanding import analyze_video


class VideoCaptionInput(BaseModel):
    """Input payload for the caption compatibility tool."""

    video_path: str = Field(default="", description="Path to local video file")
    sensor_id: str = Field(default="", description="Sensor identifier for RTSP/VST sources")
    user_prompt: str = Field(default="", description="Caption prompt")
    start_timestamp: str = Field(default="", description="Optional start timestamp")
    end_timestamp: str = Field(default="", description="Optional end timestamp")


@register_tool(
    "video_caption",
    description="Generate caption text for a video file or RTSP clip using the shared understanding pipeline.",
)
async def video_caption_tool(
    video_path: str = "",
    sensor_id: str = "",
    user_prompt: str = "",
    start_timestamp: str = "",
    end_timestamp: str = "",
) -> str:
    source_type = "rtsp" if sensor_id else "video_file"
    result = await analyze_video(
        video_path=video_path,
        query=user_prompt,
        source_type=source_type,
        sensor_id=sensor_id or None,
        start_timestamp=start_timestamp or None,
        end_timestamp=end_timestamp or None,
    )
    return result.summary_text

