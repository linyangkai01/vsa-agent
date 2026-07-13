"""Acceptance: search flow."""

import pytest


class TestSearchFlow:
    async def test_query_decomposition(self):
        from unittest.mock import AsyncMock, MagicMock

        from vsa_agent.tools.search import decompose_query

        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"query": "person walking"}'
        mock_adapter.invoke = AsyncMock(return_value=mock_response)
        result = await decompose_query("Find a person walking", model_adapter=mock_adapter)
        assert result is not None
        assert hasattr(result, "query")

    async def test_embed_only_path(self):
        from vsa_agent.tools.search import search_tool

        result = await search_tool(query="test query")
        assert result is not None

    async def test_fusion_path(self):
        from vsa_agent.tools.search import search_tool

        result = await search_tool(query="person walking", decomposed_attributes=["person"], decomposed_has_action=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_search_returns_search_output_for_default_success_flow(self, monkeypatch):
        from types import SimpleNamespace

        from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
        from vsa_agent.tools.search import DecomposedQuery, SearchOutput, SearchResult

        async def fake_decompose_query(query, model_adapter):
            return DecomposedQuery(query=query, attributes=[], has_action=False)

        async def fake_embed_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-01.mp4",
                        description="person enters loading area",
                        start_time="2026-06-19T10:00:00",
                        end_time="2026-06-19T10:00:12",
                        sensor_id="cam-01",
                        screenshot_url="",
                        similarity=0.91,
                        object_ids=[],
                    )
                ]
            )

        monkeypatch.setattr("vsa_agent.agents.search_agent.decompose_query", fake_decompose_query)

        result = await execute_search(
            SearchAgentInput(query="person enters loading area", use_critic=False),
            model_adapter=SimpleNamespace(),
            embed_search=fake_embed_search,
        )

        # Task 8.6 acceptance stays on the legacy public contract: execute_search()
        # returns SearchOutput directly rather than a new aggregate response object.
        assert isinstance(result, SearchOutput)
        assert result.data[0].video_name == "cam-01.mp4"

    @pytest.mark.asyncio
    async def test_execute_search_calls_critic_only_when_requested_in_fusion_flow(self, monkeypatch):
        from types import SimpleNamespace

        from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
        from vsa_agent.tools.search import DecomposedQuery, SearchOutput, SearchResult

        critic_calls = []

        async def fake_decompose_query(query, model_adapter):
            return DecomposedQuery(query=query, attributes=["forklift"], has_action=True)

        async def fake_embed_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-02.mp4",
                        description="forklift turns left",
                        start_time="2026-06-19T10:05:00",
                        end_time="2026-06-19T10:05:08",
                        sensor_id="cam-02",
                        screenshot_url="",
                        similarity=0.88,
                        object_ids=[],
                    )
                ]
            )

        async def fake_attribute_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-02.mp4",
                        description="forklift turns left",
                        start_time="2026-06-19T10:05:00",
                        end_time="2026-06-19T10:05:08",
                        sensor_id="cam-02",
                        screenshot_url="",
                        similarity=0.82,
                        object_ids=[],
                    )
                ]
            )

        async def fake_critic_agent(**kwargs):
            critic_calls.append(kwargs)
            return "critic-ok"

        monkeypatch.setattr("vsa_agent.agents.search_agent.decompose_query", fake_decompose_query)
        monkeypatch.setattr(
            "vsa_agent.registry.ToolRegistry.get",
            lambda name: fake_critic_agent if name == "critic_agent" else None,
        )

        result = await execute_search(
            SearchAgentInput(query="forklift turns left", use_critic=True),
            model_adapter=SimpleNamespace(),
            embed_search=fake_embed_search,
            attribute_search=fake_attribute_search,
        )

        assert isinstance(result, SearchOutput)
        assert result.data and result.data[0].video_name == "cam-02.mp4"
        assert critic_calls
        assert critic_calls[0]["query"] == "forklift turns left"
        assert "videos_json" in critic_calls[0]

    @pytest.mark.asyncio
    async def test_execute_search_skips_critic_when_disabled_in_fusion_flow(self, monkeypatch):
        from types import SimpleNamespace

        from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
        from vsa_agent.tools.search import DecomposedQuery, SearchOutput, SearchResult

        critic_calls = []

        async def fake_decompose_query(query, model_adapter):
            return DecomposedQuery(query=query, attributes=["forklift"], has_action=True)

        async def fake_embed_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-02.mp4",
                        description="forklift turns left",
                        start_time="2026-06-19T10:05:00",
                        end_time="2026-06-19T10:05:08",
                        sensor_id="cam-02",
                        screenshot_url="",
                        similarity=0.88,
                        object_ids=[],
                    )
                ]
            )

        async def fake_attribute_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-02.mp4",
                        description="forklift turns left",
                        start_time="2026-06-19T10:05:00",
                        end_time="2026-06-19T10:05:08",
                        sensor_id="cam-02",
                        screenshot_url="",
                        similarity=0.82,
                        object_ids=[],
                    )
                ]
            )

        async def fake_critic_agent(**kwargs):
            critic_calls.append(kwargs)
            return "critic-ok"

        monkeypatch.setattr("vsa_agent.agents.search_agent.decompose_query", fake_decompose_query)
        monkeypatch.setattr(
            "vsa_agent.registry.ToolRegistry.get",
            lambda name: fake_critic_agent if name == "critic_agent" else None,
        )

        result = await execute_search(
            SearchAgentInput(query="forklift turns left", use_critic=False),
            model_adapter=SimpleNamespace(),
            embed_search=fake_embed_search,
            attribute_search=fake_attribute_search,
        )

        assert isinstance(result, SearchOutput)
        assert [r.video_name for r in result.data] == ["cam-02.mp4"]
        assert critic_calls == []

    @pytest.mark.asyncio
    async def test_execute_search_degrades_when_critic_fails_in_fusion_flow(self, monkeypatch):
        from types import SimpleNamespace

        from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
        from vsa_agent.tools.search import DecomposedQuery, SearchOutput, SearchResult

        async def fake_decompose_query(query, model_adapter):
            return DecomposedQuery(query=query, attributes=["forklift"], has_action=True)

        async def fake_embed_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-03.mp4",
                        description="forklift pauses near dock",
                        start_time="2026-06-19T10:10:00",
                        end_time="2026-06-19T10:10:09",
                        sensor_id="cam-03",
                        screenshot_url="",
                        similarity=0.77,
                        object_ids=[],
                    )
                ]
            )

        async def fake_attribute_search():
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-03.mp4",
                        description="forklift pauses near dock",
                        start_time="2026-06-19T10:10:00",
                        end_time="2026-06-19T10:10:09",
                        sensor_id="cam-03",
                        screenshot_url="",
                        similarity=0.79,
                        object_ids=[],
                    )
                ]
            )

        async def failing_critic_agent(**kwargs):
            raise RuntimeError("critic unavailable")

        monkeypatch.setattr("vsa_agent.agents.search_agent.decompose_query", fake_decompose_query)
        monkeypatch.setattr(
            "vsa_agent.registry.ToolRegistry.get",
            lambda name: failing_critic_agent if name == "critic_agent" else None,
        )

        result = await execute_search(
            SearchAgentInput(query="forklift pauses near dock", use_critic=True),
            model_adapter=SimpleNamespace(),
            embed_search=fake_embed_search,
            attribute_search=fake_attribute_search,
        )

        assert isinstance(result, SearchOutput)
        assert [r.video_name for r in result.data] == ["cam-03.mp4"]

    @pytest.mark.asyncio
    async def test_execute_search_returns_empty_search_output_for_empty_results(self, monkeypatch):
        from types import SimpleNamespace

        from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
        from vsa_agent.tools.search import DecomposedQuery, SearchOutput

        async def fake_decompose_query(query, model_adapter):
            return DecomposedQuery(query=query, attributes=[], has_action=False)

        async def fake_embed_search():
            return SearchOutput(data=[])

        monkeypatch.setattr("vsa_agent.agents.search_agent.decompose_query", fake_decompose_query)

        result = await execute_search(
            SearchAgentInput(query="no match query", use_critic=False),
            model_adapter=SimpleNamespace(),
            embed_search=fake_embed_search,
        )

        assert isinstance(result, SearchOutput)
        assert result.data == []

    @pytest.mark.asyncio
    async def test_search_agent_tool_returns_text_answer_from_agent_flow(self, monkeypatch):
        from vsa_agent.agents.search_agent import SearchAgentExecutionResult, search_agent_tool
        from vsa_agent.tools.search import SearchOutput, SearchResult

        flow_calls = []

        async def fake_execute_search_agent_flow(search_input, **kwargs):
            flow_calls.append((search_input, kwargs))
            return SearchAgentExecutionResult(
                search_output=SearchOutput(data=[]),
                incidents=[],
                text_answer="answer from summarize layer",
                metadata={},
            )

        async def fake_execute_search(search_input):
            return SearchOutput(
                data=[
                    SearchResult(
                        video_name="cam-legacy.mp4",
                        description="legacy search result",
                        start_time="2026-06-19T20:00:00",
                        end_time="2026-06-19T20:00:04",
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

        answer = await search_agent_tool("summarize this search", agent_mode=False, max_results=2)

        assert answer == "answer from summarize layer"
        assert flow_calls
        assert flow_calls[0][0].query == "summarize this search"
        assert flow_calls[0][0].agent_mode is False
        assert flow_calls[0][0].max_results == 2
