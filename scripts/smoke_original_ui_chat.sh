#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
UI_URL="${UI_URL:-http://127.0.0.1:3000}"
SMOKE_MESSAGE="${SMOKE_MESSAGE:-Say hello from vsa-agent}"
RUN_UI_PROXY_SMOKE="${RUN_UI_PROXY_SMOKE:-true}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for the original UI chat smoke test." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Checking backend health at ${BACKEND_URL}/health"
curl -fsS "${BACKEND_URL}/health" >/dev/null

echo "Checking /chat/stream rejects empty chat payloads"
empty_status="$(
  curl -sS -o "${tmp_dir}/empty-response.txt" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d '{"messages":[]}' \
    "${BACKEND_URL}/chat/stream"
)"
if [[ "${empty_status}" != "400" ]]; then
  echo "Expected HTTP 400 for empty messages, got ${empty_status}." >&2
  cat "${tmp_dir}/empty-response.txt" >&2
  exit 1
fi

echo "Checking backend /chat/stream returns compatible stream frames"
curl -sS -N --max-time "${SMOKE_TIMEOUT_SECONDS:-90}" \
  -H "Content-Type: application/json" \
  -H "Conversation-Id: smoke-original-ui-chat" \
  -H "User-Message-ID: smoke-user-message" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"${SMOKE_MESSAGE}\"}]}" \
  "${BACKEND_URL}/chat/stream" \
  > "${tmp_dir}/backend-stream.txt"

if ! grep -q "data: " "${tmp_dir}/backend-stream.txt"; then
  echo "Backend stream did not include data frames." >&2
  cat "${tmp_dir}/backend-stream.txt" >&2
  exit 1
fi
if ! grep -q "data: \[DONE\]" "${tmp_dir}/backend-stream.txt"; then
  echo "Backend stream did not include the [DONE] frame." >&2
  cat "${tmp_dir}/backend-stream.txt" >&2
  exit 1
fi

echo "Backend stream smoke passed."

if [[ "${RUN_UI_PROXY_SMOKE}" == "true" ]]; then
  echo "Checking original UI proxy at ${UI_URL}/api/chat"
  curl -sS --max-time "${SMOKE_TIMEOUT_SECONDS:-90}" \
    -H "Content-Type: application/json" \
    -H "Conversation-Id: smoke-original-ui-proxy" \
    -H "User-Message-ID: smoke-ui-message" \
    -d "{\"chatCompletionURL\":\"${BACKEND_URL}/chat/stream\",\"messages\":[{\"role\":\"user\",\"content\":\"${SMOKE_MESSAGE}\"}],\"additionalProps\":{\"enableIntermediateSteps\":true}}" \
    "${UI_URL}/api/chat" \
    > "${tmp_dir}/ui-proxy.txt"

  if [[ ! -s "${tmp_dir}/ui-proxy.txt" ]]; then
    echo "UI proxy returned an empty response." >&2
    exit 1
  fi

  echo "UI proxy smoke passed. Response preview:"
  head -c 500 "${tmp_dir}/ui-proxy.txt"
  echo
fi

echo "Original UI chat smoke completed successfully."
