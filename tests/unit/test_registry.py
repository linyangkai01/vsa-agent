"""Tests for registry.py."""
import pytest
from vsa_agent.registry import ToolRegistry, register_tool

class TestRegisterTool:
    def test_registers_function(self):
        @register_tool("test_tool", description="A test tool")
        async def my_tool(x: int) -> int:
            return x + 1
        tools = ToolRegistry.get_all()
        assert "test_tool" in tools

class TestToolRegistry:
    def test_get_returns_none_for_missing(self):
        assert ToolRegistry.get("nonexistent_tool") is None

    def test_list_tools_returns_list(self):
        tools_list = ToolRegistry.list_tools()
        assert isinstance(tools_list, list)
        for t in tools_list:
            assert "name" in t
