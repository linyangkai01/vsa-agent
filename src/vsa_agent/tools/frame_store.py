"""Shared frame store - allows frame_extract to pass frames to video_understanding
without going through the LLM message loop.

frame_extract stores frames here and returns a reference key.
video_understanding reads frames by key.
"""

import uuid
from typing import Any

_frame_store: dict[str, dict[str, Any]] = {}


def store_frames(frames: list[str], metadata: dict) -> str:
    """Store frames and return a reference key."""
    key = str(uuid.uuid4())
    _frame_store[key] = {"frames": frames, "metadata": metadata}
    return key


def get_frames(key: str) -> list[str] | None:
    """Retrieve frames by reference key."""
    entry = _frame_store.get(key)
    if entry is None:
        return None
    return entry["frames"]


def get_metadata(key: str) -> dict | None:
    """Retrieve metadata by reference key."""
    entry = _frame_store.get(key)
    if entry is None:
        return None
    return entry["metadata"]


def clear_key(key: str) -> None:
    """Remove frames from store."""
    _frame_store.pop(key, None)


def clear_all() -> None:
    """Clear all stored frames."""
    _frame_store.clear()
