"""Acceptance: search flow."""
class TestSearchFlow:
    async def test_query_decomposition(self):
        from vsa_agent.tools.search import decompose_query
        from unittest.mock import AsyncMock, MagicMock
        mock_adapter = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{\"query\": \"person walking\"}"
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
