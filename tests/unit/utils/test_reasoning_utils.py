"""Tests for utils/reasoning_utils.py."""

from vsa_agent.utils.reasoning_utils import (
    bind_reasoning_kwargs,
    get_llm_reasoning_bind_kwargs,
    get_thinking_tag,
    thinking_tag,
)


class TestThinkingTag:
    def test_wraps_content(self):
        result = thinking_tag("test reasoning")
        assert "<thinking>" in result
        assert "test reasoning" in result
        assert "</thinking>" in result


class TestBindReasoningKwargs:
    def test_filters_relevant_keys(self):
        kwargs = {"reasoning_effort": "high", "temperature": 0.1, "unrelated": "value"}
        result = bind_reasoning_kwargs(kwargs)
        assert "reasoning_effort" in result
        assert "temperature" in result
        assert "unrelated" not in result

    def test_empty_input(self):
        assert bind_reasoning_kwargs({}) == {}


class TestReasoningCompatNames:
    def test_get_thinking_tag_matches_existing_helper(self):
        assert get_thinking_tag("abc") == thinking_tag("abc")

    def test_get_llm_reasoning_bind_kwargs_matches_existing_filter(self):
        kwargs = {
            "reasoning_effort": "high",
            "temperature": 0.1,
            "filter_thinking": True,
            "unrelated": "value",
        }
        assert get_llm_reasoning_bind_kwargs(kwargs) == bind_reasoning_kwargs(kwargs)
