#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vsa-agent}"

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

cd "${ROOT_DIR}"
conda run -n "${CONDA_ENV_NAME}" uvicorn vsa_agent.api.routes:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null; then
    export NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL="${NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/chat/stream}"
    export NEXT_PUBLIC_AGENT_API_URL_BASE="${NEXT_PUBLIC_AGENT_API_URL_BASE:-http://${BACKEND_HOST}:${BACKEND_PORT}/api/v1}"
    exec "${ROOT_DIR}/scripts/run_original_ui_vss.sh"
  fi
  sleep 1
done

echo "Timed out waiting for backend health at http://${BACKEND_HOST}:${BACKEND_PORT}/health" >&2
exit 1
