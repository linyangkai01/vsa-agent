"""URL translation utilities for video file access.

Handles conversion between different URL/file formats
for video storage backends.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def translate_url(url: str, target_base: str | None = None) -> str:
    """Translate a video URL to a local filesystem path.

    Supports:
    - file:// URLs → local paths
    - s3:// URLs → (requires external mapping)
    - http(s):// URLs → (requires download)
    - Plain paths → returned as-is

    Args:
        url: The video URL or path.
        target_base: Optional base directory for local files.

    Returns:
        Translated local filesystem path.
    """
    parsed = urlparse(url)

    if parsed.scheme == "file":
        path = parsed.path
        if target_base:
            return os.path.join(target_base, os.path.basename(path))
        return path

    if parsed.scheme in ("", "c:", "d:"):
        # Already a local path
        return url

    # For other schemes, return as-is (caller handles)
    return url


def is_remote_url(url: str) -> bool:
    """Check if a URL points to a remote resource.

    Args:
        url: The URL to check.

    Returns:
        True if the URL is remote (http, https, s3, etc.).
    """
    parsed = urlparse(url)
    return parsed.scheme not in ("", "file", None)
