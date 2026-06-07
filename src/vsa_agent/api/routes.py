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
    import json, asyncio
    from vsa_agent.agents.top_agent import build_graph, AgentState

    graph = await build_graph()

    async def event_stream():
        state = AgentState(current_message=req.message)
        async for chunk in graph.astream(state, stream_mode='custom'):
            yield f'data: {json.dumps(chunk.model_dump())}
'
        yield 'data: [DONE]
'

    return StreamingResponse(event_stream(), media_type='text/event-stream')
