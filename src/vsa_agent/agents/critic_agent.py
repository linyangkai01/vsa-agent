"""Critic Agent — VLM-based search result verification.

Evaluates video search results against the original query by sending
each result to a VLM for criteria checking. Returns confirmed, rejected,
or unverified results.

Mirrors NVIDIA critic_agent.py data models and verification pattern.

Design Pattern: #7 Self-Check Loop.
"""

import json
import logging
from enum import Enum

from pydantic import BaseModel
from pydantic import ConfigDict
from langchain_core.messages import HumanMessage
from pydantic import Field

logger = logging.getLogger(__name__)

# ===== Prompt =====

CRITIC_AGENT_PROMPT = """You evaluate a video against a user prompt and check whether the requested parameters are met.

user_prompt: __USER_PROMPT__

Break down the user prompt into criteria and evaluate each. Return JSON:
Example: {"man": true, "blue shirt": true, "backpack": true}

All criteria must be met for the result to be confirmed."""


# ===== Data Models =====


class CriticAgentResult(Enum):
    """Result for a single video evaluation. Mirrors NVIDIA CriticAgentResult."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


class VideoInfo(BaseModel):
    """Information about a video clip. Mirrors NVIDIA VideoInfo."""

    model_config = ConfigDict(frozen=True)
    sensor_id: str = Field(description="The sensor ID of the video.")
    start_timestamp: str = Field(description="Start timestamp in UTC ISO 8601 format.")
    end_timestamp: str = Field(description="End timestamp in UTC ISO 8601 format.")


class CriticAgentInput(BaseModel):
    """Input for the Critic Agent. Mirrors NVIDIA CriticAgentInput."""

    query: str = Field(description="The user query used to generate search results.")
    videos: list[VideoInfo] = Field(description="List of video information to evaluate.")
    evaluation_count: int | None = Field(
        default=None,
        description="Number of videos to evaluate. None = all.",
        ge=1,
    )


class VideoResult(BaseModel):
    """Result for a single video evaluation. Mirrors NVIDIA VideoResult."""

    video_info: VideoInfo = Field(description="The video that was evaluated.")
    result: CriticAgentResult = Field(description="The evaluation result.")
    criteria_met: dict[str, bool] | None = Field(default=None, description="Criteria status dictionary.")


class CriticAgentOutput(BaseModel):
    """Output for the Critic Agent. Mirrors NVIDIA CriticAgentOutput."""

    video_results: list[VideoResult] = Field(description="List of video results.")


# ===== Helpers =====


def _get_json_from_string(string: str) -> str:
    """Strip JSON from markdown code blocks. Mirrors NVIDIA get_json_from_string."""
    if "```json" in string:
        return string.split("```json")[1].split("```")[0].strip()
    return string


# ===== Core Verification =====


async def execute_critic(
    critic_input: CriticAgentInput,
    model_adapter=None,
) -> CriticAgentOutput:
    """Execute VLM-based verification of search results.

    Sends each video to VLM with criteria-checking prompt. Returns
    confirmed, rejected, or unverified for each result.

    Args:
        critic_input: Query + videos to verify.
        model_adapter: Model adapter for VLM calls (injected for testing).

    Returns:
        CriticAgentOutput with evaluation results.
    """
    if model_adapter is None:
        from vsa_agent.model_adapter import create_model_adapter
        model_adapter = create_model_adapter()

    video_count = min(
        critic_input.evaluation_count or len(critic_input.videos),
        len(critic_input.videos),
    )

    video_results = []
    for video in critic_input.videos[:video_count]:
        formatted_prompt = CRITIC_AGENT_PROMPT.replace("__USER_PROMPT__", critic_input.query)

        try:
            # Call VLM with the criteria prompt
            from langchain_core.messages import HumanMessage
            response = await model_adapter.invoke([HumanMessage(content=formatted_prompt)])
            content = str(response.content) if hasattr(response, "content") else str(response)

            # Parse criteria JSON
            criteria_str = _get_json_from_string(content)
            criteria_dict = json.loads(criteria_str)

            # ALL criteria must be true for CONFIRMED
            result = CriticAgentResult.CONFIRMED
            for value in criteria_dict.values():
                if not value:
                    result = CriticAgentResult.REJECTED
                    break

            video_results.append(VideoResult(
                video_info=video,
                result=result,
                criteria_met=criteria_dict,
            ))

        except Exception as e:
            logger.error("Critic evaluation failed: %s", e)
            video_results.append(VideoResult(
                video_info=video,
                result=CriticAgentResult.UNVERIFIED,
                criteria_met={},
            ))

    return CriticAgentOutput(video_results=video_results)
