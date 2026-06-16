"""Acceptance: critic flow."""
class TestCriticFlow:
    async def test_all_videos_confirmed(self):
        from vsa_agent.agents.critic_agent import CriticAgentInput, VideoInfo, execute_critic
        from unittest.mock import AsyncMock, MagicMock
        videos = [VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")]
        inp = CriticAgentInput(query="test", videos=videos)
        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{\"person\": true, \"action\": true}"
        mock_adapter.invoke = AsyncMock(return_value=mock_response)
        output = await execute_critic(inp, model_adapter=mock_adapter)
        assert len(output.video_results) == 1
        assert output.video_results[0].result.value == "confirmed"

    async def test_partial_rejection(self):
        from vsa_agent.agents.critic_agent import CriticAgentInput, VideoInfo, execute_critic
        from unittest.mock import AsyncMock, MagicMock
        videos = [VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")]
        inp = CriticAgentInput(query="test", videos=videos)
        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{\"person\": false, \"action\": false}"
        mock_adapter.invoke = AsyncMock(return_value=mock_response)
        output = await execute_critic(inp, model_adapter=mock_adapter)
        assert len(output.video_results) == 1
