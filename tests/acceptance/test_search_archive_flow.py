import pytest

from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.agents.search_agent import execute_search_agent_flow
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


@pytest.mark.asyncio
async def test_local_archive_search_returns_matching_video_result():
    async def local_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="warehouse-safety-demo.mp4",
                    description="worker walking near forklift in loading area",
                    start_time="2026-06-23T10:00:00",
                    end_time="2026-06-23T10:00:08",
                    sensor_id="warehouse-cam-01",
                    screenshot_url="",
                    similarity=0.93,
                    object_ids=["person-1", "forklift-1"],
                )
            ]
        )

    result = await execute_search_agent_flow(
        SearchAgentInput(
            query="find a worker walking near a forklift",
            agent_mode=False,
            use_critic=False,
            use_attribute_search=False,
        ),
        embed_search=local_embed_search,
    )

    assert result.search_output.data
    first = result.search_output.data[0]
    assert first.video_name == "warehouse-safety-demo.mp4"
    assert first.description == "worker walking near forklift in loading area"
    assert first.start_time == "2026-06-23T10:00:00"
    assert first.end_time == "2026-06-23T10:00:08"
    assert first.sensor_id == "warehouse-cam-01"
    assert first.similarity >= 0.9
    assert first.object_ids == ["person-1", "forklift-1"]
    assert result.incidents
    assert "forklift" in result.text_answer.lower()
