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
PORT_TERMINATION_GRACE_SEC=5

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
UI_LOG_PATH="$RUNTIME_DIR/ui.log"
UI_ERR_LOG_PATH="$RUNTIME_DIR/ui.err.log"
ES_LOG_PATH="$RUNTIME_DIR/es.log"
API_URL="http://127.0.0.1:${API_PORT}"
API_HEALTH_URL="${API_URL}/health"
UI_URL="http://127.0.0.1:${UI_PORT}"
ES_ENDPOINT="http://127.0.0.1:${ES_PORT}"
API_PID=""
UI_PID=""
LOG_STREAM_PIDS=()
STACK_STARTED_AT=""

port_listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "TCP:$1" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$1" 2>/dev/null | tr ' ' '\n' || true
  else
    echo "ERROR: lsof or fuser is required to reclaim API/UI ports" >&2
    return 127
  fi
}
wait_for_port_free() {
  local port="$1" deadline=$((SECONDS + TIMEOUT_SEC))
  local force_deadline=$((SECONDS + PORT_TERMINATION_GRACE_SEC)) pids pid forced=0
  while true; do
    pids="$(port_listener_pids "$port")" || return 1
    [[ -z "$pids" ]] && return 0

    if (( SECONDS >= deadline )); then
      echo "ERROR: port $port was not released; remaining PID(s): $pids" >&2
      return 1
    fi
    if (( forced == 0 && SECONDS >= force_deadline )); then
      echo "Port $port remained occupied after TERM; forcing remaining listener(s) to stop." >&2
      for pid in $pids; do
        kill -KILL "$pid" >/dev/null 2>&1 || true
      done
      forced=1
    fi
    sleep 1
  done
}

reclaim_port() {
  local port="$1" pids pid
  pids="$(port_listener_pids "$port")" || return 1
  for pid in $pids; do
    echo "Reclaiming port $port from PID $pid: $(ps -p "$pid" -o args= 2>/dev/null || true)"
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  wait_for_port_free "$port"
}

start_file_log_stream() {
  local label="$1" path="$2"
  setsid bash -c 'tail -n 0 -F "$1" 2>&1 | sed -u "s/^/[$2] /"' bash "$path" "$label" &
  LOG_STREAM_PIDS+=("$!")
}

start_es_log_stream() {
  setsid bash -c 'docker compose -f docker-compose.es.yml logs --since "$2" -f elasticsearch 2>&1 | tee -a "$1" | sed -u "s/^/[es] /"' bash "$ES_LOG_PATH" "$STACK_STARTED_AT" &
  LOG_STREAM_PIDS+=("$!")
}

stop_log_streams() {
  local pid
  for pid in "${LOG_STREAM_PIDS[@]}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -- "-$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
}

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

  stop_log_streams

  [[ -f "$ES_LOG_PATH" ]] && echo "ES log: $ES_LOG_PATH"
  [[ -f "$API_LOG_PATH" ]] && echo "API log: $API_LOG_PATH"
  [[ -f "$API_ERR_LOG_PATH" ]] && echo "API error log: $API_ERR_LOG_PATH"
  [[ -f "$UI_LOG_PATH" ]] && echo "UI log: $UI_LOG_PATH"
  [[ -f "$UI_ERR_LOG_PATH" ]] && echo "UI error log: $UI_ERR_LOG_PATH"
  [[ -f "$CONFIG_PATH" ]] && echo "Temporary config retained: $CONFIG_PATH"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

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

verify_python_runtime() {
  python_cmd - <<'PY'
from importlib.metadata import PackageNotFoundError, version

try:
    import aiohttp  # noqa: F401
    import elasticsearch  # noqa: F401
    import uvicorn  # noqa: F401
    client_version = version("elasticsearch")
except (ImportError, PackageNotFoundError) as exc:
    raise SystemExit(
        "ERROR: Python runtime requires aiohttp and elasticsearch[async]>=8.14,<9. "
        "Install the project dependencies in the selected conda environment. "
        f"Missing dependency: {exc}"
    )

major, minor = (int(part) for part in client_version.split(".")[:2])
if (major, minor) < (8, 14) or major >= 9:
    raise SystemExit(
        "ERROR: Elasticsearch Python client must satisfy elasticsearch[async]>=8.14,<9; "
        f"found {client_version!r}."
    )
PY
}

ensure_python_runtime() {
  if verify_python_runtime; then
    return
  fi

  echo "[setup] Installing project Python dependencies into the selected runtime..." >&2
  if [[ -n "$CONDA_ENV" ]]; then
    conda run -n "$CONDA_ENV" python -m pip install --upgrade -e '.[dev]'
  else
    python -m pip install --upgrade -e '.[dev]'
  fi
  verify_python_runtime
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

updated = re.sub(
    r"(?m)^(recorded_video:\r?\n[ \t]+enabled:)[ \t]*(?:true|false)",
    r"\1 false",
    updated,
    count=1,
)

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(updated, encoding="utf-8")
PY
}

ensure_ui_runtime() {
  if [[ ! -f "$REPO_ROOT/.deps/node-env.sh" ]]; then
    bash "$SCRIPT_DIR/bootstrap_node.sh"
  fi
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.deps/node-env.sh"
  require_command npm
  if [[ ! -x "$REPO_ROOT/frontend/original-ui/node_modules/.bin/turbo" ]]; then
    npm run ui:install
  fi
}

wait_http_health() {
  local deadline
  deadline=$((SECONDS + TIMEOUT_SEC))

  while (( SECONDS < deadline )); do
    if [[ -n "$API_PID" ]] && ! kill -0 "$API_PID" >/dev/null 2>&1; then
      echo "ERROR: FastAPI process exited before health check succeeded" >&2
      return 1
    fi

    health_payload=$(curl -fsS "$API_HEALTH_URL" 2>/dev/null || true)
    if [[ -n "$health_payload" ]] && printf '%s' "$health_payload" | python -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "ok" else 1)'; then
      return 0
    fi

    sleep 2
  done

  echo "ERROR: FastAPI did not become reachable at $API_HEALTH_URL within $TIMEOUT_SEC seconds" >&2
  return 1
}

wait_ui_health() {
  local deadline=$((SECONDS + TIMEOUT_SEC))
  while (( SECONDS < deadline )); do
    if [[ -n "$UI_PID" ]] && ! kill -0 "$UI_PID" >/dev/null 2>&1; then
      echo "ERROR: Original UI process exited before readiness" >&2
      return 1
    fi
    if curl -fsS "$UI_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Original UI did not become reachable at $UI_URL within $TIMEOUT_SEC seconds" >&2
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
ensure_python_runtime

for port in "$API_PORT" "$UI_PORT"; do reclaim_port "$port"; done

write_search_config

export VSA_CONFIG="$CONFIG_PATH"
export PYTHONPATH="$REPO_ROOT/src"
if [[ "$SMOKE_ONLY" == "0" ]]; then
  ensure_ui_runtime
fi

doctor_args=(scripts/runtime-doctor.py \
  --config "$CONFIG_PATH" \
  --es-endpoint "$ES_ENDPOINT" \
  --phase static \
  --port "$API_PORT" \
  --json)
if [[ "$SMOKE_ONLY" == "1" ]]; then
  doctor_args+=(--skip-ui)
else
  doctor_args+=(--port "$UI_PORT")
fi
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
python_cmd "${doctor_args[@]}"

export VSA_ES_PORT="$ES_PORT"
export VSA_ES_CONTAINER_NAME="vsa-agent-es"
STACK_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
: >"$ES_LOG_PATH"
if ! docker compose -f docker-compose.es.yml up -d; then
  echo "ERROR: Docker Compose could not start Elasticsearch." >&2
  exit 1
fi
start_es_log_stream

deadline=$((SECONDS + TIMEOUT_SEC))
until curl -fsS "$ES_ENDPOINT" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: Elasticsearch did not become reachable at $ES_ENDPOINT within $TIMEOUT_SEC seconds" >&2
    exit 1
  fi
  sleep 2
done

doctor_args=(scripts/runtime-doctor.py \
  --config "$CONFIG_PATH" \
  --es-endpoint "$ES_ENDPOINT" \
  --phase elasticsearch \
  --json)
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
python_cmd "${doctor_args[@]}"
: >"$API_LOG_PATH"
: >"$API_ERR_LOG_PATH"
start_file_log_stream "api" "$API_LOG_PATH"
start_file_log_stream "api.err" "$API_ERR_LOG_PATH"

if [[ -n "$CONDA_ENV" ]]; then
  PYTHONUNBUFFERED=1 setsid conda run --no-capture-output -n "$CONDA_ENV" python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG_PATH" 2>"$API_ERR_LOG_PATH" &
else
  PYTHONUNBUFFERED=1 setsid python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG_PATH" 2>"$API_ERR_LOG_PATH" &
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
  ensure_ui_runtime
  : >"$UI_LOG_PATH"
  : >"$UI_ERR_LOG_PATH"
  start_file_log_stream "ui" "$UI_LOG_PATH"
  start_file_log_stream "ui.err" "$UI_ERR_LOG_PATH"
  NEXT_PUBLIC_ENABLE_SEARCH_TAB=true NEXT_PUBLIC_AGENT_API_URL_BASE="/api/v1" NEXT_PUBLIC_VST_API_URL="/api/v1/vst" VSA_INTERNAL_AGENT_API_URL_BASE="${API_URL}/api/v1" PORT="$UI_PORT" setsid bash "$SCRIPT_DIR/run_original_ui_vss.sh" >"$UI_LOG_PATH" 2>"$UI_ERR_LOG_PATH" &
  UI_PID=$!
  wait_ui_health
  echo "  ui:  $UI_URL"
  if ! wait "$UI_PID"; then
    echo "ERROR: Original UI exited after readiness" >&2
    exit 1
  fi
fi
