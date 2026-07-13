from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from vsa_agent.tools.search import SearchResult


def build_record_id(run_id: str, video_path: str) -> str:
    if run_id.strip():
        return run_id.strip()
    name = Path(video_path).name
    return name or "unknown-video"


class ArchiveRecord(BaseModel):
    record_id: str = Field(description="Stable archive record identifier")
    video_name: str = Field(description="Video filename")
    video_path: str = Field(default="", description="Original local video path")
    description: str = Field(default="", description="Concise searchable description")
    search_text: str = Field(default="", description="Concatenated text used for local search")
    start_time: str = Field(default="", description="Run/video start timestamp")
    end_time: str = Field(default="", description="Run/video end timestamp")
    sensor_id: str = Field(default="", description="Sensor or video source identifier")
    screenshot_url: str = Field(default="", description="Optional preview image URL/path")
    object_ids: list[str] = Field(default_factory=list, description="Lightweight extracted tags")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source run metadata")

    def to_search_result(self, similarity: float) -> SearchResult:
        return SearchResult(
            video_name=self.video_name,
            description=self.description,
            start_time=self.start_time,
            end_time=self.end_time,
            sensor_id=self.sensor_id,
            screenshot_url=self.screenshot_url,
            similarity=max(0.0, min(1.0, float(similarity))),
            object_ids=list(self.object_ids),
        )
