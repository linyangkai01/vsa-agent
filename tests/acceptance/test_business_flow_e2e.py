"""Acceptance: full E2E business flow."""
class TestBusinessFlow:
    async def test_full_search_and_critic_flow(self):
        from vsa_agent.tools.search import search_tool
        from vsa_agent.agents.critic_agent import CriticAgentInput, VideoInfo, execute_critic
        from unittest.mock import AsyncMock, MagicMock
        search_result = await search_tool(query="person walking")
        assert search_result is not None
        videos = [VideoInfo(sensor_id="s1", start_timestamp="t1", end_timestamp="t2")]
        inp = CriticAgentInput(query="person walking", videos=videos)
        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{\"person\": true}"
        mock_adapter.invoke = AsyncMock(return_value=mock_response)
        critic_output = await execute_critic(inp, model_adapter=mock_adapter)
        assert len(critic_output.video_results) == 1
