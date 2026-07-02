#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/frontend/original-ui"
LOG_DIR="${ROOT_DIR}/artifacts"
LOG_FILE="${LOG_DIR}/original-ui-npm-install.log"

if [[ -f "${ROOT_DIR}/.deps/node-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.deps/node-env.sh"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required. Run: bash scripts/bootstrap_node.sh" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
INSTALL_TIMEOUT_SECONDS="${NPM_INSTALL_TIMEOUT_SECONDS:-900}"
IGNORE_SCRIPTS="${NPM_INSTALL_IGNORE_SCRIPTS:-true}"
HEARTBEAT_SECONDS="${NPM_INSTALL_HEARTBEAT_SECONDS:-15}"

echo "Installing original UI dependencies in ${UI_DIR}"
echo "Registry: ${REGISTRY}"
echo "Ignore install scripts: ${IGNORE_SCRIPTS}"
echo "Log: ${LOG_FILE}"
echo

cd "${UI_DIR}"

NPM_ARGS=(
  ci
  "--registry=${REGISTRY}"
  "--prefer-offline=false"
  "--audit=false"
  "--fund=false"
  "--progress=false"
  "--loglevel=http"
  "--fetch-retries=2"
  "--fetch-retry-maxtimeout=30000"
  "--fetch-timeout=60000"
  "--maxsockets=3"
)

if [[ "${IGNORE_SCRIPTS}" == "true" ]]; then
  NPM_ARGS+=("--ignore-scripts=true")
else
  NPM_ARGS+=("--foreground-scripts=true")
fi

run_npm_install() {
  npm "${NPM_ARGS[@]}" > "${LOG_FILE}" 2>&1 &
  local npm_pid=$!
  local elapsed=0

  while kill -0 "${npm_pid}" >/dev/null 2>&1; do
    sleep "${HEARTBEAT_SECONDS}"
    elapsed=$((elapsed + HEARTBEAT_SECONDS))
    echo "[${elapsed}s] npm install still running. Last log lines:"
    tail -n 8 "${LOG_FILE}" || true
    echo

    if (( elapsed >= INSTALL_TIMEOUT_SECONDS )); then
      echo "npm install timed out after ${INSTALL_TIMEOUT_SECONDS}s. See ${LOG_FILE}" >&2
      kill "${npm_pid}" >/dev/null 2>&1 || true
      wait "${npm_pid}" >/dev/null 2>&1 || true
      return 124
    fi
  done

  wait "${npm_pid}"
}

run_npm_install

echo
echo "Original UI dependencies are installed."
