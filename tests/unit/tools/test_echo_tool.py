"""Tests for tools/echo_tool.py."""
from vsa_agent.tools.echo_tool import echo_tool

class TestEchoTool:
    async def test_echo_message(self):
        result = await echo_tool(message="Hello, world!")
        assert result == "Echo: Hello, world!"

    async def test_echo_empty(self):
        result = await echo_tool(message="")
        assert result == "Echo: "
