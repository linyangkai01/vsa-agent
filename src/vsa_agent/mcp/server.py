from fastmcp import FastMCP

mcp = FastMCP('vsa-agent')


@mcp.tool()
async def echo(message: str) -> str:
    '''Echo back the input message — test tool for MCP protocol.'''
    from vsa_agent.registry import ToolRegistry
    fn = ToolRegistry.get('echo')
    if fn:
        return await fn(message)
    return f'Echo: {message}'


@mcp.tool()
async def list_tools() -> str:
    '''List all available tools in the VSA agent.'''
    from vsa_agent.registry import ToolRegistry
    tools = ToolRegistry.list_tools()
    import json
    return json.dumps(tools, indent=2)


@mcp.tool()
async def chat(query: str) -> str:
    '''Send a query to the VSA agent and get a response.'''
    from vsa_agent.agents.top_agent import agent_node, tool_node, finalize_node, decide_next, AgentState
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import InMemorySaver

    graph = StateGraph(AgentState)
    graph.add_node('agent', agent_node)
    graph.add_node('tool', tool_node)
    graph.add_node('finalize', finalize_node)
    graph.set_entry_point('agent')
    graph.add_conditional_edges('agent', decide_next, {
        'call_tool': 'tool',
        'respond': 'finalize',
    })
    graph.add_edge('tool', 'agent')
    graph.add_edge('finalize', END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    state = AgentState(current_message=query)
    result = await compiled.ainvoke(state)
    return result.get('final_answer', 'No response')


if __name__ == '__main__':
    mcp.run()
