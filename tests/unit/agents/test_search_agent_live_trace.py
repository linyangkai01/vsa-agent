import json
import shutil
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage


TEST_TRACE_DIR = Path("artifacts/test-search-agent-live-trace")


@pytest.fixture
def trace_dir():
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)
    TEST_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_TRACE_DIR
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)


@pytest.mark.asyncio
async def test_search_agent_logs_decomposition_tool_calls_and_answer(trace_dir, monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import SearchOutput
    from vsa_agent.tools.search import SearchResult

    trace_path = trace_dir / "search.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    async def fake_summarize_search_incidents(incidents, query):
        return "person walking near forklift"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
    )

    class FakeModelAdapter:
        async def invoke(self, messages):
            return AIMessage(
                content=json.dumps(
                    {
                        "query": "person walking near forklift",
                        "attributes": ["person", "forklift"],
                        "has_action": True,
                    }
                )
            )

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-01.mp4",
                    description="person walking near forklift",
                    start_time="2026-06-23T10:00:00",
                    end_time="2026-06-23T10:00:08",
                    sensor_id="cam-01",
                    similarity=0.93,
                    object_ids=["obj-1"],
                )
            ]
        )

    async def fake_attribute_search():
        return SearchOutput(data=[])

    result = await execute_search_agent_flow(
        SearchAgentInput(query="find a person walking near a forklift", use_critic=False),
        model_adapter=FakeModelAdapter(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
    )

    assert result.text_answer == "person walking near forklift"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "search_agent.decompose_query" in event_types
    assert "search_agent.embed_search" in event_types
    assert "search_agent.attribute_search" in event_types
    assert "search_agent.answer" in event_types
    answer_event = events[event_types.index("search_agent.answer")]
    assert answer_event["payload"]["text_answer"] == "person walking near forklift"
