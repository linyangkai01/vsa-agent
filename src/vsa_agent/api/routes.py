from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel

from vsa_agent.agents.data_models import AgentState
from vsa_agent.api.original_ui_chat import OriginalUIChatRequest
from vsa_agent.api.original_ui_chat import extract_latest_user_text
from vsa_agent.api.rtsp_stream_api import router as rtsp_router
from vsa_agent.api.video_delete import router as video_delete_router
from vsa_agent.api.video_search_ingest import router as video_search_ingest_router

app = FastAPI(title='vsa-agent', description='Video Safety Analysis Agent')
app.router.routes.extend(rtsp_router.routes)
app.router.routes.extend(video_delete_router.routes)
app.router.routes.extend(video_search_ingest_router.routes)


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
        config = RunnableConfig(configurable={'thread_id': '1'})
        async for chunk in graph.astream(state, config=config, stream_mode='custom'):
            yield f'data: {json.dumps(chunk.model_dump())}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream')


@app.post('/chat/stream')
async def original_ui_chat_stream(req: OriginalUIChatRequest, request: Request):
    from vsa_agent.api.original_ui_chat import stream_original_ui_chat

    try:
        extract_latest_user_text(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stream = stream_original_ui_chat(
        req,
        conversation_id=request.headers.get('Conversation-Id', ''),
        user_message_id=request.headers.get('User-Message-ID', ''),
    )

    async def event_stream():
        async for frame in stream:
            yield frame

    return StreamingResponse(event_stream(), media_type='text/event-stream')
