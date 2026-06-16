"""Tests for utils/reasoning_parsing.py."""
from vsa_agent.utils.reasoning_parsing import parse_reasoning_content, ReasoningResult

class TestReasoningResult:
    def test_defaults(self):
        r = ReasoningResult()
        assert r.answer == ""
        assert r.has_reasoning is False

class TestParseReasoningContent:
    def test_no_reasoning(self):
        result = parse_reasoning_content("Simple answer")
        assert result.answer == "Simple answer"
        assert result.has_reasoning is False

    def test_with_thinking_tags(self):
        result = parse_reasoning_content("<thinking>Some reasoning</thinking>Final answer")
        assert result.answer == "Final answer"
        assert result.thinking == "Some reasoning"

    def test_with_answer_tags(self):
        result = parse_reasoning_content("Context <answer>Final answer</answer>")
        assert result.answer == "Final answer"

    def test_empty_string(self):
        result = parse_reasoning_content("")
        assert result.answer == ""

    def test_none_input(self):
        result = parse_reasoning_content(None)
        assert result.answer == ""
