'''Shared pytest fixtures for vsa-agent unit tests.'''
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_llm_response():
    '''Create a mock LLM response with content and optional tool_calls.'''
    def _make(content='Test response', tool_calls=None):
        response = MagicMock()
        response.content = content
        response.tool_calls = tool_calls or []
        return response
    return _make
