"""Summary Agent — long video chunking + VLM aggregation + safety report.

Orchestrates: chunk video → frame_extract → VLM caption → aggregate report.
Designed for analyzing long security videos (minutes to hours).

Design Pattern: #11 Long-Form Video Analysis, #20 Safety Report Generation.
"""

import logging

from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# ===== Input Model =====


class SummaryAgentInput(BaseModel):
    """Input for the Summary Agent. Mirrors NVIDIA agent input patterns."""

    query: str = Field(description="What to look for in the video (e.g., safety violations)")
    video_path: str = Field(default="", description="Path to the video file")
    chunk_duration_sec: int = Field(default=30, description="Duration of each chunk in seconds")
    max_chunks: int = Field(default=10, description="Maximum number of chunks to process")


# ===== Core Orchestration =====


async def execute_summary(
    search_input: SummaryAgentInput,
    video_duration_sec: float,
    frame_extract_fn=None,
    video_understand_fn=None,
) -> str:
    """Execute long video summary: chunk → caption → aggregate → report.

    Args:
        search_input: Summary agent parameters (query, chunk size, etc.)
        video_duration_sec: Total video duration in seconds.
        frame_extract_fn: Async function for frame extraction (injected for testing).
        video_understand_fn: Async function for VLM captioning (injected for testing).

    Returns:
        Aggregated summary report string.
    """
    if video_duration_sec <= 0:
        return "Video duration is 0 seconds. No frames to analyze."

    chunk_duration = search_input.chunk_duration_sec
    num_chunks = min(
        max(1, int(video_duration_sec / chunk_duration)),
        search_input.max_chunks,
    )

    logger.info("Processing %d chunks of %ds each", num_chunks, chunk_duration)

    # Resolve functions from registry if not injected
    if frame_extract_fn is None:
        from vsa_agent.registry import ToolRegistry
        frame_extract_fn = ToolRegistry.get("frame_extract")
    if video_understand_fn is None:
        from vsa_agent.registry import ToolRegistry
        video_understand_fn = ToolRegistry.get("video_understanding")

    captions = []
    for i in range(num_chunks):
        start = i * chunk_duration
        end = min(start + chunk_duration, video_duration_sec)

        logger.debug("Chunk %d/%d: %.1fs - %.1fs", i + 1, num_chunks, start, end)

        # Extract frames for this chunk
        if frame_extract_fn:
            frames_result = await frame_extract_fn(
                video_path=search_input.video_path,
                start_timestamp=start,
                end_timestamp=end,
                max_frames=5,
            )
            frames = frames_result.get("frames", [])
        else:
            frames = []

        # Send frames to VLM
        if frames and video_understand_fn:
            caption = await video_understand_fn(
                frames=frames,
                query=search_input.query,
            )
            captions.append(caption)
        else:
            captions.append(f"[{start:.1f}s-{end:.1f}s] No frames extracted")

    # Aggregate into report
    report_lines = [
        f"Video Summary Report",
        f"Query: {search_input.query}",
        f"Duration: {video_duration_sec:.1f}s, Chunks: {num_chunks}",
        f"{'='*40}",
        "",
    ]
    for i, caption in enumerate(captions):
        start = i * chunk_duration
        end = min(start + chunk_duration, video_duration_sec)
        report_lines.append(f"[{start:.1f}s - {end:.1f}s]")
        report_lines.append(caption)
        report_lines.append("")

    return "\n".join(report_lines)
