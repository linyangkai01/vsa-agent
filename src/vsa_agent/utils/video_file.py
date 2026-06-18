"""Shared video-file path helpers."""

from __future__ import annotations

from vsa_agent.utils.url_translation import is_remote_url
from vsa_agent.utils.url_translation import normalize_local_path


def is_local_video_candidate(path: str) -> bool:
    """Return whether a path is a local video-file candidate."""
    return bool(path) and not is_remote_url(path)


def ensure_local_video_path(path: str) -> str:
    """Validate and normalize a local video file path."""
    if not is_local_video_candidate(path):
        raise ValueError(f"Expected a local video file path, got: {path}")
    return normalize_local_path(path)
