#!/usr/bin/env bash
set -Eeuo pipefail

API_PORT=8000
ES_PORT=9200
UI_PORT=3000
INDEX="vsa-video-embeddings"
CONDA_ENV=""
DATA_ROOT=""
TIMEOUT_SEC=90
STOP_ELASTICSEARCH=0
SMOKE_ONLY=0
VALIDATE=0
PORT_TERMINATION_GRACE_SEC=5
PROCESS_SHUTDOWN_GRACE_TICKS=10

usage() {
  cat <<'EOF'
Usage:
  ./scripts/es-runtime-stack.sh [options]

Options:
  --api-port PORT            FastAPI port. Default: 8000
  --es-port PORT             Elasticsearch port. Default: 9200
  --ui-port PORT             Original UI port. Default: 3000
  --index NAME               Production Elasticsearch alias. Default: vsa-video-embeddings
  --data-root PATH           Recorded-video data directory. Default: .runtime/recorded-video
  --validate                 Run an isolated validation and exit.
  --smoke-only               Compatibility alias for --validate without starting the UI.
  --conda-env NAME           Run Python through conda run -n NAME.
  --timeout-sec SECONDS      Startup timeout. Default: 90
  --stop-elasticsearch       Stop Elasticsearch on exit only when this run started it.
  -ApiPort PORT              PowerShell-style alias for --api-port.
  -EsPort PORT               PowerShell-style alias for --es-port.
  -UiPort PORT               PowerShell-style alias for --ui-port.
  -Index NAME                PowerShell-style alias for --index.
  -DataRoot PATH             PowerShell-style alias for --data-root.
  -Validate                  PowerShell-style alias for --validate.
  -SmokeOnly                 PowerShell-style alias for --smoke-only.
  -CondaEnv NAME             PowerShell-style alias for --conda-env.
  -TimeoutSec SECONDS        PowerShell-style alias for --timeout-sec.
  -StopElasticsearch         PowerShell-style alias for --stop-elasticsearch.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port|-ApiPort) API_PORT="$2"; shift 2 ;;
    --es-port|-EsPort) ES_PORT="$2"; shift 2 ;;
    --ui-port|-UiPort) UI_PORT="$2"; shift 2 ;;
    --index|-Index) INDEX="$2"; shift 2 ;;
    --data-root|-DataRoot) DATA_ROOT="$2"; shift 2 ;;
    --validate|-Validate) VALIDATE=1; shift ;;
    --smoke-only|-SmokeOnly) SMOKE_ONLY=1; VALIDATE=1; shift ;;
    --conda-env|-CondaEnv) CONDA_ENV="$2"; shift 2 ;;
    --timeout-sec|-TimeoutSec) TIMEOUT_SEC="$2"; shift 2 ;;
    --stop-elasticsearch|-StopElasticsearch) STOP_ELASTICSEARCH=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime/es-stack"
RUNS_DIR="$RUNTIME_DIR/runs"

if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: required command 'python' was not found on PATH" >&2
  exit 127
fi
RUN_ID="$(python -c 'import uuid; print(uuid.uuid4())')"
RUN_DIR="$RUNS_DIR/$RUN_ID"
LATEST_LINK="$RUNTIME_DIR/latest"
CONFIG_PATH="$RUN_DIR/config.yaml"
VALIDATION_CONFIG_PATH="$RUN_DIR/validation-config.yaml"
STACK_LOG_PATH="$RUN_DIR/stack.log"
API_LOG_PATH="$RUN_DIR/api.log"
WORKER_LOG_PATH="$RUN_DIR/worker.log"
UI_LOG_PATH="$RUN_DIR/ui.log"
ES_LOG_PATH="$RUN_DIR/es.log"
PROCESS_MANIFEST_PATH="$RUN_DIR/processes.json"
API_URL="http://127.0.0.1:${API_PORT}"
API_HEALTH_URL="${API_URL}/health"
UI_URL="http://127.0.0.1:${UI_PORT}"
ES_ENDPOINT="http://127.0.0.1:${ES_PORT}"
VALIDATION_INDEX="validation-${RUN_ID}"
VALIDATION_SMOKE_INDEX="${VALIDATION_INDEX}-legacy-smoke"
VALIDATION_DATA_ROOT="$RUN_DIR/$VALIDATION_INDEX"
API_CONFIG_PATH="$CONFIG_PATH"
STACK_STARTED_AT=""
ES_STARTED_BY_RUN=0
ES_LOG_PID=""
API_PID=""
WORKER_PID=""
UI_PID=""
declare -A PROCESS_PIDS=()
declare -A PROCESS_EXIT_RECORDED=()

mkdir -p "$RUN_DIR"
for path in "$STACK_LOG_PATH" "$API_LOG_PATH" "$WORKER_LOG_PATH" "$UI_LOG_PATH" "$ES_LOG_PATH"; do
  : >"$path"
done
if [[ -L "$LATEST_LINK" || -f "$LATEST_LINK" ]]; then
  rm -f -- "$LATEST_LINK"
elif [[ -e "$LATEST_LINK" ]]; then
  printf '[stack] ERROR: LATEST_POINTER_CONFLICT: refusing to replace directory %s\n' "$LATEST_LINK" | tee -a "$STACK_LOG_PATH" >&2
  exit 1
fi
ln -sfn "$RUN_DIR" "$LATEST_LINK"

redact_runtime_text() {
  python -u -c '
import re
import sys

def protect(text):
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)([\"'"'"'](?:api[-_]?key|access[-_]?token|token|password)[\"'"'"']\s*:\s*[\"'"'"'])[^\"'"'"']*([\"'"'"'])", r"\1[REDACTED]\2", text)
    text = re.sub(r"(?i)((?:api[-_]?key|access[-_]?token|token|password)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)data:image/[^;\s\"'"'"']+;base64,[A-Za-z0-9+/=_-]+", "[REDACTED_IMAGE]", text)
    return re.sub(r"(?i)([\"'"'"'](?:image|image_url|input_image|b64_json)[\"'"'"']\s*:\s*[\"'"'"'])[A-Za-z0-9+/=_-]{64,}([\"'"'"'])", r"\1[REDACTED_IMAGE]\2", text)

for line in sys.stdin:
    sys.stdout.write(protect(line))
    sys.stdout.flush()
'
}

log_stack() {
  local message
  message="$(printf '%s' "$*" | redact_runtime_text)"
  printf '[stack] %s\n' "$message" | tee -a "$STACK_LOG_PATH"
}

log_stack_error() {
  local message
  message="$(printf '%s' "$*" | redact_runtime_text)"
  printf '[stack] ERROR: %s\n' "$message" | tee -a "$STACK_LOG_PATH" >&2
}

run_stack_command() {
  set +e
  "$@" 2>&1 | redact_runtime_text | sed -u 's/^/[stack] /' | tee -a "$STACK_LOG_PATH"
  local status=${PIPESTATUS[0]}
  set -e
  return "$status"
}

init_process_manifest() {
  python - "$PROCESS_MANIFEST_PATH" "$RUN_ID" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {"run_id": sys.argv[2], "processes": []}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

update_process_manifest() {
  local action="$1" component="$2" value1="$3" value2="${4:-}"
  python - "$PROCESS_MANIFEST_PATH" "$action" "$component" "$value1" "$value2" <<'PY'
from datetime import UTC, datetime
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
action, component, value1, value2 = sys.argv[2:6]
payload = json.loads(path.read_text(encoding="utf-8"))
if action == "add":
    payload["processes"].append(
        {
            "component": component,
            "pid": int(value1),
            "command": value2,
            "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "exit_status": None,
        }
    )
elif action == "finish":
    for process in reversed(payload["processes"]):
        if process["component"] == component and process["exit_status"] is None:
            process["exit_status"] = value1
            break
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

record_process() {
  local component="$1" pid="$2" safe_command="$3"
  PROCESS_PIDS["$component"]="$pid"
  update_process_manifest add "$component" "$pid" "$safe_command"
}

record_process_exit() {
  local component="$1" status="$2"
  if [[ "${PROCESS_EXIT_RECORDED[$component]:-0}" == "0" ]]; then
    update_process_manifest finish "$component" "$status"
    PROCESS_EXIT_RECORDED["$component"]=1
  fi
}

init_process_manifest
log_stack "run_id=$RUN_ID evidence=$RUN_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log_stack_error "required command '$1' was not found on PATH"
    exit 127
  fi
}

python_cmd() {
  if [[ -n "$CONDA_ENV" ]]; then
    conda run --no-capture-output -n "$CONDA_ENV" python "$@"
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
    raise SystemExit(f"missing Python runtime dependency: {exc}")

major, minor = (int(part) for part in client_version.split(".")[:2])
if (major, minor) < (8, 14) or major >= 9:
    raise SystemExit(f"elasticsearch[async]>=8.14,<9 is required; found {client_version}")
PY
}

ensure_python_runtime() {
  if verify_python_runtime; then
    return
  fi
  log_stack "installing project Python dependencies into the selected runtime"
  if [[ -n "$CONDA_ENV" ]]; then
    run_stack_command conda run -n "$CONDA_ENV" python -m pip install --upgrade -e '.[dev]'
  else
    run_stack_command python -m pip install --upgrade -e '.[dev]'
  fi
  verify_python_runtime
}

ensure_ui_runtime() {
  if [[ ! -f "$REPO_ROOT/.deps/node-env.sh" ]]; then
    run_stack_command bash "$SCRIPT_DIR/bootstrap_node.sh"
  fi
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.deps/node-env.sh"
  require_command npm
  if [[ ! -x "$REPO_ROOT/frontend/original-ui/node_modules/.bin/turbo" ]]; then
    run_stack_command npm run ui:install
  fi
}

write_search_config() {
  local target="$1" selected_index="$2" selected_data_root="$3" mode="$4"
  python - "$REPO_ROOT/config.yaml" "$target" "$ES_ENDPOINT" "$selected_index" "$selected_data_root" "$mode" <<'PY'
from pathlib import Path
import json
import re
import sys

source, target = Path(sys.argv[1]), Path(sys.argv[2])
endpoint, index, data_root, mode = sys.argv[3:7]
validation = mode == "validation"
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
  allow_mock_fallback: {str(validation).lower()}
  force_mock_embedding: {str(validation).lower()}
"""
updated = re.sub(r"(?m)^search:\r?\n(?:^[ \t]+[^\r\n]*(?:\r?\n|$))*", search_block + "\n", raw, count=1)
enabled = "true"
updated = re.sub(
    r"(?m)^(recorded_video:\r?\n[ \t]+enabled:)[ \t]*(?:true|false)",
    rf"\1 {enabled}",
    updated,
    count=1,
)
updated = re.sub(
    r"(?m)^(recorded_video:\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+data_root:)[^\r\n]*",
    rf"\1 {json.dumps(data_root)}",
    updated,
    count=1,
)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(updated, encoding="utf-8")
PY
}

port_listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "TCP:$1" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$1" 2>/dev/null | tr ' ' '\n' || true
  else
    log_stack_error "lsof or fuser is required to reclaim API/UI ports"
    return 127
  fi
}

assert_current_user_pid() {
  local pid="$1" owner_uid current_uid
  owner_uid="$(ps -p "$pid" -o uid= 2>/dev/null | tr -d '[:space:]')"
  current_uid="$(id -u)"
  if [[ -z "$owner_uid" || "$owner_uid" != "$current_uid" ]]; then
    log_stack_error "FOREIGN_LISTENER: refusing to terminate PID $pid owned by uid ${owner_uid:-unknown}"
    return 1
  fi
}

wait_for_port_free() {
  local port="$1" deadline=$((SECONDS + TIMEOUT_SEC))
  local force_deadline=$((SECONDS + PORT_TERMINATION_GRACE_SEC)) pids pid forced=0
  while true; do
    pids="$(port_listener_pids "$port")" || return 1
    [[ -z "$pids" ]] && return 0
    if (( SECONDS >= deadline )); then
      log_stack_error "port $port was not released; remaining PID(s): $pids"
      return 1
    fi
    if (( forced == 0 && SECONDS >= force_deadline )); then
      for pid in $pids; do
        assert_current_user_pid "$pid" || return 1
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
    assert_current_user_pid "$pid" || return 1
    log_stack "reclaiming port $port from current-user PID $pid"
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  wait_for_port_free "$port"
}

redact_component_output() {
  local label="$1" path="$2"
  redact_runtime_text | tee -a "$path" | sed -u "s/^/[$label] /" | tee -a "$STACK_LOG_PATH"
}

start_es_log_stream() {
  setsid docker compose -f docker-compose.es.yml logs --since "$STACK_STARTED_AT" -f elasticsearch > >(redact_component_output es "$ES_LOG_PATH") 2>&1 &
  ES_LOG_PID=$!
  record_process es "$ES_LOG_PID" "docker compose -f docker-compose.es.yml logs --since <run-start> -f elasticsearch"
}

wait_http_health() {
  local deadline=$((SECONDS + TIMEOUT_SEC)) health_payload
  while (( SECONDS < deadline )); do
    if [[ -n "$API_PID" ]] && ! kill -0 "$API_PID" >/dev/null 2>&1; then
      log_stack_error "FastAPI process exited before health check succeeded"
      return 1
    fi
    health_payload="$(curl -fsS "$API_HEALTH_URL" 2>/dev/null || true)"
    if [[ -n "$health_payload" ]] && printf '%s' "$health_payload" | python -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "ok" else 1)'; then
      return 0
    fi
    sleep 2
  done
  log_stack_error "FastAPI did not become reachable at $API_HEALTH_URL within $TIMEOUT_SEC seconds"
  return 1
}

wait_worker_ready() {
  local deadline=$((SECONDS + TIMEOUT_SEC))
  while (( SECONDS < deadline )); do
    if [[ -n "$WORKER_PID" ]] && ! kill -0 "$WORKER_PID" >/dev/null 2>&1; then
      log_stack_error "recorded-video Worker exited before readiness"
      return 1
    fi
    if python - "$WORKER_LOG_PATH" <<'PY'
import json
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines():
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        continue
    if payload.get("event") == "worker.readiness" and payload.get("ready") is True:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 1
  done
  log_stack_error "recorded-video Worker did not emit ready=true within $TIMEOUT_SEC seconds"
  return 1
}

wait_ui_health() {
  local deadline=$((SECONDS + TIMEOUT_SEC))
  while (( SECONDS < deadline )); do
    if [[ -n "$UI_PID" ]] && ! kill -0 "$UI_PID" >/dev/null 2>&1; then
      log_stack_error "Original UI process exited before readiness"
      return 1
    fi
    if curl -fsS "$UI_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  log_stack_error "Original UI did not become reachable at $UI_URL within $TIMEOUT_SEC seconds"
  return 1
}

wait_same_origin_proxy() {
  local deadline=$((SECONDS + TIMEOUT_SEC)) status
  while (( SECONDS < deadline )); do
    status="$(curl -sS -o /dev/null -w '%{http_code}' "$UI_URL/api/v1/search" 2>/dev/null || true)"
    if [[ "$status" == "405" ]]; then
      return 0
    fi
    sleep 2
  done
  log_stack_error "same-origin API proxy did not become reachable through $UI_URL"
  return 1
}

wait_runtime_processes() {
  local component pid status
  while true; do
    for component in api worker ui; do
      pid="${PROCESS_PIDS[$component]:-}"
      [[ -z "$pid" ]] && continue
      if ! pid_is_running "$pid"; then
        status=0
        wait "$pid" >/dev/null 2>&1 || status=$?
        record_process_exit "$component" "$status"
        log_stack_error "$component exited after readiness with status $status"
        [[ "$status" == "0" ]] && return 1
        return "$status"
      fi
    done
    sleep 0.25
  done
}

pid_is_running() {
  local pid="$1" state
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  state="$(ps -p "$pid" -o stat= 2>/dev/null | tr -d '[:space:]')"
  [[ -z "$state" || "$state" != Z* ]]
}

signal_process_tree() {
  local signal="$1" pid="$2" target_pgid self_pgid
  target_pgid="$(ps -p "$pid" -o pgid= 2>/dev/null | tr -d '[:space:]')"
  self_pgid="$(ps -p "$$" -o pgid= 2>/dev/null | tr -d '[:space:]')"
  if [[ "$target_pgid" =~ ^[0-9]+$ && "$target_pgid" == "$pid" && "$target_pgid" != "$self_pgid" ]]; then
    kill -"$signal" -- "-$target_pgid" >/dev/null 2>&1 || true
  else
    kill -"$signal" "$pid" >/dev/null 2>&1 || true
  fi
}

stop_pid_bounded() {
  local pid="$1" tick status=0
  if pid_is_running "$pid"; then
    signal_process_tree TERM "$pid"
    for ((tick = 0; tick < ${PROCESS_SHUTDOWN_GRACE_TICKS:-10}; tick++)); do
      pid_is_running "$pid" || break
      sleep 0.1
    done
  fi
  if pid_is_running "$pid"; then
    signal_process_tree KILL "$pid"
  fi
  wait "$pid" >/dev/null 2>&1 || status=$?
  return "$status"
}

stop_managed_process() {
  local component="$1" pid="${PROCESS_PIDS[$1]:-}" status=0
  [[ -z "$pid" ]] && return 0
  stop_pid_bounded "$pid" || status=$?
  record_process_exit "$component" "$status"
}

delete_validation_resources() {
  [[ "$VALIDATE" != "1" ]] && return 0
  local failed=0
  if ! curl -fsS -X DELETE "$ES_ENDPOINT/$VALIDATION_SMOKE_INDEX" >/dev/null 2>&1; then
    log_stack_error "failed to remove validation index $VALIDATION_SMOKE_INDEX"
    failed=1
  fi
  rm -rf -- "$VALIDATION_DATA_ROOT" || failed=1
  rm -f -- "$VALIDATION_CONFIG_PATH" "$CONFIG_PATH" || failed=1
  if [[ "$failed" == "0" ]]; then
    log_stack "removed isolated validation namespace $VALIDATION_INDEX"
    return 0
  fi
  return 1
}

cleanup() {
  local status=$? cleanup_failed=0
  trap - EXIT INT TERM
  stop_managed_process ui
  stop_managed_process worker
  stop_managed_process api
  stop_managed_process es
  delete_validation_resources || cleanup_failed=1
  if [[ "$ES_STARTED_BY_RUN" == "1" && "$STOP_ELASTICSEARCH" == "1" ]]; then
    if run_stack_command docker compose -f docker-compose.es.yml down; then
      :
    else
      cleanup_failed=1
    fi
  fi
  if [[ "$VALIDATE" != "1" && -f "$CONFIG_PATH" ]]; then
    log_stack "Temporary config retained: $CONFIG_PATH"
  fi
  log_stack "process manifest: $PROCESS_MANIFEST_PATH"
  log_stack "stack log: $STACK_LOG_PATH"
  if [[ "$cleanup_failed" == "1" && "$status" == "0" ]]; then
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

require_command docker
require_command curl
require_command setsid
if [[ -n "$CONDA_ENV" ]]; then
  require_command conda
fi

cd "$REPO_ROOT"
ensure_python_runtime
if [[ -z "$DATA_ROOT" ]]; then
  DATA_ROOT="$REPO_ROOT/.runtime/recorded-video"
elif [[ "$DATA_ROOT" != /* ]]; then
  DATA_ROOT="$REPO_ROOT/$DATA_ROOT"
fi
mkdir -p "$DATA_ROOT"

for port in "$API_PORT" "$UI_PORT"; do reclaim_port "$port"; done

write_search_config "$CONFIG_PATH" "$INDEX" "$DATA_ROOT" production
if [[ "$VALIDATE" == "1" ]]; then
  write_search_config "$VALIDATION_CONFIG_PATH" "$VALIDATION_INDEX" "$VALIDATION_DATA_ROOT" validation
  API_CONFIG_PATH="$VALIDATION_CONFIG_PATH"
fi

export PYTHONPATH="$REPO_ROOT/src"
if [[ "$SMOKE_ONLY" == "0" ]]; then
  ensure_ui_runtime
fi

doctor_args=(scripts/runtime-doctor.py --config "$CONFIG_PATH" --es-endpoint "$ES_ENDPOINT" --phase static --port "$API_PORT" --json)
if [[ "$SMOKE_ONLY" == "1" ]]; then
  doctor_args+=(--skip-ui)
else
  doctor_args+=(--port "$UI_PORT")
fi
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
log_stack "running static runtime doctor"
run_stack_command python_cmd "${doctor_args[@]}"

export VSA_ES_PORT="$ES_PORT"
export VSA_ES_CONTAINER_NAME="vsa-agent-es"
STACK_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
if [[ "$(docker inspect -f '{{.State.Running}}' vsa-agent-es 2>/dev/null || true)" != "true" ]]; then
  ES_STARTED_BY_RUN=1
fi
if ! run_stack_command docker compose -f docker-compose.es.yml up -d; then
  log_stack_error "Docker Compose could not start Elasticsearch"
  exit 1
fi
start_es_log_stream

deadline=$((SECONDS + TIMEOUT_SEC))
until curl -fsS "$ES_ENDPOINT" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    log_stack_error "Elasticsearch did not become reachable at $ES_ENDPOINT within $TIMEOUT_SEC seconds"
    exit 1
  fi
  sleep 2
done

doctor_args=(scripts/runtime-doctor.py --config "$CONFIG_PATH" --es-endpoint "$ES_ENDPOINT" --phase elasticsearch --json)
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
log_stack "validating production alias and mapping without writes"
run_stack_command python_cmd "${doctor_args[@]}"

if [[ -n "$CONDA_ENV" ]]; then
  VSA_CONFIG="$API_CONFIG_PATH" PYTHONUNBUFFERED=1 setsid conda run --no-capture-output -n "$CONDA_ENV" python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" > >(redact_component_output api "$API_LOG_PATH") 2>&1 &
else
  VSA_CONFIG="$API_CONFIG_PATH" PYTHONUNBUFFERED=1 setsid python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT" > >(redact_component_output api "$API_LOG_PATH") 2>&1 &
fi
API_PID=$!
if [[ -n "$CONDA_ENV" ]]; then
  API_SAFE_COMMAND="conda run --no-capture-output -n $CONDA_ENV python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $API_PORT"
else
  API_SAFE_COMMAND="python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $API_PORT"
fi
record_process api "$API_PID" "$API_SAFE_COMMAND"
wait_http_health # readiness: api health

if [[ -n "$CONDA_ENV" ]]; then
  PYTHONUNBUFFERED=1 setsid conda run --no-capture-output -n "$CONDA_ENV" python scripts/recorded-video-worker.py --config "$API_CONFIG_PATH" > >(redact_component_output worker "$WORKER_LOG_PATH") 2>&1 &
else
  PYTHONUNBUFFERED=1 setsid python scripts/recorded-video-worker.py --config "$API_CONFIG_PATH" > >(redact_component_output worker "$WORKER_LOG_PATH") 2>&1 &
fi
WORKER_PID=$!
if [[ -n "$CONDA_ENV" ]]; then
  WORKER_SAFE_COMMAND="conda run --no-capture-output -n $CONDA_ENV python scripts/recorded-video-worker.py --config <runtime-config>"
else
  WORKER_SAFE_COMMAND="python scripts/recorded-video-worker.py --config <runtime-config>"
fi
record_process worker "$WORKER_PID" "$WORKER_SAFE_COMMAND"
wait_worker_ready # readiness: recorded-video Worker

if [[ "$SMOKE_ONLY" == "0" ]]; then
  NEXT_PUBLIC_ENABLE_SEARCH_TAB=true NEXT_PUBLIC_AGENT_API_URL_BASE="/api/v1" NEXT_PUBLIC_VST_API_URL="/api/v1/vst" VSA_INTERNAL_AGENT_API_URL_BASE="${API_URL}/api/v1" PORT="$UI_PORT" setsid bash "$SCRIPT_DIR/run_original_ui_vss.sh" > >(redact_component_output ui "$UI_LOG_PATH") 2>&1 &
  UI_PID=$!
  record_process ui "$UI_PID" "bash scripts/run_original_ui_vss.sh"
  wait_ui_health # readiness: original UI
  wait_same_origin_proxy # readiness: same-origin proxy
fi

if [[ "$VALIDATE" == "1" ]]; then # validation
  log_stack "running isolated validation against $VALIDATION_INDEX"
  smoke_args=(scripts/es_ingest_smoke.py --api-url "$API_URL" --es-endpoint "$ES_ENDPOINT" --index "$VALIDATION_SMOKE_INDEX" --video-id "runtime-validation-$RUN_ID" --insecure)
  run_stack_command python_cmd "${smoke_args[@]}"
  log_stack "PASS: ES runtime stack validation succeeded"
  exit 0
fi # validation

log_stack "PASS: ES recorded-video runtime stack is ready"
log_stack "api=$API_URL es=$ES_ENDPOINT ui=$UI_URL index=$INDEX data_root=$DATA_ROOT"
wait_runtime_processes
