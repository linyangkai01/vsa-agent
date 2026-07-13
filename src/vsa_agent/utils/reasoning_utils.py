"""Reasoning utilities for VLM interactions.

Provides thinking_tag formatting and keyword argument binding
for models with reasoning capabilities.
"""

from __future__ import annotations

from typing import Any


def thinking_tag(content: str) -> str:
    """Wrap content in thinking tags for models that support reasoning.

    Args:
        content: The reasoning/thinking content.

    Returns:
        Content wrapped in thinking tags.
    """
    return f"<thinking>\n{content}\n</thinking>"


def bind_reasoning_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Bind reasoning-related kwargs for model adapter calls.

    Filters and prepares kwargs relevant to reasoning configuration.

    Args:
        kwargs: Raw keyword arguments.

    Returns:
        Filtered kwargs with reasoning parameters.
    """
    reasoning_keys = {
        "reasoning_effort",
        "max_tokens",
        "temperature",
        "top_p",
        "stop",
        "filter_thinking",
    }
    return {k: v for k, v in kwargs.items() if k in reasoning_keys}


def get_thinking_tag(content: str) -> str:
    return thinking_tag(content)


def get_llm_reasoning_bind_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return bind_reasoning_kwargs(kwargs)


__all__ = [
    "thinking_tag",
    "bind_reasoning_kwargs",
    "get_thinking_tag",
    "get_llm_reasoning_bind_kwargs",
]
