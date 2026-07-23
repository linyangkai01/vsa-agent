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
EXPLICIT_VALIDATE=0
KEEP_RUNNING=0
SECRETS_FILE="${VSA_SECRETS_FILE:-${HOME:-}/.config/vsa-agent/secrets.env}"
SECRETS_FILE_EXPLICIT=0
PORT_TERMINATION_GRACE_SEC=5
PROCESS_SHUTDOWN_GRACE_TICKS=50

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
  --keep-running             Keep an explicit isolated validation runtime alive.
  --smoke-only               Compatibility alias for --validate without starting the UI.
  --conda-env NAME           Run Python through conda run -n NAME.
  --secrets-file PATH        Private KEY=VALUE file. Default: ~/.config/vsa-agent/secrets.env
  --timeout-sec SECONDS      Startup timeout. Default: 90
  --stop-elasticsearch       Stop Elasticsearch on exit only when this run started it.
  -ApiPort PORT              PowerShell-style alias for --api-port.
  -EsPort PORT               PowerShell-style alias for --es-port.
  -UiPort PORT               PowerShell-style alias for --ui-port.
  -Index NAME                PowerShell-style alias for --index.
  -DataRoot PATH             PowerShell-style alias for --data-root.
  -Validate                  PowerShell-style alias for --validate.
  -KeepRunning               PowerShell-style alias for --keep-running.
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
    --validate|-Validate) VALIDATE=1; EXPLICIT_VALIDATE=1; shift ;;
    --keep-running|-KeepRunning) KEEP_RUNNING=1; shift ;;
    --smoke-only|-SmokeOnly) SMOKE_ONLY=1; VALIDATE=1; shift ;;
    --conda-env|-CondaEnv) CONDA_ENV="$2"; shift 2 ;;
    --secrets-file|-SecretsFile) SECRETS_FILE="$2"; SECRETS_FILE_EXPLICIT=1; shift 2 ;;
    --timeout-sec|-TimeoutSec) TIMEOUT_SEC="$2"; shift 2 ;;
    --stop-elasticsearch|-StopElasticsearch) STOP_ELASTICSEARCH=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$KEEP_RUNNING" == "1" && "$SMOKE_ONLY" == "1" ]]; then
  echo "ERROR: --keep-running cannot be combined with --smoke-only" >&2
  exit 2
fi
if [[ "$KEEP_RUNNING" == "1" && "$EXPLICIT_VALIDATE" != "1" ]]; then
  echo "ERROR: --keep-running requires explicit validation via --validate" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_LOG_SUPERVISOR="$SCRIPT_DIR/runtime-log-supervisor.py"
SUPERVISOR_PYTHON="${VSA_SUPERVISOR_PYTHON:-python}"
RUNTIME_DIR="$REPO_ROOT/.runtime/es-stack"
RUNS_DIR="$RUNTIME_DIR/runs"

if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: required command 'python' was not found on PATH" >&2
  exit 127
fi
RUN_ID="$(python -c 'import uuid; print(uuid.uuid4())')"
LAUNCHER_PID="$BASHPID"
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
SYNC_SUPERVISOR_PID=""
STARTED_SUPERVISOR_PID=""
API_PID=""
WORKER_PID=""
UI_PID=""
INTERRUPTED_SIGNAL=""
INTERRUPT_PENDING=0
CLEANUP_ACTIVE=0
SUPERVISOR_START_CRITICAL=0
MANAGED_EXIT_COMPONENT=""
MANAGED_EXIT_STATUS=0
STOPPED_PROCESS_STATUS=0
declare -A PROCESS_PIDS=()
declare -A PROCESS_EXIT_RECORDED=()
declare -A PROCESS_STATUS_FILES=()
declare -A PROCESS_PENDING_EXIT_STATUS=()

mkdir -p "$RUN_DIR"
for path in "$STACK_LOG_PATH" "$API_LOG_PATH" "$WORKER_LOG_PATH" "$UI_LOG_PATH" "$ES_LOG_PATH"; do
  : >"$path"
done
if [[ -L "$LATEST_LINK" || -f "$LATEST_LINK" ]]; then
  rm -f -- "$LATEST_LINK"
elif [[ -e "$LATEST_LINK" ]]; then
  printf '[stack] ERROR: LATEST_POINTER_CONFLICT: refusing to replace directory %s\n' "$LATEST_LINK" >>"$STACK_LOG_PATH"
  printf '[stack] ERROR: LATEST_POINTER_CONFLICT: refusing to replace directory %s\n' "$LATEST_LINK" >&2
  exit 1
fi
ln -sfn "$RUN_DIR" "$LATEST_LINK"

LAUNCHER_PID_PATH="$RUN_DIR/launcher.pid"
if ! printf '%s\n' "$LAUNCHER_PID" >"$LAUNCHER_PID_PATH"; then
  printf '[stack] ERROR: unable to record launcher PID at %s\n' "$LAUNCHER_PID_PATH" >&2
  exit 1
fi

handle_interrupt() {
  trap '' INT TERM
  INTERRUPTED_SIGNAL="$1"
  INTERRUPT_PENDING=1
  if [[ "$CLEANUP_ACTIVE" == "1" || "$SUPERVISOR_START_CRITICAL" == "1" ]]; then
    return 0
  fi
  exit 130
}

begin_supervisor_start() {
  SUPERVISOR_START_CRITICAL=1
}

finish_supervisor_start() {
  SUPERVISOR_START_CRITICAL=0
  if [[ "$INTERRUPT_PENDING" == "1" && "$CLEANUP_ACTIVE" != "1" ]]; then
    exit 130
  fi
}

register_sync_supervisor() {
  SYNC_SUPERVISOR_PID="$1"
}

register_component_supervisor() {
  local component="$1" pid="$2" safe_command="$3"
  STARTED_SUPERVISOR_PID="$pid"
  record_process "$component" "$pid" "$safe_command"
}

start_sync_supervisor() {
  begin_supervisor_start
  "$SUPERVISOR_PYTHON" -u "$RUNTIME_LOG_SUPERVISOR" --label stack --stack-log "$STACK_LOG_PATH" -- "$@" &
  local command_pid=$!
  register_sync_supervisor "$command_pid"
  finish_supervisor_start
}

wait_sync_supervisor() {
  local monitor_runtime="$1" command_pid="$SYNC_SUPERVISOR_PID" status=0 failure_status
  set +e
  while pid_is_running "$command_pid"; do
    if [[ "$monitor_runtime" == "1" ]]; then
      if observe_managed_processes; then
        :
      else
        failure_status=$?
        if ! stop_sync_supervisor; then
          set -e
          return 1
        fi
        set -e
        log_stack_error "$MANAGED_EXIT_COMPONENT exited with status $MANAGED_EXIT_STATUS"
        return "$failure_status"
      fi
    fi
    sleep 0.05
  done
  wait "$command_pid" || status=$?
  if [[ "$SYNC_SUPERVISOR_PID" == "$command_pid" ]]; then
    SYNC_SUPERVISOR_PID=""
  fi
  set -e
  return "$status"
}

log_stack() {
  start_sync_supervisor printf '%s\n' "$*"
  wait_sync_supervisor 1
}

publish_status() {
  local component pid status_file
  local -a status_guards=()
  for component in es api worker ui; do
    pid="${PROCESS_PIDS[$component]:-}"
    [[ -z "$pid" ]] && continue
    status_file="${PROCESS_STATUS_FILES[$component]:-$RUN_DIR/$component.status.json}"
    status_guards+=(--require-running-status "$component" "$pid" "$status_file")
  done
  begin_supervisor_start
  "$SUPERVISOR_PYTHON" -u "$RUNTIME_LOG_SUPERVISOR" \
    --label stack \
    --stack-log "$STACK_LOG_PATH" \
    "${status_guards[@]}" \
    -- printf '%s\n' "$*" &
  local command_pid=$!
  register_sync_supervisor "$command_pid"
  finish_supervisor_start
  wait_sync_supervisor 1
}

log_stack_error() {
  start_sync_supervisor printf 'ERROR: %s\n' "$*" >&2
  wait_sync_supervisor 0
}

load_secrets_file() {
  local path="$1" line key value mode owner current_owner loaded=0
  if [[ ! -e "$path" ]]; then
    if [[ "$SECRETS_FILE_EXPLICIT" == "1" ]]; then
      log_stack_error "secrets file does not exist: $path"
      return 1
    fi
    return 0
  fi
  if [[ ! -f "$path" || ! -r "$path" ]]; then
    log_stack_error "secrets file must be a readable regular file: $path"
    return 1
  fi
  if [[ "$(uname -s)" == "Linux" ]]; then
    mode="$(stat -c '%a' -- "$path")"
    owner="$(stat -c '%u' -- "$path")"
    current_owner="$(id -u)"
    if [[ "$owner" != "$current_owner" ]]; then
      log_stack_error "refusing secrets file not owned by the current user: $path"
      return 1
    fi
    if (( (8#$mode & 077) != 0 )); then
      log_stack_error "refusing secrets file with group or other permissions: $path"
      return 1
    fi
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ ! "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Z][A-Z0-9_]*_API_[K][E][Y])=(.*)$ ]]; then
      log_stack_error "secrets file contains an invalid entry; only uppercase provider-key entries are allowed: $path"
      return 1
    fi
    key="${BASH_REMATCH[2]}"
    value="${BASH_REMATCH[3]}"
    if [[ ${#value} -ge 2 && ( ( "$value" == \"*\" ) || ( "$value" == \'*\' ) ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    if [[ -z "$value" ]]; then
      log_stack_error "secrets file contains an empty value for $key"
      return 1
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
    loaded=$((loaded + 1))
  done <"$path"
  log_stack "loaded private secrets file path=$path keys=$loaded"
}

cleanup_log_line() {
  printf '[stack] %s\n' "$*" >>"$STACK_LOG_PATH"
  printf '[stack] %s\n' "$*"
}

cleanup_log_error() {
  printf '[stack] ERROR: %s\n' "$*" >>"$STACK_LOG_PATH"
  printf '[stack] ERROR: %s\n' "$*" >&2
}

run_stack_command() {
  start_sync_supervisor "$@"
  wait_sync_supervisor 1
}

run_conda_stack_command() {
  run_stack_command bash -c 'conda "$@"' vsa-conda "$@"
}

run_python_stack_command() {
  if [[ -n "$CONDA_ENV" ]]; then
    run_conda_stack_command run --no-capture-output -n "$CONDA_ENV" python "$@"
  else
    run_stack_command python "$@"
  fi
}

start_supervised_process() {
  local component="$1" component_log="$2" safe_command="$3" status_file
  shift 3
  status_file="$RUN_DIR/$component.status.json"
  PROCESS_STATUS_FILES["$component"]="$status_file"
  begin_supervisor_start
  bash -c 'VSA_SUPERVISOR_REGISTERED_PID="$BASHPID" exec "$@"' vsa-supervisor \
    "$SUPERVISOR_PYTHON" -u "$RUNTIME_LOG_SUPERVISOR" \
    --label "$component" \
    --stack-log "$STACK_LOG_PATH" \
    --component-log "$component_log" \
    --status-file "$status_file" \
    --component "$component" \
    -- "$@" &
  local supervisor_pid=$!
  register_component_supervisor "$component" "$supervisor_pid" "$safe_command"
  finish_supervisor_start
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
    if ! update_process_manifest finish "$component" "$status"; then
      return 1
    fi
    PROCESS_EXIT_RECORDED["$component"]=1
  fi
}

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
    run_conda_stack_command run -n "$CONDA_ENV" python -m pip install --upgrade -e '.[dev]'
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
import yaml

source, target = Path(sys.argv[1]), Path(sys.argv[2])
endpoint, index, data_root, mode = sys.argv[3:7]
validation = mode == "validation"
raw = source.read_text(encoding="utf-8")
source_config = yaml.safe_load(raw) or {}
embedding_dimensions = int((source_config.get("search") or {}).get("embedding_dimensions", 1024))
search_block = f"""search:
  enabled: true
  es_endpoint: {endpoint}
  embed_index: {index}
  embedding_dimensions: {embedding_dimensions}
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: false
  force_mock_embedding: false
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

stale_project_ui_pids() {
  local current_uid protected_pids=" " pid="$LAUNCHER_PID" parent depth=0
  [[ "$(uname -s)" == "Linux" ]] || return 0
  current_uid="$(id -u)"

  while [[ "$pid" =~ ^[0-9]+$ ]] && (( pid > 1 && depth < 64 )); do
    [[ "$protected_pids" == *" $pid "* ]] && break
    protected_pids+="$pid "
    parent="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d '[:space:]')"
    pid="$parent"
    depth=$((depth + 1))
  done

  ps -eo uid=,pid=,comm=,args= | awk -v uid="$current_uid" -v root="$REPO_ROOT" -v protected="$protected_pids" '
    $1 == uid && $3 ~ /^(node|npm|turbo|bash|sh)$/ {
      command_line = $0
      if (index(protected, " " $2 " ") == 0 &&
          (index(command_line, root "/frontend/original-ui") > 0 ||
           index(command_line, root "/scripts/run_original_ui_vss.sh") > 0)) {
        print $2
      }
    }
  '
}

reclaim_stale_project_ui_processes() {
  local pids pid deadline
  pids="$(stale_project_ui_pids)"
  [[ -z "$pids" ]] && return 0
  for pid in $pids; do
    assert_current_user_pid "$pid" allow-missing || return 1
    log_stack "reclaiming stale project UI process PID $pid"
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  deadline=$((SECONDS + PORT_TERMINATION_GRACE_SEC))
  while [[ -n "$(stale_project_ui_pids)" ]] && (( SECONDS < deadline )); do
    sleep 0.25
  done
  pids="$(stale_project_ui_pids)"
  for pid in $pids; do
    assert_current_user_pid "$pid" allow-missing || return 1
    kill -KILL "$pid" >/dev/null 2>&1 || true
  done
  deadline=$((SECONDS + PORT_TERMINATION_GRACE_SEC))
  while [[ -n "$(stale_project_ui_pids)" ]] && (( SECONDS < deadline )); do
    sleep 0.25
  done
  pids="$(stale_project_ui_pids)"
  if [[ -n "$pids" ]]; then
    log_stack_error "stale project UI process cleanup did not complete; remaining PID(s): $pids"
    return 1
  fi
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
  local pid="$1" missing_policy="${2:-reject-missing}" owner_uid current_uid
  owner_uid="$(ps -p "$pid" -o uid= 2>/dev/null | tr -d '[:space:]')"
  current_uid="$(id -u)"
  if [[ -z "$owner_uid" ]]; then
    # The listener may exit between discovery and ownership validation.
    # Only the stale-UI path has already established current-user ownership.
    if [[ "$missing_policy" == "allow-missing" ]] && ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    log_stack_error "FOREIGN_LISTENER: refusing to terminate PID $pid owned by uid unknown"
    return 1
  fi
  if [[ "$owner_uid" != "$current_uid" ]]; then
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

start_es_log_stream() {
  start_supervised_process \
    es \
    "$ES_LOG_PATH" \
    "docker compose -f docker-compose.es.yml logs --since <run-start> -f elasticsearch" \
    docker compose -f docker-compose.es.yml logs --since "$STACK_STARTED_AT" -f elasticsearch
  ES_LOG_PID="$STARTED_SUPERVISOR_PID"
}

observe_managed_processes() {
  local component pid status finalization_status pending_status
  MANAGED_EXIT_COMPONENT=""
  MANAGED_EXIT_STATUS=0
  for component in es api worker ui; do
    pid="${PROCESS_PIDS[$component]:-}"
    [[ -z "$pid" ]] && continue
    pending_status="${PROCESS_PENDING_EXIT_STATUS[$component]:-}"
    if [[ -n "$pending_status" ]]; then
      status="$pending_status"
    elif ! pid_is_running "$pid"; then
      status=0
      wait "$pid" >/dev/null 2>&1 || status=$?
      PROCESS_PENDING_EXIT_STATUS["$component"]="$status"
    else
      continue
    fi
    MANAGED_EXIT_COMPONENT="$component"
    MANAGED_EXIT_STATUS="$status"
    if record_process_exit "$component" "$status"; then
      PROCESS_PENDING_EXIT_STATUS["$component"]=""
      PROCESS_PIDS["$component"]=""
      [[ "$status" == "0" ]] && return 1
      return "$status"
    else
      finalization_status=$?
      return "$finalization_status"
    fi
  done
  return 0
}

validate_component_status() {
  local component="$1" status_file="$2" expected_supervisor_pid="$3"
  python - "$status_file" "$RUN_ID" "$component" "$expected_supervisor_pid" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
run_id, component, expected_supervisor_pid = sys.argv[2], sys.argv[3], int(sys.argv[4])
payload = None

def fail(reason, status=1):
    state = payload.get("state") if isinstance(payload, dict) else "unknown"
    exit_code = payload.get("exit_code") if isinstance(payload, dict) else None
    print(
        f"component={component} status_file={path.as_posix()} state={state} "
        f"exit_code={json.dumps(exit_code)} error={reason}",
        file=sys.stderr,
    )
    raise SystemExit(status)

try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    fail(f"unreadable status sidecar: {error}")
if not isinstance(payload, dict):
    fail("status sidecar root must be an object")
if payload.get("schema_version") != 1:
    fail("schema_version mismatch")
if payload.get("run_id") != run_id:
    fail("run_id mismatch")
if payload.get("component") != component:
    fail("component mismatch")
if payload.get("supervisor_pid") != expected_supervisor_pid:
    fail("supervisor PID mismatch")
if not isinstance(payload.get("updated_at"), str) or not payload["updated_at"]:
    fail("updated_at is missing")
state = payload.get("state")
workload_pid = payload.get("workload_pid")
if state == "exited":
    if not isinstance(workload_pid, int) or isinstance(workload_pid, bool) or workload_pid <= 0:
        fail("invalid workload PID")
    exit_code = payload.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or not 0 <= exit_code <= 255:
        fail("invalid exited component exit code")
    fail("component exited", exit_code or 1)
if state != "running":
    fail("component is not running")
if not isinstance(workload_pid, int) or isinstance(workload_pid, bool) or workload_pid <= 0:
    fail("invalid workload PID")
if payload.get("exit_code") is not None:
    fail("running component has an exit code")
PY
}

validate_managed_statuses() {
  local component pid status_file error status
  for component in es api worker ui; do
    pid="${PROCESS_PIDS[$component]:-}"
    [[ -z "$pid" ]] && continue
    status_file="${PROCESS_STATUS_FILES[$component]:-$RUN_DIR/$component.status.json}"
    if error="$(validate_component_status "$component" "$status_file" "$pid" 2>&1)"; then
      :
    else
      status=$?
      log_stack_error "$error"
      return "$status"
    fi
  done
  return 0
}

wait_component_status_running() {
  local component="$1" pid="${PROCESS_PIDS[$1]:-}" status_file deadline error status process_status
  status_file="${PROCESS_STATUS_FILES[$component]:-$RUN_DIR/$component.status.json}"
  deadline=$((SECONDS + TIMEOUT_SEC))
  while (( SECONDS < deadline )); do
    if error="$(validate_component_status "$component" "$status_file" "$pid" 2>&1)"; then
      return 0
    else
      status=$?
    fi
    if [[ "$error" == *" state=exited "* ]]; then
      log_stack_error "$error"
      return "$status"
    fi
    if fail_if_managed_process_exited; then
      :
    else
      process_status=$?
      if error="$(validate_component_status "$component" "$status_file" "$pid" 2>&1)"; then
        return 0
      else
        status=$?
      fi
      if [[ "$error" == *" state=exited "* ]]; then
        log_stack_error "$error"
        return "$status"
      fi
      return "$process_status"
    fi
    sleep 0.05
  done
  error="$(validate_component_status "$component" "$status_file" "$pid" 2>&1 || true)"
  log_stack_error "$error"
  return 1
}

fail_if_managed_process_exited() {
  local status
  if observe_managed_processes; then
    return 0
  else
    status=$?
  fi
  log_stack_error "$MANAGED_EXIT_COMPONENT exited with status $MANAGED_EXIT_STATUS"
  return "$status"
}

wait_http_health() {
  local deadline=$((SECONDS + TIMEOUT_SEC)) health_payload
  while (( SECONDS < deadline )); do
    fail_if_managed_process_exited || return $?
    validate_managed_statuses || return $?
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
    fail_if_managed_process_exited || return $?
    validate_managed_statuses || return $?
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
    fail_if_managed_process_exited || return $?
    validate_managed_statuses || return $?
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
    fail_if_managed_process_exited || return $?
    validate_managed_statuses || return $?
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
  while true; do
    fail_if_managed_process_exited || return $?
    validate_managed_statuses || return $?
    sleep 0.25
  done
}

pid_is_running() {
  local pid="$1" state
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  if [[ -n "${MSYSTEM:-}" || "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]; then
    return 0
  fi
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
  local pid="$1" tick=0
  local grace_ticks="${PROCESS_SHUTDOWN_GRACE_TICKS:-50}"
  local deadline=$((grace_ticks * 2))
  STOPPED_PROCESS_STATUS=0
  if pid_is_running "$pid"; then
    signal_process_tree TERM "$pid"
    for ((; tick < grace_ticks; tick++)); do
      pid_is_running "$pid" || break
      sleep 0.1
    done
  fi
  if pid_is_running "$pid"; then
    signal_process_tree KILL "$pid"
    for ((; tick < deadline; tick++)); do
      pid_is_running "$pid" || break
      sleep 0.1
    done
  fi
  pid_is_running "$pid" && return 1
  wait "$pid" >/dev/null 2>&1 || STOPPED_PROCESS_STATUS=$?
  return 0
}

request_managed_process_stop() {
  local component="$1" pid="${PROCESS_PIDS[$1]:-}"
  [[ -z "$pid" ]] && return 0
  [[ -n "${PROCESS_PENDING_EXIT_STATUS[$component]:-}" ]] && return 0
  kill -TERM "$pid" >/dev/null 2>&1 || true
}

stop_managed_process() {
  local component="$1" pid="${PROCESS_PIDS[$1]:-}" pending_status
  [[ -z "$pid" ]] && return 0
  pending_status="${PROCESS_PENDING_EXIT_STATUS[$component]:-}"
  if [[ -n "$pending_status" ]]; then
    record_process_exit "$component" "$pending_status" || return $?
    PROCESS_PENDING_EXIT_STATUS["$component"]=""
    PROCESS_PIDS["$component"]=""
    return 0
  fi
  stop_pid_bounded "$pid" || return 1
  record_process_exit "$component" "$STOPPED_PROCESS_STATUS" || return $?
  PROCESS_PIDS["$component"]=""
  return 0
}

stop_sync_supervisor() {
  [[ -z "$SYNC_SUPERVISOR_PID" ]] && return 0
  stop_pid_bounded "$SYNC_SUPERVISOR_PID" || return 1
  SYNC_SUPERVISOR_PID=""
}

delete_validation_resources() {
  [[ "$VALIDATE" != "1" ]] && return 0
  local failed=0 validation_resource validation_indices=""
  if curl -fsS "$ES_ENDPOINT/_alias/$VALIDATION_INDEX" >/dev/null 2>&1; then
    validation_indices="$(
      curl -fsS "$ES_ENDPOINT/_alias/$VALIDATION_INDEX" |
        python -c 'import json, sys; print("\n".join(json.load(sys.stdin)))'
    )" || failed=1
  fi
  validation_indices="$({
    printf '%s\n' "$validation_indices"
    curl -fsS "$ES_ENDPOINT/_cat/indices/${VALIDATION_INDEX}-*?h=index" 2>/dev/null || true
  } | awk 'NF && !seen[$0]++')"
  for validation_resource in "$VALIDATION_SMOKE_INDEX" $validation_indices; do
    if ! curl -fsS -X DELETE --get --data-urlencode "ignore_unavailable=true" "$ES_ENDPOINT/$validation_resource" >/dev/null 2>&1; then
      cleanup_log_error "failed to remove validation index $validation_resource"
      failed=1
    fi
  done
  rm -rf -- "$VALIDATION_DATA_ROOT" || failed=1
  rm -f -- "$VALIDATION_CONFIG_PATH" "$CONFIG_PATH" || failed=1
  if [[ "$failed" == "0" ]]; then
    cleanup_log_line "removed isolated validation namespace $VALIDATION_INDEX"
    return 0
  fi
  return 1
}

cleanup() {
  local status="${1:-$?}" cleanup_failed=0
  trap - EXIT
  trap '' INT TERM
  CLEANUP_ACTIVE=1
  set +e
  if [[ -n "$SYNC_SUPERVISOR_PID" ]]; then
    if ! run_cleanup_stage "stop sync supervisor" stop_sync_supervisor; then cleanup_failed=1; fi
  fi
  request_managed_process_stop ui
  request_managed_process_stop worker
  request_managed_process_stop api
  request_managed_process_stop es
  if ! run_cleanup_stage "stop ui" stop_managed_process ui; then cleanup_failed=1; fi
  if ! run_cleanup_stage "stop worker" stop_managed_process worker; then cleanup_failed=1; fi
  if ! run_cleanup_stage "stop api" stop_managed_process api; then cleanup_failed=1; fi
  if ! run_cleanup_stage "stop es" stop_managed_process es; then cleanup_failed=1; fi
  if ! run_cleanup_stage "delete validation resources" delete_validation_resources; then cleanup_failed=1; fi
  if [[ "$ES_STARTED_BY_RUN" == "1" && "$STOP_ELASTICSEARCH" == "1" ]]; then
    if ! run_cleanup_stage "stop Elasticsearch compose" run_stack_command docker compose -f docker-compose.es.yml down; then
      cleanup_failed=1
    fi
  fi
  if [[ "$VALIDATE" != "1" && -f "$CONFIG_PATH" ]]; then
    if ! run_cleanup_stage "log temporary config notice" cleanup_log_line "Temporary config retained: $CONFIG_PATH"; then
      cleanup_failed=1
    fi
  fi
  if ! run_cleanup_stage "log process manifest path" cleanup_log_line "process manifest: $PROCESS_MANIFEST_PATH"; then
    cleanup_failed=1
  fi
  if ! run_cleanup_stage "log stack log path" cleanup_log_line "stack log: $STACK_LOG_PATH"; then cleanup_failed=1; fi
  if [[ "$cleanup_failed" == "1" && "$status" == "0" ]]; then
    status=1
  fi
  if [[ "$INTERRUPT_PENDING" == "1" ]]; then
    status=130
  fi
  if [[ -n "$INTERRUPTED_SIGNAL" ]]; then
    if ! run_cleanup_stage "log interruption status" cleanup_log_line \
      "interruption signal=$INTERRUPTED_SIGNAL final_status=$status"; then
      [[ "$status" == "0" ]] && status=1
    fi
  fi
  exit "$status"
}

run_cleanup_stage() {
  local label="$1"
  shift
  if "$@"; then
    return 0
  fi
  printf '[stack] ERROR: cleanup stage failed: %s\n' "$label" >>"$STACK_LOG_PATH"
  printf '[stack] ERROR: cleanup stage failed: %s\n' "$label" >&2
  return 1
}

trap 'status=$?; trap "" INT TERM; cleanup "$status"' EXIT
trap 'handle_interrupt INT' INT
trap 'handle_interrupt TERM' TERM

init_process_manifest
log_stack "run_id=$RUN_ID evidence=$RUN_DIR"
log_stack "launcher_pid=$LAUNCHER_PID"
load_secrets_file "$SECRETS_FILE"

require_command docker
require_command curl
require_command python
if [[ -n "$CONDA_ENV" ]]; then
  require_command conda
  require_command bash
fi

cd "$REPO_ROOT"
ensure_python_runtime
if [[ -z "$DATA_ROOT" ]]; then
  DATA_ROOT="$REPO_ROOT/.runtime/recorded-video"
elif [[ "$DATA_ROOT" != /* ]]; then
  DATA_ROOT="$REPO_ROOT/$DATA_ROOT"
fi
mkdir -p "$DATA_ROOT"

reclaim_stale_project_ui_processes
for port in "$API_PORT" "$UI_PORT"; do reclaim_port "$port"; done

write_search_config "$CONFIG_PATH" "$INDEX" "$DATA_ROOT" production
if [[ "$VALIDATE" == "1" ]]; then
  write_search_config "$VALIDATION_CONFIG_PATH" "$VALIDATION_INDEX" "$VALIDATION_DATA_ROOT" validation
  API_CONFIG_PATH="$VALIDATION_CONFIG_PATH"
fi
export VSA_CONFIG="$API_CONFIG_PATH"

export PYTHONPATH="$REPO_ROOT/src"
if [[ "$SMOKE_ONLY" == "0" ]]; then
  ensure_ui_runtime
fi

doctor_args=(scripts/runtime-doctor.py --config "$API_CONFIG_PATH" --es-endpoint "$ES_ENDPOINT" --phase static --port "$API_PORT" --json)
if [[ "$SMOKE_ONLY" == "1" ]]; then
  doctor_args+=(--skip-ui)
else
  doctor_args+=(--port "$UI_PORT")
fi
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
log_stack "running static runtime doctor"
run_python_stack_command "${doctor_args[@]}"

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
wait_component_status_running es

deadline=$((SECONDS + TIMEOUT_SEC))
while true; do
  fail_if_managed_process_exited
  validate_managed_statuses
  if curl -fsS "$ES_ENDPOINT" >/dev/null 2>&1; then
    break
  fi
  if (( SECONDS >= deadline )); then
    log_stack_error "Elasticsearch did not become reachable at $ES_ENDPOINT within $TIMEOUT_SEC seconds"
    exit 1
  fi
  sleep 2
done

doctor_args=(scripts/runtime-doctor.py --config "$API_CONFIG_PATH" --es-endpoint "$ES_ENDPOINT" --phase elasticsearch --json)
if [[ -n "$CONDA_ENV" ]]; then
  doctor_args+=(--conda-env "$CONDA_ENV")
fi
if [[ "$VALIDATE" == "1" ]]; then
  log_stack "bootstrapping isolated validation alias before service startup"
else
  log_stack "bootstrapping or validating production alias before service startup"
fi
run_python_stack_command scripts/recorded-video-bootstrap-index.py --config "$API_CONFIG_PATH" --json
log_stack "validating active alias and mapping without writes"
run_python_stack_command "${doctor_args[@]}"

if [[ -n "$CONDA_ENV" ]]; then
  start_supervised_process api "$API_LOG_PATH" "conda run --no-capture-output -n $CONDA_ENV python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $API_PORT" \
    env VSA_CONFIG="$API_CONFIG_PATH" VSA_ORIGINAL_UI_TRACE_ROOT="$RUN_DIR/chat-traces" PYTHONUNBUFFERED=1 bash -c 'conda "$@"' vsa-conda run --no-capture-output -n "$CONDA_ENV" python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT"
else
  start_supervised_process api "$API_LOG_PATH" "python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $API_PORT" \
    env VSA_CONFIG="$API_CONFIG_PATH" VSA_ORIGINAL_UI_TRACE_ROOT="$RUN_DIR/chat-traces" PYTHONUNBUFFERED=1 python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port "$API_PORT"
fi
API_PID="$STARTED_SUPERVISOR_PID"
wait_component_status_running api
wait_http_health # readiness: api health

if [[ -n "$CONDA_ENV" ]]; then
  start_supervised_process worker "$WORKER_LOG_PATH" "conda run --no-capture-output -n $CONDA_ENV python scripts/recorded-video-worker.py --config <runtime-config>" \
    env PYTHONUNBUFFERED=1 bash -c 'conda "$@"' vsa-conda run --no-capture-output -n "$CONDA_ENV" python scripts/recorded-video-worker.py --config "$API_CONFIG_PATH"
else
  start_supervised_process worker "$WORKER_LOG_PATH" "python scripts/recorded-video-worker.py --config <runtime-config>" \
    env PYTHONUNBUFFERED=1 python scripts/recorded-video-worker.py --config "$API_CONFIG_PATH"
fi
WORKER_PID="$STARTED_SUPERVISOR_PID"
wait_component_status_running worker
wait_worker_ready # readiness: recorded-video Worker

if [[ "$SMOKE_ONLY" == "0" ]]; then
  start_supervised_process ui "$UI_LOG_PATH" "bash scripts/run_original_ui_vss.sh" \
    env NEXT_PUBLIC_ENABLE_SEARCH_TAB=true NEXT_PUBLIC_AGENT_API_URL_BASE="/api/v1" NEXT_PUBLIC_VST_API_URL="/api/v1/vst" VSA_INTERNAL_AGENT_API_URL_BASE="${API_URL}/api/v1" PORT="$UI_PORT" bash "$SCRIPT_DIR/run_original_ui_vss.sh"
  UI_PID="$STARTED_SUPERVISOR_PID"
  wait_component_status_running ui
  wait_ui_health # readiness: original UI
  wait_same_origin_proxy # readiness: same-origin proxy
fi

if [[ "$VALIDATE" == "1" ]]; then # validation
  if [[ "$KEEP_RUNNING" == "1" ]]; then
    validate_managed_statuses
    publish_status "READY: isolated validation runtime api=$API_URL ui=$UI_URL es=$ES_ENDPOINT index=$VALIDATION_INDEX"
    wait_runtime_processes
  else
    log_stack "running isolated validation against $VALIDATION_INDEX"
    smoke_args=(scripts/es_ingest_smoke.py --api-url "$API_URL" --es-endpoint "$ES_ENDPOINT" --index "$VALIDATION_SMOKE_INDEX" --video-id "runtime-validation-$RUN_ID" --insecure)
    run_python_stack_command "${smoke_args[@]}"
    validate_managed_statuses
    publish_status "PASS: ES runtime stack validation succeeded"
    exit 0
  fi
fi # validation

validate_managed_statuses
publish_status "PASS: ES recorded-video runtime stack is ready"
log_stack "api=$API_URL es=$ES_ENDPOINT ui=$UI_URL index=$INDEX data_root=$DATA_ROOT"
wait_runtime_processes
