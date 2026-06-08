"""Attribute search tool — object-level search by visual attributes.

Searches for video segments matching specific object/person descriptions
(e.g., "person with red jacket", "blue forklift").

Design Pattern: #10 Registry Table, #13 Search Strategy.
"""

import logging

from datetime import datetime
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult

logger = logging.getLogger(__name__)


# ===== Data Models =====


class AttributeSearchInput(BaseModel):
    """Input for attribute-based search. Mirrors NVIDIA AttributeSearchInput."""

    query: str | list[str] = Field(
        ...,
        description="Attribute query or list of queries (e.g., 'person with red hat' or ['person', 'red hat'])",
    )
    source_type: str = Field(
        default="video_file",
        description="Type of video source: 'video_file' for uploaded videos, 'rtsp' for live/camera streams.",
    )
    timestamp_start: str | None = Field(default=None, description="Start time filter")
    timestamp_end: str | None = Field(default=None, description="End time filter")
    video_sources: list[str] | None = Field(default=None, description="Filter by video source names")
    top_k: int = Field(default=1, description="Number of results to return")
    min_similarity: float = Field(default=0.3, description="Minimum cosine similarity threshold")
    fuse_multi_attribute: bool = Field(default=True, description="Fuse multiple attributes for single screenshot")
    exclude_videos: list[dict[str, str]] = Field(default_factory=list, description="Videos to exclude")


class AttributeSearchMetadata(BaseModel):
    """Metadata for attribute search result. Mirrors NVIDIA AttributeSearchMetadata."""

    sensor_id: str = Field(..., description="Sensor/camera ID")
    object_id: str = Field(..., description="Object ID")
    object_type: str = Field(default="", description="Object type")
    frame_timestamp: str = Field(default="", description="Best frame timestamp")
    start_time: str | None = Field(default=None, description="Start time")
    end_time: str | None = Field(default=None, description="End time")
    bbox: dict | None = Field(default=None, description="Bounding box")
    behavior_score: float = Field(default=0.0, description="Behavior-level similarity")
    frame_score: float | None = Field(default=None, description="Frame-level similarity")
    video_name: str | None = Field(default=None, description="Video name")


class AttributeSearchResult(BaseModel):
    """Single attribute search result. Mirrors NVIDIA AttributeSearchResult."""

    screenshot_url: str | None = Field(default=None, description="Screenshot URL")
    metadata: AttributeSearchMetadata = Field(..., description="Search result metadata")


# ===== Core Search =====


async def search_by_attributes(
    query_text: str,
    search_input: AttributeSearchInput | None = None,
) -> list[AttributeSearchResult]:
    """Search for objects by visual attributes. Mock implementation.

    NVIDIA original uses Elasticsearch behavior index + frame lookup +
    cosine similarity with Painless scripts. Returns mock results for now.
    """
    if search_input is None:
        search_input = AttributeSearchInput(query=query_text)
    
    # Mock: return a single result with deterministic scoring
    seed = sum(ord(c) for c in str(query_text)) % 100
    return [
        AttributeSearchResult(
            screenshot_url="",
            metadata=AttributeSearchMetadata(
                sensor_id=f"sensor-{seed % 10}",
                object_id=f"obj-{seed}",
                object_type="person" if "person" in str(query_text).lower() else "object",
                frame_timestamp="2025-01-01T10:00:00Z",
                behavior_score=0.5 + seed * 0.005,
                video_name=f"camera_{seed % 5}.mp4",
            ),
        )
    ]


# ===== Helpers =====


def _deduplicate_by_video_name(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate SearchResults by video_name, keeping the highest similarity.

    This mimics the NVIDIA original's deduplication behavior where
    multiple attribute hits on the same video are collapsed into the
    best-scoring result.
    """
    merged: dict[str, SearchResult] = {}
    for r in results:
        if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
            merged[r.video_name] = r
    return sorted(merged.values(), key=lambda x: x.similarity, reverse=True)


# ===== Registered Tool =====


@register_tool(
    "attribute_search",
    description="Attribute-based search: find video segments matching specific "
                "visual attributes (e.g., 'person in red jacket'). "
                "Returns deduplicated SearchOutput ranked by similarity.",
)
async def attribute_search_tool(
    attributes: list[str],
    store=None,
    top_k: int = 5,
) -> SearchOutput:
    """Search for video segments matching visual attribute descriptions.

    Args:
        attributes: List of attribute descriptions (e.g., ["person in red shirt"]).
        store: Optional vector store for dependency injection (testing).
               If None, uses a default in-memory store.
        top_k: Maximum results per attribute before deduplication.

    Returns:
        SearchOutput with deduplicated, ranked matches.
    """
    if not attributes:
        raise ValueError("At least one attribute is required for attribute search")

    if store is None:
        from vsa_agent.tools.vector_store import get_default_store
        store = get_default_store()

    try:
        result = await store.search_by_attributes(
            attributes=attributes,
            top_k=top_k,
        )

        if isinstance(result, SearchOutput):
            results = result.data
        elif hasattr(result, "data"):
            results = list(result.data)
        else:
            results = list(result) if isinstance(result, list) else []

        # Deduplicate by video_name (best score wins)
        deduped = _deduplicate_by_video_name(results)

        # Sort by similarity descending
        deduped.sort(key=lambda x: x.similarity, reverse=True)

        return SearchOutput(data=deduped[:top_k])
    except Exception as e:
        logger.error("Attribute search failed for attributes %s: %s", attributes, e)
        return SearchOutput(data=[])
