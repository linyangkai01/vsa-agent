#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vsa-agent}"
CONFIG_PATH="${VSA_CONFIG:-${ROOT_DIR}/config.yaml}"
BACKEND_PROBE_TIMEOUT_SECONDS="${BACKEND_PROBE_TIMEOUT_SECONDS:-45}"
RESTART_EXISTING_BACKEND_ON_PROBE_FAIL="${RESTART_EXISTING_BACKEND_ON_PROBE_FAIL:-true}"
FORCE_RESTART_BACKEND="${FORCE_RESTART_BACKEND:-false}"

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

backend_listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true
    return 0
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "${BACKEND_PORT}" 2>/dev/null | tr ' ' '\n' || true
    return 0
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :${BACKEND_PORT}" 2>/dev/null \
      | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' \
      | sort -u
    return 0
  fi
}

stop_existing_backend() {
  local pid args stopped=0
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    if ! args="$(ps -p "${pid}" -o args= 2>/dev/null)"; then
      continue
    fi
    if [[ "${args}" != *"uvicorn"* && "${args}" != *"vsa_agent.api.routes"* ]]; then
      echo "Refusing to stop PID ${pid}; it does not look like the vsa-agent uvicorn backend: ${args}" >&2
      continue
    fi
    echo "Stopping stale backend PID ${pid}: ${args}"
    kill "${pid}" >/dev/null 2>&1 || true
    stopped=1
  done < <(backend_listener_pids)

  if [[ "${stopped}" != "1" ]]; then
    echo "Could not find a safe vsa-agent backend process to stop on port ${BACKEND_PORT}." >&2
    return 1
  fi

  for _ in $(seq 1 15); do
    if ! curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for stale backend on port ${BACKEND_PORT} to stop." >&2
  return 1
}

cd "${ROOT_DIR}"

export VSA_CONFIG="${CONFIG_PATH}"
export VSA_ORIGINAL_UI_TRACE_ROOT="${VSA_ORIGINAL_UI_TRACE_ROOT:-${ROOT_DIR}/artifacts/original-ui-chat-runs}"

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
  echo "Existing backend found at http://${BACKEND_HOST}:${BACKEND_PORT}"
  if [[ "${FORCE_RESTART_BACKEND}" == "true" ]]; then
    echo "FORCE_RESTART_BACKEND=true; restarting backend before launching UI."
    if ! stop_existing_backend; then
      echo "Stop the process currently using port ${BACKEND_PORT}, then restart this script." >&2
      exit 2
    fi
    conda run -n "${CONDA_ENV_NAME}" uvicorn vsa_agent.api.routes:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
    BACKEND_PID=$!
  elif probe_existing_backend; then
    echo "Using existing backend at http://${BACKEND_HOST}:${BACKEND_PORT}"
  else
    echo "The existing backend is healthy but not usable for original UI chat." >&2
    if [[ "${RESTART_EXISTING_BACKEND_ON_PROBE_FAIL}" == "true" ]]; then
      echo "Attempting to stop the stale backend on port ${BACKEND_PORT} and start a fresh one."
      if ! stop_existing_backend; then
        echo "Stop the process currently using port ${BACKEND_PORT}, then restart this script so it can launch a backend with the config.local.yaml key." >&2
        exit 2
      fi
      conda run -n "${CONDA_ENV_NAME}" uvicorn vsa_agent.api.routes:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
      BACKEND_PID=$!
    else
      echo "Stop the process currently using port ${BACKEND_PORT}, then restart this script so it can launch a backend with the config.local.yaml key." >&2
      exit 2
    fi
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
