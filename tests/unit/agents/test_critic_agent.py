"""Tests for Task 12 — Critic Agent (VLM-based search result verification)."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vsa_agent.agents.critic_agent import CriticAgentInput
from vsa_agent.agents.critic_agent import CriticAgentOutput
from vsa_agent.agents.critic_agent import CriticAgentResult
from vsa_agent.agents.critic_agent import VideoInfo
from vsa_agent.agents.critic_agent import VideoResult
from vsa_agent.agents.critic_agent import execute_critic
from vsa_agent.tools.search import SearchResult


# ===== Helpers =====


def _mock_vlm_response(should_confirm: bool = True):
    """Mock VLM returns JSON criteria. All true = confirmed, any false = rejected."""
    if should_confirm:
        json_str = '{"person": true, "hard hat": true, "forklift": true}'
    else:
        json_str = '{"person": true, "hard hat": false, "forklift": true}'
    adapter = MagicMock()
    response = MagicMock()
    response.content = json_str
    adapter.invoke = AsyncMock(return_value=response)
    return adapter


# ===== Model Tests =====


class TestVideoInfo:
    def test_create(self):
        vi = VideoInfo(
            sensor_id="sensor-1",
            start_timestamp="2025-01-01T10:00:00Z",
            end_timestamp="2025-01-01T10:01:00Z",
        )
        assert vi.sensor_id == "sensor-1"


class TestCriticAgentInput:
    def test_minimal(self):
        inp = CriticAgentInput(
            query="person wearing hard hat",
            videos=[VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")],
        )
        assert len(inp.videos) == 1
        assert inp.evaluation_count is None


# ===== execute_critic Tests =====


class TestExecuteCritic:
    def test_confirms_matching_result(self):
        """VLM returns all criteria true → CONFIRMED."""
        inp = CriticAgentInput(
            query="person with hard hat",
            videos=[VideoInfo(sensor_id="cam1", start_timestamp="t1", end_timestamp="t2")],
        )
        vlm = _mock_vlm_response(should_confirm=True)

        result = asyncio.run(execute_critic(inp, model_adapter=vlm))
        assert isinstance(result, CriticAgentOutput)
        assert len(result.video_results) == 1
        assert result.video_results[0].result == CriticAgentResult.CONFIRMED

    def test_rejects_non_matching_result(self):
        """VLM returns any criterion false → REJECTED."""
        inp = CriticAgentInput(
            query="person with hard hat",
            videos=[VideoInfo(sensor_id="cam1", start_timestamp="t1", end_timestamp="t2")],
        )
        vlm = _mock_vlm_response(should_confirm=False)

        result = asyncio.run(execute_critic(inp, model_adapter=vlm))
        assert result.video_results[0].result == CriticAgentResult.REJECTED

    def test_handles_bad_vlm_response(self):
        """Malformed VLM response → UNVERIFIED."""
        inp = CriticAgentInput(
            query="test",
            videos=[VideoInfo(sensor_id="cam1", start_timestamp="t1", end_timestamp="t2")],
        )
        adapter = MagicMock()
        adapter.invoke = AsyncMock(return_value=MagicMock(content="not json"))
        result = asyncio.run(execute_critic(inp, model_adapter=adapter))
        assert result.video_results[0].result == CriticAgentResult.UNVERIFIED
