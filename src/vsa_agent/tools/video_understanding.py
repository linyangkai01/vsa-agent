"""Video understanding tool — sends frames to a VLM for captioning and analysis.

Takes base64-encoded JPEG frames (from frame_extract) and a user query,
constructs a vision-language prompt, and returns the VLM's response.

Design Pattern: #2 Multimodal VLM, #11 Intent-Aware Prompting.
"""

import logging

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

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


# ===== Registered Tool =====


@register_tool(
    "video_understanding",
    description="Send video frames to a VLM for analysis and captioning. "
                "Accepts base64-encoded JPEG frames and a user query, "
                "returns a detailed textual description of the video content.",
)
async def video_understanding_tool(
    frames: list[str],
    query: str,
    model_adapter=None,
) -> str:
    """Analyze video frames using a Vision-Language Model.

    Args:
        frames: List of base64-encoded JPEG frame strings.
        query: The user's question or description request.
        model_adapter: Optional model adapter for dependency injection in tests.
                       If None, creates one from config.

    Returns:
        The VLM's textual analysis of the video content.
    """
    if not frames:
        raise ValueError("At least one frame is required for video understanding")

    # Lazily create model adapter from config if not injected
    if model_adapter is None:
        from vsa_agent.model_adapter import create_model_adapter
        from vsa_agent.config import get_config
        config = get_config()
        model_name = config.model.dev.vlm_model if config.model.mode == "dev" else config.model.prod.vlm_model
        model_adapter = create_model_adapter(model_name=model_name)

    # Build the vision-language prompt
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

    logger.info("Sending %d frames to VLM for query: %s", len(frames), query[:80])
    response = await model_adapter.invoke(messages)
    result = str(response.content) if response.content is not None else ""

    logger.info("VLM response length: %d chars", len(result))
    return result
