from fastmcp import FastMCP

mcp = FastMCP('vsa-agent')


@mcp.tool()
async def echo(message: str) -> str:
    '''Echo back the input message.'''
    from vsa_agent.registry import ToolRegistry
    fn = ToolRegistry.get('echo')
    if fn:
        return await fn(message)
    return f'Echo: {message}'


@mcp.tool()
async def list_tools() -> str:
    '''List all available tools in the VSA agent.'''
    from vsa_agent.registry import ToolRegistry
    import json
    tools = ToolRegistry.list_tools()
    return json.dumps(tools, indent=2)


@mcp.tool()
async def chat(query: str) -> str:
    '''Send a query to the VSA agent.'''
    from vsa_agent.agents.top_agent import build_graph, AgentState

    graph = await build_graph()
    state = AgentState(current_message=query)
    result = await graph.ainvoke(state)
    return result.get('final_answer', 'No response')


if __name__ == '__main__':
    mcp.run()
