"""VSS (Video Search & Summarization) data models.

Re-exports from video_analytics/nvschema.py for backward compatibility.
The canonical Incident model lives in video_analytics/nvschema.py.
"""

from __future__ import annotations

from vsa_agent.video_analytics.nvschema import Incident

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MediaInfoOffset:
    """Media information with offset tracking.

    Tracks video metadata and current processing position.
    """
    video_path: str = ""
    duration_sec: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    current_offset_sec: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["MediaInfoOffset", "Incident"]
