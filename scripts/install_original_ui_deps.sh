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

echo "Installing original UI dependencies in ${UI_DIR}"
echo "Registry: ${REGISTRY}"
echo "Log: ${LOG_FILE}"
echo

cd "${UI_DIR}"

if command -v timeout >/dev/null 2>&1; then
  timeout "${INSTALL_TIMEOUT_SECONDS}" npm ci \
    --registry="${REGISTRY}" \
    --prefer-offline=false \
    --audit=false \
    --fund=false \
    --progress=true \
    --loglevel=notice 2>&1 | tee "${LOG_FILE}"
else
  npm ci \
    --registry="${REGISTRY}" \
    --prefer-offline=false \
    --audit=false \
    --fund=false \
    --progress=true \
    --loglevel=notice 2>&1 | tee "${LOG_FILE}"
fi

echo
echo "Original UI dependencies are installed."
