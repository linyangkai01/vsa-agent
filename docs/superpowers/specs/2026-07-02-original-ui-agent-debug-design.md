# Original UI Agent Debug Integration Design

Date: 2026-07-02

## Goal

Use the original NVIDIA VSS UI as a temporary browser-based test shell for `vsa-agent` agent debugging. The first version should let a user open the original UI, send chat prompts, observe TopAgent responses, and inspect intermediate tool activity without rebuilding a custom frontend yet.

This supports the project goal of replacing NVIDIA runtime dependencies with open-source/local equivalents while preserving useful VSS business flow behavior.

## Current Context

`vsa-agent` already has a FastAPI app with `/api/chat`, which streams internal `AgentMessageChunk` SSE frames from the TopAgent graph.

The original UI sends chat messages to its own Next.js `/api/chat` route. That proxy reads `chatCompletionURL`, converts UI conversation messages into an OpenAI-like request payload, then forwards the request to the configured backend endpoint. For HTTP chat streaming, the original UI expects a backend endpoint such as `/chat/stream` that returns SSE frames shaped like OpenAI chat deltas:

```text
data: {"choices":[{"delta":{"content":"..."}}]}
data: [DONE]
```

The original UI can also display intermediate steps when the stream includes:

```text
intermediate_data: {"name":"...", "payload":"...", "status":"..."}
```

Its proxy converts these intermediate events into `<intermediatestep>...</intermediatestep>` blocks for the browser.

## Design

Add a compatibility layer to `vsa-agent` instead of modifying the original UI. The original UI remains a mostly unchanged interface-testing shell and is configured through environment variables.

### Backend Endpoints

Keep the existing `/api/chat` endpoint unchanged for current internal tests and clients.

Add a new `POST /chat/stream` endpoint that accepts OpenAI-like chat payloads:

```json
{
  "messages": [
    {"role": "user", "content": "Analyze the configured video and identify safety risks."}
  ]
}
```

The endpoint extracts the latest user message, runs the existing TopAgent graph, and streams original-UI-compatible output.

### Stream Mapping

Map TopAgent stream chunks to UI-compatible stream events:

- `thought` becomes `intermediate_data` with a step name such as `Thought`.
- `tool_call` becomes `intermediate_data` with a step name such as `Tool Call`.
- `error` becomes `intermediate_data` with `status: "error"` and also emits readable response text when appropriate.
- `final` becomes OpenAI-style SSE delta content.
- End of stream emits `data: [DONE]`.

The compatibility endpoint should also include `Conversation-Id` and `User-Message-ID` headers in trace metadata when present, so browser runs can be correlated with backend logs.

### UI Configuration

For the first test shell, configure the original UI to use HTTP streaming mode:

```bash
NEXT_PUBLIC_WEB_SOCKET_DEFAULT_ON=false
NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS=true
NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL=http://127.0.0.1:8000/chat/stream
```

When using the VSS app sidebar/main chat, keep `NEXT_PUBLIC_AGENT_API_URL_BASE` only for search/upload panels. Chat itself is driven by `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL`.

### Scope

In scope:

- Browser chat against TopAgent through the original UI.
- HTTP streaming compatibility for `/chat/stream`.
- Intermediate thought/tool visibility in the UI.
- Minimal docs for starting backend and original UI together.
- Unit tests for request parsing and stream event formatting.

Out of scope for this first version:

- WebSocket/HITL compatibility.
- Original UI video upload compatibility.
- Full VST/video-management API emulation.
- Custom `vsa-agent` frontend design.
- Multi-video archive UI.

## Error Handling

Invalid or empty message payloads return HTTP 400 with a clear text error.

Unexpected TopAgent exceptions should be converted into a stream-visible intermediate error event and then close the stream with `data: [DONE]`. Server logs should retain the exception details for debugging.

If the model or tool call fails inside the existing graph loop, the endpoint should preserve the current graph behavior and expose the failure as intermediate evidence rather than silently swallowing it.

## Testing

Add unit tests that verify:

- `/chat/stream` accepts OpenAI-like `messages`.
- The latest user message is selected as the TopAgent prompt.
- `thought`, `tool_call`, and `final` chunks are serialized into original-UI-compatible streaming frames.
- Empty messages return 400.
- Existing `/api/chat` behavior is not removed.

Manual acceptance:

1. Start `vsa-agent` backend.
2. Start the original UI with `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL` pointing at `/chat/stream`.
3. Send a prompt from the browser.
4. Confirm final answer appears in the chat.
5. Confirm intermediate tool activity appears when `NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS=true`.
6. Confirm backend live trace/log artifacts still provide replay/debug context.

## Open Decisions

The first implementation should not modify original UI source code unless the environment-only setup proves impossible. If the original UI proxy behavior changes during setup, prefer adding a small documented UI env example over forking the UI.
