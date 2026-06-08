import json
import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# ===== Data Models =====
# SIMPLIFIED: Moved here from query_builders.py to match NVIDIA original structure.
# In the NVIDIA original, DecomposedQuery/SearchResult/SearchOutput are defined
# directly in tools/search.py (~1400 lines), not in a separate file.


class DecomposedQuery(BaseModel):
    query: str = Field(default='', description='The main search description')
    video_sources: list[str] = Field(default_factory=list, description='List of video source names')
    source_type: str = Field(default='video_file', description='rtsp or video_file')
    timestamp_start: str | None = Field(default=None, description='Start timestamp ISO format')
    timestamp_end: str | None = Field(default=None, description='End timestamp ISO format')
    attributes: list[str] = Field(default_factory=list, description='Person/object attributes to filter by')
    has_action: bool | None = Field(
        default=None,
        description='True if query contains an action/event/activity',
    )
    top_k: int | None = Field(default=None, description='Number of results to return')
    min_cosine_similarity: float | None = Field(default=None, description='Minimum similarity threshold')


class SearchResult(BaseModel):
    video_name: str = Field(..., description='Name of the video file')
    description: str = Field(..., description='Description of the video content')
    start_time: str = Field(..., description='Start time ISO timestamp')
    end_time: str = Field(..., description='End time ISO timestamp')
    sensor_id: str = Field(..., description='Sensor identifier')
    screenshot_url: str = Field(default='', description='URL to screenshot')
    similarity: float = Field(..., description='Cosine similarity score (0.0-1.0)')
    object_ids: list[str] = Field(default_factory=list, description='Tracked object IDs')


class SearchOutput(BaseModel):
    data: list[SearchResult] = Field(
        default_factory=list,
        description='List of search results matching the query',
    )
