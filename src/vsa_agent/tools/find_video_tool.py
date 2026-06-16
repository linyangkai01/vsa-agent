"""Video database lookup tool - finds local video files by name.

Maps user-friendly video names ("test1", "warehouse_cam") to local file paths.
In production, this would query Elasticsearch/Milvus for video metadata.
"""

import logging

from vsa_agent.registry import register_tool
from vsa_agent.tools.video_db import find_video, list_videos

logger = logging.getLogger(__name__)


@register_tool(
    "find_video",
    description="Find a video file by name or path. Returns the full file path if found. "
                "Use this FIRST when the user mentions a video name like 'test1' or 'test1.mp4'. "
                "The returned path can be passed to frame_extract or video_understanding.",
)
async def find_video_tool(name: str) -> str:
    """Find a video file by name.

    Args:
        name: Video name (e.g., "test1", "test1.mp4", or partial path).

    Returns:
        Full file path if found, or error message if not found.
    """
    path = find_video(name)
    if path:
        logger.info("Found video '%s' at: %s", name, path)
        return path
    available = list_videos()
    names = [v["name"] for v in available]
    return f"Video '{name}' not found. Available videos: {names}"


@register_tool(
    "list_videos",
    description="List all available videos in the local database. Returns names and file paths.",
)
async def list_videos_tool() -> str:
    """List all available videos."""
    videos = list_videos()
    if not videos:
        return "No videos found in the database."
    lines = ["Available videos:"]
    for v in videos:
        size_mb = v["size_bytes"] / (1024 * 1024)
        lines.append(f"  - {v['name']} ({size_mb:.1f} MB)")
    return "\n".join(lines)

