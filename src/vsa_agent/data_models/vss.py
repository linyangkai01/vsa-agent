"""VSS (Video Search & Summarization) data models.

Re-exports from ``video_analytics.nvschema`` for backward compatibility.
The canonical Location/Place/Incident models live in that module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vsa_agent.video_analytics.nvschema import Incident, Location, Place


@dataclass
class MediaInfoOffset:
    """Media information with offset tracking."""

    video_path: str = ""
    duration_sec: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    current_offset_sec: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current_frame_index(self) -> int:
        """Return the derived zero-based frame index."""
        if self.fps <= 0:
            return 0
        return max(0, int(self.current_offset_sec * self.fps))

    @property
    def remaining_duration_sec(self) -> float:
        """Return the remaining duration, clamped at zero."""
        return max(0.0, self.duration_sec - self.current_offset_sec)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "video_path": self.video_path,
            "duration_sec": self.duration_sec,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "current_offset_sec": self.current_offset_sec,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MediaInfoOffset:
        """Rehydrate from a serialized payload."""
        return cls(**payload)


__all__ = ["MediaInfoOffset", "Location", "Place", "Incident"]
