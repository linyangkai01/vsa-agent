"""Prompt generation helpers for video understanding workflows."""

from typing import Any

from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING, VLM_HUMAN_PROMPT_TEMPLATE
from vsa_agent.registry import register_tool

_DEFAULT_INTENT_GUIDANCE = (
    "Focus on directly observable details that answer the user's query. "
    "Do not hallucinate or infer facts that are not visible."
)

_ROOT_CAUSE_INTENT_GUIDANCE = (
    "Focus on root cause analysis. Describe visible causes, precursors, "
    "contributing conditions, and the sequence leading up to the event. "
    "Do not hallucinate or infer facts that are not visible."
)


def _format_context(context: dict[str, Any] | None) -> str:
    if not context:
        return ""

    lines = [f"- {key}: {context[key]}" for key in sorted(context)]
    return "\n\nContext:\n" + "\n".join(lines)


def _build_user_section(query: str) -> str:
    """Reuse the shared human-prompt shape for query wording."""
    return VLM_HUMAN_PROMPT_TEMPLATE.format(query=query)


@register_tool(
    "generate_understanding_prompt",
    description="Build a deterministic understanding prompt from a user query and intent.",
)
async def generate_understanding_prompt(
    query: str,
    intent: str | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic prompt for downstream video understanding."""
    intent_key = (intent or "").strip().lower()
    guidance = _ROOT_CAUSE_INTENT_GUIDANCE if intent_key == "root_cause" else _DEFAULT_INTENT_GUIDANCE

    return (
        f"{SYSTEM_PROMPT_VIDEO_UNDERSTANDING}\n\n{guidance}\n\n{_build_user_section(query)}{_format_context(context)}"
    )
