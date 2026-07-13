from vsa_agent.registry import register_tool


@register_tool("echo", description="Echo back the input message")
async def echo_tool(message: str) -> str:
    """First tool: echoes the input back. Minimal example of tool registration."""
    return f"Echo: {message}"
