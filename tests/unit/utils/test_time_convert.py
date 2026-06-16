"""Tests for utils/time_convert.py."""
import pytest
from vsa_agent.utils.time_convert import parse_iso8601_duration, format_timestamp, frames_to_seconds, seconds_to_frames

class TestParseIso8601Duration:
    def test_seconds(self):
        assert parse_iso8601_duration("PT30S") == 30.0
    def test_minutes(self):
        assert parse_iso8601_duration("PT5M") == 300.0
    def test_hours(self):
        assert parse_iso8601_duration("PT1H") == 3600.0
    def test_invalid_format(self):
        with pytest.raises(ValueError):
            parse_iso8601_duration("invalid")

class TestFormatTimestamp:
    def test_hh_mm_ss(self):
        result = format_timestamp(3661.0)
        assert result == "01:01:01"

class TestFramesToSeconds:
    def test_basic(self):
        assert frames_to_seconds(30, 30.0) == 1.0

class TestSecondsToFrames:
    def test_basic(self):
        assert seconds_to_frames(1.0, 30.0) == 30
