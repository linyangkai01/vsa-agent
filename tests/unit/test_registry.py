import pytest
import asyncio
from vsa_agent.registry import ToolRegistry, register_tool, _TOOLS


class TestToolRegistry:
    def test_register_and_get(self):
        @register_tool('test_upper', description='Convert to uppercase')
        async def test_upper(message: str) -> str:
            return message.upper()

        tools = ToolRegistry.get_all()
        assert 'test_upper' in tools

        fn = ToolRegistry.get('test_upper')
        assert fn is not None

        result = asyncio.run(fn('hello'))
        assert result == 'HELLO'

        # Clean up
        del _TOOLS['test_upper']

    def test_list_tools(self):
        @register_tool('temp_list_tool', description='Test listing')
        async def temp_list_tool():
            pass

        tools = ToolRegistry.list_tools()
        names = [t['name'] for t in tools]
        assert 'temp_list_tool' in names

        del _TOOLS['temp_list_tool']

    def test_get_nonexistent_returns_none(self):
        fn = ToolRegistry.get('nonexistent_tool')
        assert fn is None
