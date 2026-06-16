"""Skim caption wrapper built on top of video caption."""

from __future__ import annotations

from vsa_agent.registry import register_tool
from vsa_agent.tools.video_caption import video_caption_tool


@register_tool(
    "video_skim_caption",
    description="Generate a brief caption for a video using the shared caption pipeline.",
)
async def video_skim_caption_tool(
    video_path: str = "",
    sensor_id: str = "",
    user_prompt: str = "",
    start_timestamp: str = "",
    end_timestamp: str = "",
) -> str:
    skim_prompt = f"请简要概述视频内容：{user_prompt}".strip("：")
    return await video_caption_tool(
        video_path=video_path,
        sensor_id=sensor_id,
        user_prompt=skim_prompt,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )

