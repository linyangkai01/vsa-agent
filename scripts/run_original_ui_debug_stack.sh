#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vsa-agent}"
CONFIG_PATH="${VSA_CONFIG:-${ROOT_DIR}/config.yaml}"
BACKEND_PROBE_TIMEOUT_SECONDS="${BACKEND_PROBE_TIMEOUT_SECONDS:-45}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required to start the vsa-agent backend." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for the backend health check." >&2
  exit 1
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
    wait "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

probe_existing_backend() {
  local probe_output
  probe_output="$(mktemp)"
  if ! curl -sS -N --max-time "${BACKEND_PROBE_TIMEOUT_SECONDS}" \
    -H "Content-Type: application/json" \
    -H "Conversation-Id: original-ui-stack-probe" \
    -H "User-Message-ID: original-ui-stack-probe" \
    -d '{"messages":[{"role":"user","content":"Say hello from vsa-agent"}]}' \
    "http://${BACKEND_HOST}:${BACKEND_PORT}/chat/stream" \
    > "${probe_output}"; then
    echo "Existing backend did not pass /chat/stream probe." >&2
    cat "${probe_output}" >&2 || true
    rm -f "${probe_output}"
    return 1
  fi

  if ! grep -q "data: \[DONE\]" "${probe_output}"; then
    echo "Existing backend probe did not include data: [DONE]." >&2
    cat "${probe_output}" >&2 || true
    rm -f "${probe_output}"
    return 1
  fi

  if grep -Eq 'OpenAIError|AuthenticationError|PermissionDeniedError|"status": "error"' "${probe_output}"; then
    echo "Existing backend probe returned a model/setup error." >&2
    cat "${probe_output}" >&2 || true
    rm -f "${probe_output}"
    return 1
  fi

  rm -f "${probe_output}"
  return 0
}

cd "${ROOT_DIR}"

export VSA_CONFIG="${CONFIG_PATH}"

echo "Validating vsa-agent runtime config"
conda run -n "${CONDA_ENV_NAME}" python -m vsa_agent config doctor --config "${VSA_CONFIG}"

MODEL_API_KEY="$(
  conda run -n "${CONDA_ENV_NAME}" python -c "import os; from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml(os.environ['VSA_CONFIG'])).llm.api_key or '')"
)"
if [[ -n "${MODEL_API_KEY}" ]]; then
  export OPENAI_API_KEY="${OPENAI_API_KEY:-${MODEL_API_KEY}}"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Model API key is missing. Set DASHSCOPE_API_KEY or add it to ignored config.local.yaml before starting the debug stack." >&2
  exit 2
fi

if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null; then
  echo "Existing backend found at http://${BACKEND_HOST}:${BACKEND_PORT}; probing /chat/stream before reuse"
  if probe_existing_backend; then
    echo "Using existing backend at http://${BACKEND_HOST}:${BACKEND_PORT}"
  else
    echo "The existing backend is healthy but not usable for original UI chat." >&2
    echo "Stop the process currently using port ${BACKEND_PORT}, then restart this script so it can launch a backend with the config.local.yaml key." >&2
    exit 2
  fi
else
  conda run -n "${CONDA_ENV_NAME}" uvicorn vsa_agent.api.routes:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
  BACKEND_PID=$!
fi

for _ in $(seq 1 30); do
  if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null; then
    export NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL="${NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/chat/stream}"
    export NEXT_PUBLIC_AGENT_API_URL_BASE="${NEXT_PUBLIC_AGENT_API_URL_BASE:-http://${BACKEND_HOST}:${BACKEND_PORT}/api/v1}"
    exec bash "${ROOT_DIR}/scripts/run_original_ui_vss.sh"
  fi
  sleep 1
done

echo "Timed out waiting for backend health at http://${BACKEND_HOST}:${BACKEND_PORT}/health" >&2
exit 1
