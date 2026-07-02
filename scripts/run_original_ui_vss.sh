#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/frontend/original-ui"

if [[ -f "${ROOT_DIR}/.deps/node-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.deps/node-env.sh"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required. Run: bash scripts/bootstrap_node.sh" >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required. Run: bash scripts/bootstrap_node.sh" >&2
  exit 1
fi

if [[ ! -d "${UI_DIR}" ]]; then
  echo "Original UI workspace not found at ${UI_DIR}" >&2
  exit 1
fi

export NEXT_PUBLIC_WEB_SOCKET_DEFAULT_ON="${NEXT_PUBLIC_WEB_SOCKET_DEFAULT_ON:-false}"
export NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS="${NEXT_PUBLIC_ENABLE_INTERMEDIATE_STEPS:-true}"
export NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL="${NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL:-http://127.0.0.1:8000/chat/stream}"
export NEXT_PUBLIC_AGENT_API_URL_BASE="${NEXT_PUBLIC_AGENT_API_URL_BASE:-http://127.0.0.1:8000/api/v1}"

cd "${UI_DIR}"
exec npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui
