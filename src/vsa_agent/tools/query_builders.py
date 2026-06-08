"""Query builders and data models for the search agent.

Provides structured query decomposition and typed search results
used by the three-path routing strategy.

Design Pattern: #9 Domain Query Builders, #13 Three-Path Search Strategy.
"""

from pydantic import BaseModel
from pydantic import Field


# ===== Data Models =====


class DecomposedQuery(BaseModel):
    """Structured search parameters extracted from a natural language query
    by the LLM query decomposition step.

    Fields mirror the NVIDIA DecomposedQuery pattern:
    - attributes: person/object descriptions for attribute search
    - has_action: True if query mentions an action/event
    - top_k: number of results to return
    """

    query: str = Field(default="", description="The main search description")
    video_sources: list[str] = Field(default_factory=list, description="List of video source names")
    source_type: str = Field(default="video_file", description="rtsp or video_file")
    timestamp_start: str | None = Field(default=None, description="Start timestamp ISO format")
    timestamp_end: str | None = Field(default=None, description="End timestamp ISO format")
    attributes: list[str] = Field(default_factory=list, description="Person/object attributes to filter by")
    has_action: bool | None = Field(
        default=None,
        description="True if query contains an action/event/activity",
    )
    top_k: int | None = Field(default=None, description="Number of results to return")
    min_cosine_similarity: float | None = Field(default=None, description="Minimum similarity threshold")


class SearchResult(BaseModel):
    """A single search result item matching the query."""

    video_name: str = Field(..., description="Name of the video file")
    description: str = Field(..., description="Description of the video content")
    start_time: str = Field(..., description="Start time ISO timestamp")
    end_time: str = Field(..., description="End time ISO timestamp")
    sensor_id: str = Field(..., description="Sensor identifier")
    screenshot_url: str = Field(default="", description="URL to screenshot")
    similarity: float = Field(..., description="Cosine similarity score (0.0-1.0)")
    object_ids: list[str] = Field(default_factory=list, description="Tracked object IDs")


class SearchOutput(BaseModel):
    """Container for a list of search results."""

    data: list[SearchResult] = Field(
        default_factory=list,
        description="List of search results matching the query",
    )
