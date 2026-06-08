"""Tests for Task 11 — Summary Agent (long video chunking + VLM aggregation)."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.agents.summary_agent import SummaryAgentInput
from vsa_agent.agents.summary_agent import execute_summary


# ===== Helpers =====


def _mock_vlm(captions: list[str] | None = None):
    """Mock VLM that returns given captions for each chunk."""
    if captions is None:
        captions = ["Person wearing hard hat walking near machinery"]
    mock = AsyncMock()
    mock.side_effect = captions
    return mock


def _mock_frame_extract(frames_per_chunk: int = 5):
    """Mock frame_extract that returns base64 frame stubs."""
    async def _fn(video_path, start_timestamp=0, end_timestamp=None, max_frames=10):
        return {
            "frames": [f"frame_{i}" for i in range(frames_per_chunk)],
            "duration_sec": 30.0,
            "extracted_count": frames_per_chunk,
        }
    return _fn


# ===== SummaryAgentInput Tests =====


class TestSummaryAgentInput:
    """Test the SummaryAgentInput Pydantic model."""

    def test_minimal_input(self):
        inp = SummaryAgentInput(query="Analyze safety conditions", video_path="/tmp/test.mp4")
        assert inp.query == "Analyze safety conditions"
        assert inp.chunk_duration_sec == 30
        assert inp.max_chunks == 10

    def test_custom_chunking(self):
        inp = SummaryAgentInput(
            query="Check for PPE violations",
            video_path="/tmp/long.mp4",
            chunk_duration_sec=60,
            max_chunks=5,
        )
        assert inp.chunk_duration_sec == 60
        assert inp.max_chunks == 5


# ===== execute_summary Tests =====


class TestExecuteSummary:
    """Test the execute_summary orchestration function."""

    def test_single_chunk_returns_report(self):
        """A short video (1 chunk) should produce a report string."""
        vlm = _mock_vlm(["Person detected in frame: wearing hard hat, near machinery"])

        result = asyncio.run(execute_summary(
            search_input=SummaryAgentInput(query="Safety check", video_path="/tmp/v.mp4"),
            video_duration_sec=25,
            frame_extract_fn=_mock_frame_extract(),
            video_understand_fn=vlm,
        ))

        assert isinstance(result, str)
        assert "Person detected" in result
        assert len(result) > 20

    def test_multi_chunk_aggregation(self):
        """Multiple chunks should be aggregated into a single report."""
        captions = [
            "[0.0] Worker A enters warehouse wearing hard hat",
            "[30.0] Worker A operates forklift without safety vest",
            "[60.0] Worker B walks through red zone",
        ]
        vlm = _mock_vlm(captions)

        result = asyncio.run(execute_summary(
            search_input=SummaryAgentInput(query="Safety violations", video_path="/tmp/v.mp4"),
            video_duration_sec=90,
            frame_extract_fn=_mock_frame_extract(),
            video_understand_fn=vlm,
        ))

        assert "Worker A" in result
        assert "Worker B" in result
        assert len(result) > 50

    def test_empty_video_returns_message(self):
        """Zero-duration video should return descriptive message.  """
        vlm = _mock_vlm([])

        result = asyncio.run(execute_summary(
            search_input=SummaryAgentInput(query="Check", video_path="/tmp/empty.mp4"),
            video_duration_sec=0,
            frame_extract_fn=_mock_frame_extract(0),
            video_understand_fn=vlm,
        ))

        assert isinstance(result, str)
        assert len(result) > 0
