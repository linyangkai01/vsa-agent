"""Video understanding tool — sends frames to a VLM for captioning and analysis.

Takes base64-encoded JPEG frames (from frame_extract) and a user query,
constructs a vision-language prompt, and returns the VLM's response.

Design Pattern: #2 Multimodal VLM, #11 Intent-Aware Prompting.
"""

import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool

logger = logging.getLogger(__name__)

# ===== Constants =====

SYSTEM_PROMPT = (
    "You are an expert at video understanding and description. "
    "Your task is to capture, in as much detail as possible, the events "
    "from the video frames related to the user's query. "
    "Be sure to capture details about the environment, people, objects, "
    "and actions. For example, describe attire, vehicle types, object colors. "
    "The frames are sampled from the video in sequence. "
    "DO NOT make up anything not visible in the frames. "
    "DO NOT hallucinate."
)

DEFAULT_MAX_FRAMES = 24


# ===== Registered Tool =====



# ===== Data Model =====



class VideoUnderstandingInput(BaseModel):
    """Input model for video understanding. Mirrors NVIDIA pattern."""
    sensor_id: str = Field(default="", description="Camera/sensor identifier")
    start_timestamp: str = Field(default="", description="Start time (ISO 8601)")
    end_timestamp: str = Field(default="", description="End time (ISO 8601)")
    user_prompt: str = Field(default="", description="User query about the video")
    video_path: str = Field(default="", description="Path to video file")
    max_frames: int = Field(default=10, description="Maximum frames to extract")



def _extract_frames(
    video_path: str,
    max_frames: int,
    start_timestamp: float = 0.0,
    end_timestamp: float | None = None,
) -> tuple[list[str], float, float, int]:
    """Extract evenly-spaced frames from a video file.

    Args:
        video_path: Path to the video file.
        max_frames: Maximum number of frames to extract.
        start_timestamp: Start time in seconds.
        end_timestamp: End time in seconds (None = full video).

    Returns:
        Tuple of (base64_frames, duration_sec, fps, total_frames).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise ValueError(f"Video has no frames: {video_path}")

        duration_sec = total_frames / fps if fps > 0 else 0
        if end_timestamp is None:
            end_timestamp = duration_sec

        start_ts = max(0.0, start_timestamp)
        end_ts = min(duration_sec, end_timestamp)

        time_window = end_ts - start_ts
        if time_window <= 0:
            return [], duration_sec, fps, total_frames

        start_frame = min(total_frames - 1, math.floor(start_ts * fps))
        end_frame = min(total_frames - 1, math.ceil(end_ts * fps))
        step_size_frame = max(1, math.floor((time_window / max_frames) * fps))

        frame_indices = list(range(start_frame, end_frame, step_size_frame))
        if not frame_indices:
            return [], duration_sec, fps, total_frames

        import base64
        base64_frames = []
        for frame_idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError(f"Could not read frame {frame_idx}")
            _, buffer = cv2.imencode(".jpg", frame)
            base64_frames.append(base64.b64encode(buffer.tobytes()).decode("utf-8"))

        return base64_frames, duration_sec, fps, total_frames
    finally:
        cap.release()



async def _analyze_frames(frames: list[str], query: str, model_adapter=None) -> str:
    """Send frames to VLM for analysis."""
    from vsa_agent.model_adapter import create_model_adapter
    from vsa_agent.config import get_config

    if not frames:
        return "No frames to analyze."

    if model_adapter is None:
        config = get_config()
        model_name = config.model.dev.vlm_model if config.model.mode == "dev" else config.model.prod.vlm_model
        model_adapter = create_model_adapter(model_name=model_name)

    image_parts = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}}
        for frame in frames
    ]
    human_prompt_parts = [
        {"type": "text", "text": (
            f"The following images are frames from a video, sampled in sequence. "
            f"Analyze them and answer the user's query.\n\n"
            f"User query: {query}\n\n"
            f"Start and end each observation with a relative timestamp if you can "
            f"infer timing from the sequence. "
            f"Use the format: <timestamp> observation_content </timestamp>."
        )},
        *image_parts,
    ]
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=human_prompt_parts),
    ]

    try:
        response = await model_adapter.invoke(messages)
    except Exception as e:
        raise RuntimeError(f"VLM call failed for query '{query[:60]}...': {e}") from e

    result = str(response.content) if response.content is not None else ""
    logger.info("VLM response length: %d chars", len(result))
    return result



async def _analyze_chunked(video_path: str, query: str, duration_sec: float, model_adapter=None) -> str:
    """Analyze a long video by chunking."""
    num_chunks = max(1, math.ceil(duration_sec / CHUNK_DURATION_SEC))
    logger.info("Long video (%.1fs): chunking into %d chunks of %ds", duration_sec, num_chunks, CHUNK_DURATION_SEC)

    captions = []
    for i in range(num_chunks):
        start = i * CHUNK_DURATION_SEC
        end = min(start + CHUNK_DURATION_SEC, duration_sec)

        frames, _, _, _ = _extract_frames(
            video_path, FRAMES_PER_CHUNK, start_timestamp=start, end_timestamp=end,
        )

        if frames:
            caption = await _analyze_frames(frames, query, model_adapter)
            captions.append(f"[{start:.0f}s-{end:.0f}s] {caption}")
        else:
            captions.append(f"[{start:.0f}s-{end:.0f}s] No frames extracted")

    report = [
        "Video Summary Report",
        f"Query: {query}",
        f"Duration: {duration_sec:.1f}s, Chunks: {num_chunks}",
        "=" * 40,
        "",
    ]
    for c in captions:
        report.append(c)
        report.append("")

    return "\n".join(report)



class VideoUnderstandingConfig(BaseModel):
    """Configuration for video understanding. Mirrors NVIDIA config pattern."""
    max_fps: float = Field(default=2.0, description="Maximum frames per second to extract")
    min_pixels: int = Field(default=224 * 224, description="Minimum pixel resolution for frames")
    max_pixels: int = Field(default=1280 * 720, description="Maximum pixel resolution for frames")
    reasoning_effort: str = Field(default="medium", description="Reasoning effort: low, medium, high")
    filter_thinking: bool = Field(default=True, description="Filter out thinking/reasoning from response")
    max_retries: int = Field(default=3, description="Maximum VLM retry attempts on failure")




from vsa_agent.utils.reasoning_parsing import parse_reasoning_content


def _parse_thinking_from_content(content: str) -> tuple[str | None, str]:
    """Parse VLM response. Delegates to utils.reasoning_parsing."""
    result = parse_reasoning_content(content)
    return result.thinking if result.has_reasoning else None, result.answer

@register_tool(
    "video_understanding",
    description="Analyze a video file. Provide the video_path and a query about what to look for. "
                "For short videos (<40s), extracts frames and sends to VLM directly. "
                "For long videos (>40s), automatically chunks the video and analyzes each segment. "
                "Returns a detailed textual description. One-step tool - no need to call frame_extract first.",
)
async def video_understanding_tool(
    video_path: str = "",
    query: str = "",
    model_adapter=None,
    frames: list[str] | None = None,
) -> str:
    """Analyze a video file in one step.

    Internally handles frame extraction, duration checking, and chunking.
    Short videos: extract frames -> VLM.
    Long videos: chunk -> extract frames per chunk -> VLM per chunk -> aggregate.

    Args:
        video_path: Path to the video file.
        query: What to look for in the video.
        model_adapter: Optional model adapter for dependency injection.
        frames: Direct frame list (backward compatibility, deprecated).

    Returns:
        Textual analysis of the video content.
    """
    # Backward compatibility: if frames are provided directly, use them
    if frames is not None:
        return await _analyze_frames(frames, query, model_adapter)

    if not video_path:
        raise ValueError("Either 'video_path' or 'frames' must be provided")

    if not os.path.exists(video_path):
        raise ValueError(f"Video file not found: {video_path}")

    # Open video to check duration
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration_sec = total_frames / fps if fps > 0 else 0

    logger.info("Video: %s, duration: %.1fs, fps: %.1f, frames: %d", video_path, duration_sec, fps, total_frames)

    if duration_sec > LONG_VIDEO_THRESHOLD_SEC:
        logger.info("Duration %.1fs > %ds threshold, using chunked analysis", duration_sec, LONG_VIDEO_THRESHOLD_SEC)
        return await _analyze_chunked(video_path, query, duration_sec, model_adapter)

    # Short video: extract frames and analyze directly
    extracted_frames, _, _, _ = _extract_frames(video_path, DEFAULT_MAX_FRAMES)
    return await _analyze_frames(extracted_frames, query, model_adapter)


def _build_vlm_messages(frames, query, system_prompt=None):
    """Build VLM messages from frames and query. Independent, testable function."""
    image_parts = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}}
        for frame in frames
    ]
    human_prompt_parts = [
        {"type": "text", "text": (
            f"The following images are frames from a video, sampled in sequence. "
            f"Analyze them and answer the user's query.\n\n"
            f"User query: {query}\n\n"
            f"Start and end each observation with a relative timestamp if you can "
            f"infer timing from the sequence. "
            f"Use the format: <timestamp> observation_content </timestamp>."
        )},
        *image_parts,
    ]
    return [
        SystemMessage(content=system_prompt or SYSTEM_PROMPT),
        HumanMessage(content=human_prompt_parts),
    ]
