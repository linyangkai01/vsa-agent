"""Tests for utils/time_convert.py."""

from datetime import datetime
from datetime import timezone

import pytest

from vsa_agent.utils.time_convert import datetime_to_iso8601
from vsa_agent.utils.time_convert import format_timestamp
from vsa_agent.utils.time_convert import frames_to_seconds
from vsa_agent.utils.time_convert import iso8601_to_datetime
from vsa_agent.utils.time_convert import parse_iso8601_duration
from vsa_agent.utils.time_convert import seconds_to_frames

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

    def test_rejects_empty_payload(self):
        with pytest.raises(ValueError):
            parse_iso8601_duration("PT")

class TestFormatTimestamp:
    def test_hh_mm_ss(self):
        result = format_timestamp(3661.0)
        assert result == "01:01:01"

    def test_mm_ss_ms_uses_total_minutes(self):
        result = format_timestamp(3661.25, fmt="mm:ss.ms")
        assert result == "61:01.250"


class TestIsoDateTimeConversion:
    def test_iso8601_to_datetime_supports_z_suffix(self):
        result = iso8601_to_datetime("2025-01-01T10:00:00Z")
        assert result == datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_datetime_to_iso8601_outputs_z_for_utc(self):
        result = datetime_to_iso8601(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
        assert result == "2025-01-01T10:00:00Z"

class TestFramesToSeconds:
    def test_basic(self):
        assert frames_to_seconds(30, 30.0) == 1.0

class TestSecondsToFrames:
    def test_basic(self):
        assert seconds_to_frames(1.0, 30.0) == 30
