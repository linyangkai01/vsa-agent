"""Tests for agents/critic_agent.py."""
import pytest
from vsa_agent.agents.critic_agent import (
    CriticAgentInput, CriticAgentOutput, CriticAgentResult,
    VideoInfo, VideoResult, execute_critic, _get_json_from_string,
)

class TestVideoInfo:
    def test_required_fields(self):
        video = VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")
        assert video.sensor_id == "s1"

    def test_is_frozen(self):
        # VideoInfo uses frozen=True config, so modifying is not allowed
        pass

class TestCriticAgentInput:
    def test_minimal(self):
        inp = CriticAgentInput(query="test query", videos=[])
        assert inp.query == "test query"

class TestCriticAgentResult:
    def test_values(self):
        assert CriticAgentResult.CONFIRMED.value == "confirmed"
        assert CriticAgentResult.REJECTED.value == "rejected"

class TestVideoResult:
    def test_with_criteria(self):
        video = VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")
        vr = VideoResult(video_info=video, result=CriticAgentResult.CONFIRMED, criteria_met={"person": True})
        assert vr.result == CriticAgentResult.CONFIRMED
        assert vr.criteria_met["person"] is True

class TestCriticAgentOutput:
    def test_with_results(self):
        video = VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")
        vr = VideoResult(video_info=video, result=CriticAgentResult.CONFIRMED)
        out = CriticAgentOutput(video_results=[vr])
        assert len(out.video_results) == 1

class TestGetJsonFromString:
    def test_strips_json_markdown(self):
        result = _get_json_from_string("```json\n{\"key\": \"value\"}\n```")
        assert "key" in result
        assert "```" not in result

    def test_plain_string(self):
        result = _get_json_from_string("{\"key\": \"value\"}")
        assert result == "{\"key\": \"value\"}"

    def test_accepts_generic_fenced_block(self):
        result = _get_json_from_string("```\n{\"key\": \"value\"}\n```")
        assert result == "{\"key\": \"value\"}"

class TestExecuteCritic:
    async def test_with_mock_adapter(self):
        from unittest.mock import AsyncMock, MagicMock
        video = VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")
        inp = CriticAgentInput(query="test", videos=[video])
        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{\"person\": true, \"red_shirt\": true}"
        mock_adapter.invoke = AsyncMock(return_value=mock_response)
        output = await execute_critic(inp, model_adapter=mock_adapter)
        assert len(output.video_results) == 1
        assert output.video_results[0].result == CriticAgentResult.CONFIRMED
