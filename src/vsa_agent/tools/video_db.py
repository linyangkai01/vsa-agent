"""Mock video database - maps video names to local file paths.

In production, this would query a real video database (Elasticsearch, Milvus, etc.)
to find videos by name, sensor ID, time range, etc.

For now, it provides a simple name-to-path mapping for local video files.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Mock video database: name -> file path
_VIDEO_DB: dict[str, str] = {}

# Auto-discover videos in the data/video directory
# video_db.py is at src/vsa_agent/tools/video_db.py
# project root is 3 levels up from tools/
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TOOLS_DIR)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data", "video")

if os.path.isdir(_DATA_DIR):
    for f in os.listdir(_DATA_DIR):
        if f.endswith((".mp4", ".avi", ".mov", ".mkv")):
            name = os.path.splitext(f)[0]
            _VIDEO_DB[name] = os.path.join(_DATA_DIR, f)
            _VIDEO_DB[f] = os.path.join(_DATA_DIR, f)


def find_video(name_or_path: str) -> str | None:
    """Find a video by name or path.

    Supports:
    - "test1" -> data/video/test1.mp4
    - "test1.mp4" -> data/video/test1.mp4
    - "/absolute/path/to/video.mp4" -> same path (passthrough)
    - "data/video/test1.mp4" -> resolved relative to project root

    Returns:
        Absolute file path, or None if not found.
    """
    # Passthrough for existing absolute paths
    if os.path.isabs(name_or_path) and os.path.exists(name_or_path):
        return os.path.abspath(name_or_path)

    # Check mock database by name (without extension or with)
    if name_or_path in _VIDEO_DB:
        return _VIDEO_DB[name_or_path]

    # Check by stripping extension
    base = os.path.splitext(name_or_path)[0]
    if base in _VIDEO_DB:
        return _VIDEO_DB[base]

    # Try resolving relative to project root
    candidate = os.path.join(_PROJECT_ROOT, name_or_path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    # Try data/video/ prefix
    candidate = os.path.join(_DATA_DIR, name_or_path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    # Try adding .mp4
    if not name_or_path.endswith(".mp4"):
        candidate = os.path.join(_DATA_DIR, name_or_path + ".mp4")
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    return None


def list_videos() -> list[dict]:
    """List all available videos in the mock database."""
    result = []
    for name, path in sorted(_VIDEO_DB.items()):
        # Skip duplicate entries (name with and without extension)
        if os.path.splitext(name)[0] == name:
            continue
        size = os.path.getsize(path) if os.path.exists(path) else 0
        result.append({"name": name, "path": path, "size_bytes": size})
    return result
