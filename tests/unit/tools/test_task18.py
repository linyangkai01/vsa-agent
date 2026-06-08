"""Tests for Task 18 — VideoUnderstandingInput and thinking parser."""

import pytest

from vsa_agent.tools.video_understanding import VideoUnderstandingInput
from vsa_agent.tools.video_understanding import _parse_thinking_from_content


class TestVideoUnderstandingInput:
    def test_all_fields(self):
        inp = VideoUnderstandingInput(
            sensor_id="cam1", start_timestamp="2025-01-01T10:00:00Z",
            end_timestamp="2025-01-01T10:01:00Z", user_prompt="Describe",
        )
        assert inp.sensor_id == "cam1"
        assert inp.user_prompt == "Describe"


class TestParseThinking:
    def test_no_tags(self):
        thinking, answer = _parse_thinking_from_content("Plain answer")
        assert thinking is None
        assert answer == "Plain answer"

    def test_with_thinking(self):
        content = "<think>This is a person</think><answer>Person detected</answer>"
        thinking, answer = _parse_thinking_from_content(content)
        assert thinking == "This is a person"
        assert answer == "Person detected"

    def test_empty(self):
        thinking, answer = _parse_thinking_from_content("")
        assert thinking is None
        assert answer == ""
