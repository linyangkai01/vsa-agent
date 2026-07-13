"""URL translation utilities for video file access."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def normalize_local_path(path: str) -> str:
    """Normalize a local filesystem path to forward-slash form."""
    return (path or "").replace("\\", "/")


def translate_url(url: str, target_base: str | None = None) -> str:
    """Translate a video URL to a local filesystem path or passthrough URI."""
    if not url:
        return ""

    parsed = urlparse(url)

    if parsed.scheme == "file":
        path = normalize_local_path(parsed.path)
        if target_base:
            return normalize_local_path(os.path.join(target_base, os.path.basename(path)))
        return path

    if parsed.scheme in ("", "c", "d"):
        return normalize_local_path(url)

    if parsed.scheme in ("s3", "minio") and target_base:
        relative_parts = [part for part in [parsed.netloc, *parsed.path.lstrip("/").split("/")] if part]
        return "/".join([normalize_local_path(target_base).rstrip("/")] + relative_parts)

    return url


def is_remote_url(url: str) -> bool:
    """Return whether a URL points to a remote resource."""
    if len(url) >= 3 and url[1:3] in (":\\", ":/") and url[0].isalpha():
        return False
    parsed = urlparse(url)
    return parsed.scheme not in ("", "file", None)
