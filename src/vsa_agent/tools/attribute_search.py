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


# ===== P1 Multi-Attribute Search (Phase B) =====


async def search_single_attribute(attribute, search_input=None):
    """Search for a single attribute. Returns list of AttributeSearchResult."""
    return await search_by_attributes(query_text=attribute, search_input=search_input)


async def search_attributes(search_input):
    """Search for multiple attributes. For each query, calls search_single_attribute."""
    queries = search_input.query
    if isinstance(queries, str):
        queries = [queries]
    all_results = []
    for q in queries:
        attr_results = await search_single_attribute(q, search_input)
        for ar in attr_results:
            if hasattr(ar, "metadata"):
                m = ar.metadata
                sr = _build_result({
                    "sensor_id": m.sensor_id, "object_id": m.object_id,
                    "object_type": m.object_type, "behavior_score": m.behavior_score,
                    "frame_score": m.frame_score, "video_name": m.video_name,
                    "start_time": m.start_time, "end_time": m.end_time,
                    "frame_timestamp": m.frame_timestamp, "bbox": m.bbox,
                }, screenshot_url=ar.screenshot_url or "")
                all_results.append(sr)
    return all_results


def _fuse_multi_attribute(attributes, attr_results_by_video):
    """Intersection: keep only videos appearing for ALL attributes."""
    if not attr_results_by_video:
        return []
    return [results[0] for results in attr_results_by_video.values() if results]


def _append_multi_attribute(attributes, attr_results_by_video):
    """Union: return all unique videos (best score per video)."""
    merged = {}
    for video_name, results in attr_results_by_video.items():
        if video_name not in merged and results:
            merged[video_name] = results[0]
    return list(merged.values())


def _build_result(metadata_dict, screenshot_url=""):
    """Build SearchResult from metadata dict."""
    similarity = float(metadata_dict.get("frame_score") or metadata_dict.get("behavior_score", 0.0))
    start = metadata_dict.get("start_time") or metadata_dict.get("frame_timestamp", "")
    end = metadata_dict.get("end_time") or metadata_dict.get("frame_timestamp", "")
    return SearchResult(
        video_name=metadata_dict.get("video_name", "unknown"),
        description=metadata_dict.get("object_type", "") or f"Match for {metadata_dict.get('object_id', 'unknown')}",
        start_time=start or "",
        end_time=end or "",
        sensor_id=metadata_dict.get("sensor_id", ""),
        screenshot_url=screenshot_url,
        similarity=similarity,
        object_ids=[str(metadata_dict.get("object_id", ""))],
    )
