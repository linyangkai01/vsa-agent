from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from vsa_agent.agents.data_models import AgentState

app = FastAPI(title='vsa-agent', description='Video Safety Analysis Agent')


class ChatRequest(BaseModel):
    message: str


@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'vsa-agent'}


@app.post('/api/chat')
async def chat(req: ChatRequest):
    import json
    from vsa_agent.agents.top_agent import build_graph

    graph = await build_graph()

    async def event_stream():
        state = AgentState(current_message=HumanMessage(content=req.message))
        async for chunk in graph.astream(state, stream_mode='custom'):
            yield f'data: {json.dumps(chunk.model_dump())}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream')
