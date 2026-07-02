# Original UI Agent Debug Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an original NVIDIA VSS UI compatible HTTP chat stream so the existing UI can be used as a browser-based TopAgent debugging shell.

**Architecture:** Keep the existing `/api/chat` endpoint intact and add a focused compatibility module for OpenAI-like request parsing plus original-UI stream formatting. The FastAPI route delegates to that module, which runs the existing TopAgent graph and maps internal `AgentMessageChunk` events into OpenAI delta SSE frames and `intermediate_data` events.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, LangGraph/LangChain messages, pytest, TestClient/httpx-compatible streaming tests.

## Global Constraints

- Preserve existing `/api/chat` behavior.
- Add `POST /chat/stream` for original UI HTTP streaming compatibility.
- Do not implement WebSocket/HITL compatibility in this change.
- Do not implement original UI video upload compatibility in this change.
- Do not modify original UI source unless environment-only setup proves impossible.
- Use HTTP streaming mode with `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL=http://127.0.0.1:8000/chat/stream`.

---

## File Structure

- Create `src/vsa_agent/api/original_ui_chat.py`: request parsing, stream frame formatting, TopAgent stream adapter.
- Modify `src/vsa_agent/api/routes.py`: register `POST /chat/stream` and delegate to `original_ui_chat`.
- Create `tests/unit/api/test_original_ui_chat.py`: pure unit tests for payload parsing and frame formatting.
- Create `tests/unit/api/test_original_ui_chat_route.py`: FastAPI route tests with a fake graph.
- Create `docs/testing/original-ui-agent-debug.md`: backend and original UI startup instructions.

---

### Task 1: Original UI Protocol Helpers

**Files:**
- Create: `src/vsa_agent/api/original_ui_chat.py`
- Test: `tests/unit/api/test_original_ui_chat.py`

**Interfaces:**
- Consumes: `vsa_agent.agents.data_models.AgentMessageChunk`, `AgentMessageChunkType`
- Produces:
  - `OriginalUIChatMessage(BaseModel)` with `role: str` and `content: str | list | dict`
  - `OriginalUIChatRequest(BaseModel)` with `messages: list[OriginalUIChatMessage]`
  - `extract_latest_user_text(request: OriginalUIChatRequest) -> str`
  - `format_openai_delta(content: str) -> str`
  - `format_done() -> str`
  - `format_intermediate_data(name: str, payload: str, status: str = "in_progress", index: int = 0, error: str = "") -> str`
  - `format_chunk_for_original_ui(chunk: AgentMessageChunk, index: int) -> list[str]`

- [ ] **Step 1: Write failing protocol tests**

Create `tests/unit/api/test_original_ui_chat.py`:

```python
import json

import pytest

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.api.original_ui_chat import OriginalUIChatRequest
from vsa_agent.api.original_ui_chat import extract_latest_user_text
from vsa_agent.api.original_ui_chat import format_chunk_for_original_ui
from vsa_agent.api.original_ui_chat import format_done
from vsa_agent.api.original_ui_chat import format_intermediate_data
from vsa_agent.api.original_ui_chat import format_openai_delta


def test_extract_latest_user_text_uses_last_user_message():
    request = OriginalUIChatRequest(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "analyze the configured video"},
        ]
    )

    assert extract_latest_user_text(request) == "analyze the configured video"


def test_extract_latest_user_text_supports_multimodal_text_parts():
    request = OriginalUIChatRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe safety risk"},
                    {"type": "image", "image_url": "ignored"},
                ],
            }
        ]
    )

    assert extract_latest_user_text(request) == "describe safety risk"


def test_extract_latest_user_text_rejects_empty_payload():
    request = OriginalUIChatRequest(messages=[{"role": "assistant", "content": "no user"}])

    with pytest.raises(ValueError, match="No user message"):
        extract_latest_user_text(request)


def test_format_openai_delta_frame_matches_original_ui_proxy():
    frame = format_openai_delta("hello")

    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame.removeprefix("data: ").strip())
    assert payload["choices"][0]["delta"]["content"] == "hello"


def test_format_done_frame():
    assert format_done() == "data: [DONE]\n\n"


def test_format_intermediate_data_frame():
    frame = format_intermediate_data(
        name="Tool Call",
        payload="Calling: video_understanding",
        status="in_progress",
        index=3,
    )

    assert frame.startswith("intermediate_data: ")
    payload = json.loads(frame.removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Call"
    assert payload["payload"] == "Calling: video_understanding"
    assert payload["status"] == "in_progress"
    assert payload["index"] == 3


def test_format_chunk_for_original_ui_maps_final_to_delta():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(type=AgentMessageChunkType.FINAL, content="final answer"),
        index=1,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["choices"][0]["delta"]["content"] == "final answer"


def test_format_chunk_for_original_ui_maps_tool_call_to_intermediate_data():
    frames = format_chunk_for_original_ui(
        AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content="Calling: video_understanding"),
        index=2,
    )

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("intermediate_data: ").strip())
    assert payload["name"] == "Tool Call"
    assert payload["payload"] == "Calling: video_understanding"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py -q
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'vsa_agent.api.original_ui_chat'`.

- [ ] **Step 3: Add protocol helper implementation**

Create `src/vsa_agent/api/original_ui_chat.py`:

```python
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType


class OriginalUIChatMessage(BaseModel):
    role: str
    content: str | list[Any] | dict[str, Any] = ""


class OriginalUIChatRequest(BaseModel):
    messages: list[OriginalUIChatMessage] = Field(default_factory=list)


def _extract_text_from_content(content: str | list[Any] | dict[str, Any]) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(content, dict):
        text = content.get("text") or content.get("content") or ""
        return text.strip() if isinstance(text, str) else ""
    return ""


def extract_latest_user_text(request: OriginalUIChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            text = _extract_text_from_content(message.content)
            if text:
                return text
    raise ValueError("No user message with text content found.")


def format_openai_delta(content: str) -> str:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_done() -> str:
    return "data: [DONE]\n\n"


def format_intermediate_data(
    name: str,
    payload: str,
    status: str = "in_progress",
    index: int = 0,
    error: str = "",
) -> str:
    event = {
        "id": f"vsa-agent-step-{index}",
        "status": status,
        "error": error,
        "name": name,
        "payload": payload,
        "parent_id": "vsa-agent",
        "intermediate_parent_id": "vsa-agent",
        "time_stamp": "default",
        "index": index,
    }
    return f"intermediate_data: {json.dumps(event, ensure_ascii=False)}\n\n"


def format_chunk_for_original_ui(chunk: AgentMessageChunk, index: int) -> list[str]:
    if chunk.type == AgentMessageChunkType.FINAL:
        return [format_openai_delta(chunk.content)]
    if chunk.type == AgentMessageChunkType.THOUGHT:
        return [format_intermediate_data("Thought", chunk.content, index=index)]
    if chunk.type == AgentMessageChunkType.TOOL_CALL:
        return [format_intermediate_data("Tool Call", chunk.content, index=index)]
    if chunk.type == AgentMessageChunkType.ERROR:
        return [format_intermediate_data("Error", chunk.content, status="error", index=index, error=chunk.content)]
    return []
```

- [ ] **Step 4: Run protocol tests to verify they pass**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py -q
```

Expected: PASS with all tests in `test_original_ui_chat.py` passing.

- [ ] **Step 5: Commit protocol helpers**

Run:

```bash
git add src/vsa_agent/api/original_ui_chat.py tests/unit/api/test_original_ui_chat.py
git commit -m "feat: add original ui chat protocol helpers"
```

Expected: commit succeeds.

---

### Task 2: TopAgent Stream Adapter

**Files:**
- Modify: `src/vsa_agent/api/original_ui_chat.py`
- Modify: `tests/unit/api/test_original_ui_chat.py`

**Interfaces:**
- Consumes:
  - `extract_latest_user_text(request: OriginalUIChatRequest) -> str`
  - `format_chunk_for_original_ui(chunk: AgentMessageChunk, index: int) -> list[str]`
  - `format_done() -> str`
- Produces:
  - `stream_original_ui_chat(request: OriginalUIChatRequest, conversation_id: str = "", user_message_id: str = "", graph_builder: Callable[[], Awaitable[Any]] | None = None) -> AsyncIterator[str]`

- [ ] **Step 1: Add failing stream adapter tests**

Append to `tests/unit/api/test_original_ui_chat.py`:

```python
from collections.abc import AsyncIterator

from vsa_agent.api.original_ui_chat import stream_original_ui_chat


class FakeGraph:
    def __init__(self):
        self.received_state = None
        self.received_config = None

    async def astream(self, state, config=None, stream_mode=None) -> AsyncIterator[AgentMessageChunk]:
        self.received_state = state
        self.received_config = config
        assert stream_mode == "custom"
        yield AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content="Analyzing...")
        yield AgentMessageChunk(type=AgentMessageChunkType.TOOL_CALL, content="Calling: video_understanding")
        yield AgentMessageChunk(type=AgentMessageChunkType.FINAL, content="The worker is on a platform.")


async def build_fake_graph(fake_graph: FakeGraph):
    return fake_graph


@pytest.mark.asyncio
async def test_stream_original_ui_chat_runs_graph_and_emits_compatible_frames():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            conversation_id="conversation-1",
            user_message_id="message-1",
            graph_builder=lambda: build_fake_graph(fake_graph),
        )
    ]

    assert any(frame.startswith("intermediate_data: ") for frame in frames)
    assert any('"The worker is on a platform."' in frame for frame in frames)
    assert frames[-1] == "data: [DONE]\n\n"
    assert fake_graph.received_state.current_message.content == "inspect video"
    assert fake_graph.received_config["configurable"]["thread_id"] == "conversation-1"


@pytest.mark.asyncio
async def test_stream_original_ui_chat_uses_default_thread_id_when_header_missing():
    fake_graph = FakeGraph()
    request = OriginalUIChatRequest(messages=[{"role": "user", "content": "inspect video"}])

    frames = [
        frame
        async for frame in stream_original_ui_chat(
            request,
            graph_builder=lambda: build_fake_graph(fake_graph),
        )
    ]

    assert frames[-1] == "data: [DONE]\n\n"
    assert fake_graph.received_config["configurable"]["thread_id"] == "original-ui-chat"
```

- [ ] **Step 2: Run stream adapter tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` for missing `stream_original_ui_chat`.

- [ ] **Step 3: Add stream adapter implementation**

Modify `src/vsa_agent/api/original_ui_chat.py` by adding these imports:

```python
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Callable

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig

from vsa_agent.agents.data_models import AgentState
from vsa_agent.observability.live_trace import write_live_trace_event
```

Append this implementation:

```python
async def stream_original_ui_chat(
    request: OriginalUIChatRequest,
    conversation_id: str = "",
    user_message_id: str = "",
    graph_builder: Callable[[], Awaitable[Any]] | None = None,
) -> AsyncIterator[str]:
    if graph_builder is None:
        from vsa_agent.agents.top_agent import build_graph

        graph_builder = build_graph

    user_text = extract_latest_user_text(request)
    thread_id = conversation_id or "original-ui-chat"
    graph = await graph_builder()
    state = AgentState(current_message=HumanMessage(content=user_text))
    config = RunnableConfig(
        configurable={
            "thread_id": thread_id,
            "checkpoint_ns": "original-ui-chat",
        }
    )

    write_live_trace_event(
        "original_ui.chat.request",
        {
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "message": user_text,
        },
    )

    index = 0
    try:
        async for chunk in graph.astream(state, config=config, stream_mode="custom"):
            for frame in format_chunk_for_original_ui(chunk, index=index):
                yield frame
            index += 1
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        write_live_trace_event(
            "original_ui.chat.error",
            {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "error": message,
            },
        )
        yield format_intermediate_data("Error", message, status="error", index=index, error=message)
        yield format_openai_delta(f"Error: {message}")
    finally:
        yield format_done()
```

- [ ] **Step 4: Run stream adapter tests to verify they pass**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py -q
```

Expected: PASS with protocol and stream adapter tests passing.

- [ ] **Step 5: Commit stream adapter**

Run:

```bash
git add src/vsa_agent/api/original_ui_chat.py tests/unit/api/test_original_ui_chat.py
git commit -m "feat: stream top agent for original ui chat"
```

Expected: commit succeeds.

---

### Task 3: FastAPI `/chat/stream` Route

**Files:**
- Modify: `src/vsa_agent/api/routes.py`
- Create: `tests/unit/api/test_original_ui_chat_route.py`

**Interfaces:**
- Consumes:
  - `OriginalUIChatRequest`
  - `stream_original_ui_chat(request, conversation_id, user_message_id)`
- Produces:
  - `POST /chat/stream`
  - Response media type: `text/event-stream`
  - Empty request response: HTTP 400 with text containing `No user message`

- [ ] **Step 1: Write failing route tests**

Create `tests/unit/api/test_original_ui_chat_route.py`:

```python
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from vsa_agent.agents.data_models import AgentMessageChunk
from vsa_agent.agents.data_models import AgentMessageChunkType
from vsa_agent.api import original_ui_chat
from vsa_agent.api.routes import app


class FakeGraph:
    async def astream(self, state, config=None, stream_mode=None) -> AsyncIterator[AgentMessageChunk]:
        yield AgentMessageChunk(type=AgentMessageChunkType.THOUGHT, content="Analyzing...")
        yield AgentMessageChunk(type=AgentMessageChunkType.FINAL, content=f"answer for {state.current_message.content}")


async def fake_build_graph():
    return FakeGraph()


def test_chat_stream_route_returns_original_ui_compatible_stream(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(original_ui_chat, "build_default_graph_for_original_ui", fake_build_graph, raising=False)
    client = TestClient(app)

    response = client.post(
        "/chat/stream",
        json={"messages": [{"role": "user", "content": "inspect video"}]},
        headers={"Conversation-Id": "conversation-1", "User-Message-ID": "message-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "intermediate_data: " in response.text
    assert '"answer for inspect video"' in response.text
    assert "data: [DONE]" in response.text


def test_chat_stream_route_rejects_empty_messages():
    client = TestClient(app)

    response = client.post("/chat/stream", json={"messages": []})

    assert response.status_code == 400
    assert "No user message" in response.text


def test_existing_api_chat_route_still_exists():
    route_paths = {route.path for route in app.routes}

    assert "/api/chat" in route_paths
    assert "/chat/stream" in route_paths
```

- [ ] **Step 2: Run route tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat_route.py -q
```

Expected: FAIL because `/chat/stream` is not registered.

- [ ] **Step 3: Add default graph builder seam**

Append to `src/vsa_agent/api/original_ui_chat.py`:

```python
async def build_default_graph_for_original_ui() -> Any:
    from vsa_agent.agents.top_agent import build_graph

    return await build_graph()
```

Change the default graph builder block in `stream_original_ui_chat` to:

```python
    if graph_builder is None:
        graph_builder = build_default_graph_for_original_ui
```

- [ ] **Step 4: Register `/chat/stream` route**

Modify `src/vsa_agent/api/routes.py` by adding imports:

```python
from fastapi import HTTPException
from fastapi import Request
```

Add the route below the existing `/api/chat` route:

```python
@app.post("/chat/stream")
async def original_ui_chat_stream(req: OriginalUIChatRequest, request: Request):
    from vsa_agent.api.original_ui_chat import stream_original_ui_chat

    try:
        stream = stream_original_ui_chat(
            req,
            conversation_id=request.headers.get("Conversation-Id", ""),
            user_message_id=request.headers.get("User-Message-ID", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_stream():
        try:
            async for frame in stream:
                yield frame
        except ValueError as exc:
            yield f"Error: {exc}\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

Also import `OriginalUIChatRequest` near the existing project imports:

```python
from vsa_agent.api.original_ui_chat import OriginalUIChatRequest
```

- [ ] **Step 5: Fix empty request validation before streaming starts**

Because `ValueError` inside an async generator is raised during iteration, update the route to validate before creating the response:

```python
from vsa_agent.api.original_ui_chat import extract_latest_user_text
```

Then add this validation inside `original_ui_chat_stream` before assigning `stream`:

```python
    try:
        extract_latest_user_text(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 6: Run route tests to verify they pass**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py tests/unit/api/test_original_ui_chat_route.py -q
```

Expected: PASS for both protocol and route tests.

- [ ] **Step 7: Commit route integration**

Run:

```bash
git add src/vsa_agent/api/original_ui_chat.py src/vsa_agent/api/routes.py tests/unit/api/test_original_ui_chat.py tests/unit/api/test_original_ui_chat_route.py
git commit -m "feat: add original ui chat stream route"
```

Expected: commit succeeds.

---

### Task 4: Original UI Startup Documentation and Regression Check

**Files:**
- Create: `docs/testing/original-ui-agent-debug.md`
- Modify: `docs/testing/live-api-validation.md` only if it links to the new UI debug doc.

**Interfaces:**
- Consumes: `/chat/stream` route from Task 3.
- Produces: Human-run startup instructions for backend and original UI.

- [ ] **Step 1: Write the UI debug doc**

Create `docs/testing/original-ui-agent-debug.md`:

````markdown
# Original UI Agent Debugging

This guide uses the original NVIDIA VSS UI as a temporary browser shell for debugging `vsa-agent`.

## Backend

From the `vsa-agent` repository:

```bash
cd /data/project/lyk/vsa-agent
conda run -n vsa-agent python -m vsa_agent config doctor
conda run -n vsa-agent uvicorn vsa_agent.api.routes:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","service":"vsa-agent"}
```

## Original UI

From the original UI repository:

```bash
cd /data/project/lyk/video-search-and-summarization-main/services/ui
export NEXT_PUBLIC_WEB_SOCKET_DEFAULT_ON=false
export NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS=true
export NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL=http://127.0.0.1:8000/chat/stream
npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui
```

If the UI runs in a browser outside the server, replace `127.0.0.1` with the server host that can reach `vsa-agent`.

## Browser Acceptance

Open the original UI and send:

```text
Analyze the configured video and identify safety risks.
```

Expected behavior:

- The final answer streams into the chat.
- Intermediate steps show TopAgent thoughts and tool calls when intermediate steps are enabled.
- Backend trace/log artifacts remain available for deeper debugging.

## Scope

This setup tests HTTP chat streaming only. WebSocket/HITL, video upload, and VST video-management compatibility are not part of this debug path.
````

- [ ] **Step 2: Run focused unit tests**

Run:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py tests/unit/api/test_original_ui_chat_route.py -q
```

Expected: PASS.

- [ ] **Step 3: Run existing route-adjacent regression tests**

Run:

```bash
python -m pytest tests/unit/test_live_trace_logging.py tests/unit/agents/test_top_agent.py tests/unit/test_live_run_validator.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full unit suite if time allows**

Run:

```bash
python -m pytest tests/unit -q --basetemp=tmp/pytest-original-ui-agent-debug
```

Expected: PASS, or only known permission warnings from old temp directories outside the chosen `--basetemp`.

- [ ] **Step 5: Commit documentation and verification updates**

Run:

```bash
git add docs/testing/original-ui-agent-debug.md
git commit -m "docs: add original ui agent debug startup guide"
```

Expected: commit succeeds.

---

## Final Verification

- [ ] Run focused tests:

```bash
python -m pytest tests/unit/api/test_original_ui_chat.py tests/unit/api/test_original_ui_chat_route.py -q
```

Expected: PASS.

- [ ] Run route smoke manually:

```bash
curl -N http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say hello from vsa-agent"}]}'
```

Expected stream contains:

```text
data: {"choices":[{"delta":{"content":
data: [DONE]
```

- [ ] Run original UI browser acceptance from `docs/testing/original-ui-agent-debug.md`.

Expected: Browser chat displays the final response and intermediate TopAgent activity.

## Self-Review Notes

- Spec coverage: `/chat/stream`, original UI OpenAI-like messages, intermediate events, unchanged `/api/chat`, tests, and startup docs are covered.
- Scope coverage: WebSocket/HITL, upload, VST emulation, custom frontend, and multi-video archive UI are explicitly excluded.
- Type consistency: All produced helper names are consumed by later tasks with matching signatures.
