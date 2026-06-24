"""Tests for agents/search_agent.py."""

import inspect

import pytest

from vsa_agent.agents.search_agent import SearchAgentConfig
from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult
from vsa_agent.video_analytics.nvschema import Incident


class TestSearchAgentInput:
    def test_defaults(self):
        inp = SearchAgentInput(query="test query")
        assert inp.query == "test query"
        assert inp.agent_mode is True
        assert inp.max_results == 5

    def test_with_values(self):
        inp = SearchAgentInput(query="person walking", agent_mode=False, max_results=10, source_type="rtsp")
        assert inp.agent_mode is False
        assert inp.source_type == "rtsp"


class TestSearchAgentConfig:
    def test_defaults(self):
        cfg = SearchAgentConfig()
        assert cfg.embed_search_tool == "embed_search"


def test_to_incidents_output_delegates_to_incident_serializer(monkeypatch):
    from vsa_agent.agents.search_agent import _to_incidents_output

    called = {}

    def fake_search_output_to_incidents(output):
        called["search_output"] = output
        return []

    def fake_incidents_to_tagged_json(incidents):
        called["incidents"] = incidents
        return "<incidents>\n{\"incidents\": []}\n</incidents>"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        fake_search_output_to_incidents,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.incidents_to_tagged_json",
        fake_incidents_to_tagged_json,
        raising=False,
    )

    text = _to_incidents_output(SearchOutput(data=[]))

    assert text.startswith("<incidents>")
    assert "search_output" in called
    assert called["incidents"] == []


@pytest.mark.asyncio
async def test_execute_search_agent_flow_builds_incidents_text_and_metadata(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    called = {"incidents": False, "summary": False}
    incident = Incident(
        id="search-incident-1",
        timestamp_sec=0.0,
        duration_sec=0.0,
        description="worker approaches gate",
        severity="medium",
        category="search_hit",
        confidence=0.83,
        metadata={"sensor_id": "cam-03"},
    )

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-03.mp4",
                    description="worker approaches gate",
                    start_time="2026-06-19T10:10:00",
                    end_time="2026-06-19T10:10:05",
                    sensor_id="cam-03",
                    screenshot_url="",
                    similarity=0.83,
                    object_ids=[],
                )
            ]
        )

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=[],
            has_action=False,
        )

    def fake_search_output_to_incidents(output):
        called["incidents"] = True
        assert output.data[0].description == "worker approaches gate"
        return [incident]

    async def fake_summarize_search_incidents(incidents, query):
        called["summary"] = True
        assert incidents == [incident]
        assert query == "worker approaches gate"
        return "worker approaches gate"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        fake_search_output_to_incidents,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="worker approaches gate", use_critic=False),
        model_adapter=object(),
        embed_search=fake_embed_search,
    )

    assert result.search_output.data[0].description == "worker approaches gate"
    assert result.incidents == [incident]
    assert result.text_answer == "worker approaches gate"
    assert result.metadata == {
        "critic_requested": False,
        "critic_applied": False,
        "critic_error": None,
        "decomposed_query": "worker approaches gate",
        "decomposed_attributes": [],
        "decomposed_has_action": False,
    }
    assert called["incidents"] is True
    assert called["summary"] is True


@pytest.mark.asyncio
async def test_execute_search_keeps_returning_search_output():
    from vsa_agent.agents.search_agent import execute_search

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-05.mp4",
                    description="forklift enters aisle",
                    start_time="2026-06-19T11:00:00",
                    end_time="2026-06-19T11:00:06",
                    sensor_id="cam-05",
                    screenshot_url="",
                    similarity=0.91,
                    object_ids=[],
                )
            ]
        )

    result = await execute_search(
        SearchAgentInput(query="forklift enters aisle"),
        embed_search=fake_embed_search,
    )

    assert isinstance(result, SearchOutput)
    assert result.data[0].description == "forklift enters aisle"


def test_execute_search_public_signature_stays_stable():
    from vsa_agent.agents.search_agent import execute_search

    signature = inspect.signature(execute_search)

    assert list(signature.parameters) == [
        "search_input",
        "model_adapter",
        "embed_search",
        "attribute_search",
    ]


@pytest.mark.asyncio
async def test_execute_search_fusion_does_not_call_critic_when_use_critic_is_false(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import DecomposedQuery

    critic_called = False

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-11.mp4",
                    description="worker in blue jacket opens gate",
                    start_time="2026-06-19T12:00:00",
                    end_time="2026-06-19T12:00:05",
                    sensor_id="cam-11",
                    screenshot_url="",
                    similarity=0.89,
                    object_ids=[],
                )
            ]
        )

    async def fake_attribute_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-12.mp4",
                    description="worker in blue jacket near gate",
                    start_time="2026-06-19T12:00:02",
                    end_time="2026-06-19T12:00:06",
                    sensor_id="cam-12",
                    screenshot_url="",
                    similarity=0.72,
                    object_ids=[],
                )
            ]
        )

    async def fake_critic_agent(**kwargs):
        nonlocal critic_called
        critic_called = True
        return {"ok": True}

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=["worker in blue jacket"],
            has_action=True,
        )

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get",
        lambda name: fake_critic_agent if name == "critic_agent" else None,
    )

    result = await execute_search(
        SearchAgentInput(query="worker in blue jacket opens gate", use_critic=False),
        model_adapter=object(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
    )

    assert critic_called is False
    assert isinstance(result, SearchOutput)
    assert [item.video_name for item in result.data] == ["cam-11.mp4", "cam-12.mp4"]


@pytest.mark.asyncio
async def test_execute_search_agent_flow_marks_critic_applied_when_enabled(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    incident = Incident(
        id="search-incident-critic",
        timestamp_sec=0.0,
        duration_sec=0.0,
        description="worker in blue jacket opens gate",
        severity="medium",
        category="search_hit",
        confidence=0.91,
        metadata={"sensor_id": "cam-21"},
    )

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-21.mp4",
                    description="worker in blue jacket opens gate",
                    start_time="2026-06-19T13:00:00",
                    end_time="2026-06-19T13:00:05",
                    sensor_id="cam-21",
                    screenshot_url="",
                    similarity=0.91,
                    object_ids=[],
                )
            ]
        )

    async def fake_attribute_search():
        return SearchOutput(data=[])

    async def fake_critic_agent(**kwargs):
        assert kwargs["query"] == "worker in blue jacket opens gate"
        assert "videos_json" in kwargs
        return {"ok": True}

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=["worker in blue jacket"],
            has_action=True,
        )

    async def fake_summarize_search_incidents(incidents, query):
        return "worker in blue jacket opens gate"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        lambda output: [incident],
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="worker in blue jacket opens gate", use_critic=True),
        model_adapter=object(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
        config=SearchAgentConfig(enable_critic=True),
        critic_agent=fake_critic_agent,
    )

    assert result.search_output.data[0].video_name == "cam-21.mp4"
    assert result.metadata["critic_requested"] is True
    assert result.metadata["critic_applied"] is True
    assert result.metadata["critic_error"] is None
    assert result.metadata["decomposed_query"] == "worker in blue jacket opens gate"
    assert result.metadata["decomposed_attributes"] == ["worker in blue jacket"]
    assert result.metadata["decomposed_has_action"] is True


@pytest.mark.asyncio
async def test_execute_search_agent_flow_records_critic_error_and_continues(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-31.mp4",
                    description="forklift enters aisle",
                    start_time="2026-06-19T14:00:00",
                    end_time="2026-06-19T14:00:04",
                    sensor_id="cam-31",
                    screenshot_url="",
                    similarity=0.87,
                    object_ids=[],
                )
            ]
        )

    async def fake_attribute_search():
        return SearchOutput(data=[])

    async def fake_critic_agent(**kwargs):
        raise RuntimeError("critic unavailable")

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=["forklift"],
            has_action=True,
        )

    async def fake_summarize_search_incidents(incidents, query):
        return "forklift enters aisle"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        lambda output: [],
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="forklift enters aisle", use_critic=True),
        model_adapter=object(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
        config=SearchAgentConfig(enable_critic=True),
        critic_agent=fake_critic_agent,
    )

    assert result.search_output.data[0].video_name == "cam-31.mp4"
    assert result.text_answer == "forklift enters aisle"
    assert result.metadata["critic_requested"] is True
    assert result.metadata["critic_applied"] is False
    assert result.metadata["critic_error"] == "critic unavailable"
    assert result.metadata["decomposed_query"] == "forklift enters aisle"
    assert result.metadata["decomposed_attributes"] == ["forklift"]
    assert result.metadata["decomposed_has_action"] is True


@pytest.mark.asyncio
async def test_execute_search_agent_flow_uses_requested_critic_on_default_config(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    critic_called = False

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-61.mp4",
                    description="worker opens gate",
                    start_time="2026-06-19T17:00:00",
                    end_time="2026-06-19T17:00:05",
                    sensor_id="cam-61",
                    screenshot_url="",
                    similarity=0.88,
                    object_ids=[],
                )
            ]
        )

    async def fake_attribute_search():
        return SearchOutput(data=[])

    async def fake_critic_agent(**kwargs):
        nonlocal critic_called
        critic_called = True
        return {"ok": True}

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=["worker"],
            has_action=True,
        )

    async def fake_summarize_search_incidents(incidents, query):
        return "worker opens gate"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        lambda output: [],
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.registry.ToolRegistry.get",
        lambda name: fake_critic_agent if name == "critic_agent" else None,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="worker opens gate", use_critic=True),
        model_adapter=object(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
    )

    assert critic_called is True
    assert result.metadata["critic_requested"] is True
    assert result.metadata["critic_applied"] is True
    assert result.metadata["critic_error"] is None
    assert result.metadata["decomposed_query"] == "worker opens gate"
    assert result.metadata["decomposed_attributes"] == ["worker"]
    assert result.metadata["decomposed_has_action"] is True


@pytest.mark.asyncio
async def test_execute_search_agent_flow_applies_critic_for_attribute_only_path(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    critic_calls = []

    async def fake_embed_search():
        return SearchOutput(data=[])

    async def fake_attribute_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-71.mp4",
                    description="person in red vest",
                    start_time="2026-06-19T18:00:00",
                    end_time="2026-06-19T18:00:05",
                    sensor_id="cam-71",
                    screenshot_url="",
                    similarity=0.9,
                    object_ids=[],
                )
            ]
        )

    async def fake_critic_agent(**kwargs):
        critic_calls.append(kwargs)
        return {"ok": True}

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(
            query=query,
            attributes=["person in red vest"],
            has_action=False,
        )

    async def fake_summarize_search_incidents(incidents, query):
        return "person in red vest"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        lambda output: [],
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="person in red vest", use_critic=True),
        model_adapter=object(),
        embed_search=fake_embed_search,
        attribute_search=fake_attribute_search,
        critic_agent=fake_critic_agent,
    )

    assert critic_calls
    assert critic_calls[0]["query"] == "person in red vest"
    assert result.metadata["critic_requested"] is True
    assert result.metadata["critic_applied"] is True
    assert result.metadata["critic_error"] is None
    assert result.metadata["decomposed_query"] == "person in red vest"
    assert result.metadata["decomposed_attributes"] == ["person in red vest"]
    assert result.metadata["decomposed_has_action"] is False

@pytest.mark.asyncio
async def test_execute_search_agent_flow_applies_critic_for_embed_only_path(monkeypatch):
    from vsa_agent.agents.search_agent import execute_search_agent_flow
    from vsa_agent.tools.search import DecomposedQuery

    critic_calls = []

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-72.mp4",
                    description="forklift leaves loading dock",
                    start_time="2026-06-19T18:05:00",
                    end_time="2026-06-19T18:05:08",
                    sensor_id="cam-72",
                    screenshot_url="",
                    similarity=0.86,
                    object_ids=[],
                )
            ]
        )

    async def fake_critic_agent(**kwargs):
        critic_calls.append(kwargs)
        return {"ok": True}

    async def fake_decompose_query(query, model_adapter):
        return DecomposedQuery(query=query, attributes=[], has_action=True)

    async def fake_summarize_search_incidents(incidents, query):
        return "forklift leaves loading dock"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.decompose_query",
        fake_decompose_query,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        lambda output: [],
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
        raising=False,
    )

    result = await execute_search_agent_flow(
        SearchAgentInput(query="forklift leaves loading dock", use_critic=True),
        model_adapter=object(),
        embed_search=fake_embed_search,
        critic_agent=fake_critic_agent,
    )

    assert critic_calls
    assert critic_calls[0]["query"] == "forklift leaves loading dock"
    assert result.metadata["critic_requested"] is True
    assert result.metadata["critic_applied"] is True
    assert result.metadata["critic_error"] is None
    assert result.metadata["decomposed_query"] == "forklift leaves loading dock"
    assert result.metadata["decomposed_attributes"] == []
    assert result.metadata["decomposed_has_action"] is True

@pytest.mark.asyncio
async def test_search_agent_tool_returns_text_answer_from_agent_flow(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentExecutionResult
    from vsa_agent.agents.search_agent import search_agent_tool

    flow_calls = []

    async def fake_execute_search_agent_flow(search_input, **kwargs):
        flow_calls.append((search_input, kwargs))
        return SearchAgentExecutionResult(
            search_output=SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-81.mp4",
                        description="worker closes gate",
                        start_time="2026-06-19T19:00:00",
                        end_time="2026-06-19T19:00:06",
                        sensor_id="cam-81",
                        screenshot_url="",
                        similarity=0.84,
                        object_ids=[],
                    )
                ]
            ),
            incidents=[],
            text_answer="worker closes gate after inspection",
            metadata={},
        )

    async def fake_execute_search(search_input):
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-legacy.mp4",
                    description="legacy search result",
                    start_time="2026-06-19T19:10:00",
                    end_time="2026-06-19T19:10:05",
                    sensor_id="cam-legacy",
                    screenshot_url="",
                    similarity=0.5,
                    object_ids=[],
                )
            ]
        )

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.execute_search_agent_flow",
        fake_execute_search_agent_flow,
        raising=False,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.execute_search",
        fake_execute_search,
        raising=False,
    )

    answer = await search_agent_tool("worker closes gate", agent_mode=False, max_results=3)

    assert answer == "worker closes gate after inspection"
    assert flow_calls
    assert flow_calls[0][0].query == "worker closes gate"
    assert flow_calls[0][0].agent_mode is False
    assert flow_calls[0][0].max_results == 3

