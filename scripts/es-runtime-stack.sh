#!/usr/bin/env bash
set -Eeuo pipefail

API_PORT=8000
ES_PORT=9200
UI_PORT=3000
INDEX="vsa-video-embeddings"
CONDA_ENV=""
TIMEOUT_SEC=90
STOP_ELASTICSEARCH=0
SMOKE_ONLY=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/es-runtime-stack.sh [options]

Options:
  --api-port PORT            FastAPI port. Default: 8000
  --es-port PORT             Elasticsearch port. Default: 9200
  --ui-port PORT             Original UI port. Default: 3000
  --smoke-only               Exit after smoke validation.
  --index NAME               Elasticsearch index. Default: vsa-video-embeddings
  --conda-env NAME           Run Python through conda run -n NAME.
  --timeout-sec SECONDS      Startup timeout. Default: 90
  --stop-elasticsearch       Stop Docker Compose Elasticsearch on exit.
  -ApiPort PORT              PowerShell-style alias for --api-port.
  -EsPort PORT               PowerShell-style alias for --es-port.
  -Index NAME                PowerShell-style alias for --index.
  -CondaEnv NAME             PowerShell-style alias for --conda-env.
  -TimeoutSec SECONDS        PowerShell-style alias for --timeout-sec.
  -StopElasticsearch         PowerShell-style alias for --stop-elasticsearch.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port|-ApiPort)
      API_PORT="$2"
      shift 2
      ;;
    --es-port|-EsPort)
      ES_PORT="$2"
      shift 2
      ;;
    --ui-port|-UiPort) UI_PORT="$2"; shift 2 ;;
    --smoke-only|-SmokeOnly) SMOKE_ONLY=1; shift ;;
    --index|-Index)
      INDEX="$2"
      shift 2
      ;;
    --conda-env|-CondaEnv)
      CONDA_ENV="$2"
      shift 2
      ;;
    --timeout-sec|-TimeoutSec)
      TIMEOUT_SEC="$2"
      shift 2
      ;;
    --stop-elasticsearch|-StopElasticsearch)
      STOP_ELASTICSEARCH=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime/es-stack"
CONFIG_PATH="$RUNTIME_DIR/config.yaml"
API_LOG_PATH="$RUNTIME_DIR/api.log"
API_ERR_LOG_PATH="$RUNTIME_DIR/api.err.log"
API_URL="http://127.0.0.1:${API_PORT}"
API_HEALTH_URL="${API_URL}/health"
ES_ENDPOINT="http://127.0.0.1:${ES_PORT}"
API_PID=""
UI_PID=""

port_listener_pids() { lsof -ti "TCP:$1" -sTCP:LISTEN 2>/dev/null || true; }
wait_for_port_free() { local deadline=$((SECONDS + TIMEOUT_SEC)); while [[ -n "$(port_listener_pids "$1")" ]]; do (( SECONDS >= deadline )) && { echo "ERROR: port $1 was not released" >&2; return 1; }; sleep 1; done; }
reclaim_port() { local pid; for pid in $(port_listener_pids "$1"); do echo "Reclaiming port $1 from PID $pid: $(ps -p "$pid" -o args=)"; kill -TERM "$pid" || true; done; wait_for_port_free "$1"; }

cleanup() {
  if [[ -n "$UI_PID" ]] && kill -0 "$UI_PID" >/dev/null 2>&1; then
    kill -- "-$UI_PID" >/dev/null 2>&1 || true
    wait "$UI_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill -- "-$API_PID" >/dev/null 2>&1 || true
    wait "$API_PID" >/dev/null 2>&1 || true
  fi

  if [[ "$STOP_ELASTICSEARCH" == "1" ]]; then
    (
      cd "$REPO_ROOT"
      docker compose -f docker-compose.es.yml down
    )
  fi

  [[ -f "$API_LOG_PATH" ]] && echo "API log: $API_LOG_PATH"
  [[ -f "$API_ERR_LOG_PATH" ]] && echo "API error log: $API_ERR_LOG_PATH"
  [[ -f "$CONFIG_PATH" ]] && echo "Temporary config retained: $CONFIG_PATH"
}
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command '$1' was not found on PATH" >&2
    exit 127
  fi
}

python_cmd() {
  if [[ -n "$CONDA_ENV" ]]; then
    conda run -n "$CONDA_ENV" python "$@"
  else
    python "$@"
  fi
}

port_available() {
  python -c "import socket,sys
port=int(sys.argv[1])
s=socket.socket()
try:
    s.bind(('127.0.0.1', port))
except OSError:
    sys.exit(1)
finally:
    s.close()" "$1"
}

write_search_config() {
  python - "$REPO_ROOT/config.yaml" "$CONFIG_PATH" "$ES_ENDPOINT" "$INDEX" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
endpoint = sys.argv[3]
index = sys.argv[4]

raw = source.read_text(encoding="utf-8")
search_block = f"""search:
  enabled: true
  es_endpoint: {endpoint}
  embed_index: {index}
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: true
  force_mock_embedding: true
"""

pattern = re.compile(r"(?ms)^search:\r?\n(?:^[ \t]+.*\r?\n?)*")
if pattern.search(raw):
    updated = pattern.sub(search_block + "\n", raw, count=1)
else:
    updated = raw.rstrip() + "\n" + search_block + "\n"

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(updated, encoding="utf-8")
PY
}

wait_http_health() {
  local deadline
  deadline=$((SECONDS + TIMEOUT_SEC))

  while (( SECONDS < deadline )); do
    if [[ -n "$API_PID" ]] && ! kill -0 "$API_PID" >/dev/null 2>&1; then
      echo "ERROR: FastAPI process exited before health check succeeded" >&2
      return 1
    fi

    if curl -fsS "$API_HEALTH_URL" 2>/dev/null | python -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "ok" else 1)'; then
      return 0
    fi

    sleep 2
  done

  echo "ERROR: FastAPI did not become reachable at $API_HEALTH_URL within $TIMEOUT_SEC seconds" >&2
  return 1
}

require_command docker
require_command curl
require_command python
require_command setsid
if [[ -n "$CONDA_ENV" ]]; then
  require_command conda
fi

mkdir -p "$RUNTIME_DIR"
cd "$REPO_ROOT"

for port in "$ES_PORT" "$API_PORT" "$UI_PORT"; do reclaim_port "$port"; done

export VSA_ES_PORT="$ES_PORT"
export VSA_ES_CONTAINER_NAME="vsa-agent-es"
docker compose -f docker-compose.es.yml up -d

deadline=$((SECONDS + TIMEOUT_SEC))
until curl -fsS "$ES_ENDPOINT" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: Elasticsearch did not become reachable at $ES_ENDPOINT within $TIMEOUT_SEC seconds" >&2
    exit 1
  fi
  sleep 2
done

write_search_config

export VSA_CONFIG="$CONFIG_PATH"
export PYTHONPATH="$REPO_ROOT/src"

if [[ -n "$CONDA_ENV" ]]; then
  setsid conda run -n "$CONDA_ENV" python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG_PATH" 2>"$API_ERR_LOG_PATH" &
else
  setsid python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG_PATH" 2>"$API_ERR_LOG_PATH" &
fi
API_PID=$!

wait_http_health

python_cmd scripts/es_ingest_smoke.py \
  --api-url "$API_URL" \
  --es-endpoint "$ES_ENDPOINT" \
  --index "$INDEX" \
  --insecure

echo "PASS: ES runtime stack validation succeeded"
echo "  api: $API_URL"
echo "  es:  $ES_ENDPOINT"
echo "  index: $INDEX"
echo "  config: $CONFIG_PATH"
if [[ "$SMOKE_ONLY" == "0" ]]; then
  NEXT_PUBLIC_ENABLE_SEARCH_TAB=true NEXT_PUBLIC_AGENT_API_URL_BASE="${API_URL}/api/v1" PORT="$UI_PORT" setsid bash "$SCRIPT_DIR/run_original_ui_vss.sh" >"$RUNTIME_DIR/ui.log" 2>"$RUNTIME_DIR/ui.err.log" &
  UI_PID=$!
  wait "$UI_PID"
fi
