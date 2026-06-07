from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title='vsa-agent', description='Video Safety Analysis Agent')


class ChatRequest(BaseModel):
    message: str


@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'vsa-agent'}


@app.post('/api/chat')
async def chat(req: ChatRequest):
    from vsa_agent.agents.top_agent import agent_node, tool_node, finalize_node, decide_next, AgentState
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import InMemorySaver
    import json, asyncio

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

    async def event_stream():
        state = AgentState(current_message=req.message)
        async for chunk in compiled.astream(state, stream_mode='custom'):
            yield f'data: {json.dumps(chunk)}\\\\n\\\\n'
        yield 'data: [DONE]\\\\n\\\\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream')
