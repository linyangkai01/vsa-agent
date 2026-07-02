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

The original UI workspace is now vendored into this repository at `frontend/original-ui`.

Install frontend dependencies from the `vsa-agent` root:

```bash
cd /data/project/lyk/vsa-agent
bash scripts/bootstrap_node.sh
source .deps/node-env.sh
npm run ui:install
```

`ui:install` uses `npm ci`, defaults to the `https://registry.npmmirror.com` registry, and writes a full install log to `artifacts/original-ui-npm-install.log`. Override the registry when needed:

```bash
NPM_CONFIG_REGISTRY=https://registry.npmjs.org npm run ui:install
```

Run only the UI from the `vsa-agent` root:

```bash
cd /data/project/lyk/vsa-agent
bash scripts/run_original_ui_vss.sh
```

This script sets:

- `NEXT_PUBLIC_WEB_SOCKET_DEFAULT_ON=false`
- `NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS=true`
- `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL=http://127.0.0.1:8000/chat/stream`
- `NEXT_PUBLIC_AGENT_API_URL_BASE=http://127.0.0.1:8000/api/v1`

If the UI runs in a browser outside the server, override `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL` and `NEXT_PUBLIC_AGENT_API_URL_BASE` before running the script.

Run backend and UI together from the `vsa-agent` root:

```bash
cd /data/project/lyk/vsa-agent
bash scripts/run_original_ui_debug_stack.sh
```

`ui:stack:vss` starts the FastAPI backend through `conda run -n vsa-agent`, waits for `/health`, and then launches the original VSS UI.

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
