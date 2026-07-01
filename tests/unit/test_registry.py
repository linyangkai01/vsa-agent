"""Tests for registry.py."""
import pytest
from vsa_agent.registry import ToolRegistry, register_tool
from vsa_agent.registry import temporary_tool_override

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

    def test_temporary_tool_override_restores_registered_tool(self):
        @register_tool("unit_override_tool", description="original")
        async def original_tool():
            return "original"

        async def replacement_tool():
            return "replacement"

        assert ToolRegistry.get("unit_override_tool") is original_tool
        with temporary_tool_override("unit_override_tool", replacement_tool, description="replacement"):
            assert ToolRegistry.get("unit_override_tool") is replacement_tool
            assert getattr(ToolRegistry.get("unit_override_tool"), "_tool_description") == "replacement"

        restored = ToolRegistry.get("unit_override_tool")
        assert restored is original_tool
        assert getattr(restored, "_tool_description") == "original"
