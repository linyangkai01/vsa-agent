"""Tests for utils/reasoning_utils.py."""
from vsa_agent.utils.reasoning_utils import thinking_tag, bind_reasoning_kwargs

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
