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
