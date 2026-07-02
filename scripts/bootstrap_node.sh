#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/frontend/original-ui"
NODE_VERSION="$(tr -d '[:space:]' < "${UI_DIR}/.nvmrc")"
NODE_VERSION="${NODE_VERSION#v}"
NODE_DIST="node-v${NODE_VERSION}-linux-x64"
NODE_ARCHIVE="${NODE_DIST}.tar.xz"
NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}"
NODE_HOME="${ROOT_DIR}/.deps/node"
DOWNLOAD_DIR="${ROOT_DIR}/.deps/downloads"

mkdir -p "${DOWNLOAD_DIR}"

if [[ -x "${NODE_HOME}/bin/node" ]]; then
  echo "Node is already installed at ${NODE_HOME}"
else
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download Node.js." >&2
    exit 1
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "tar is required to unpack Node.js." >&2
    exit 1
  fi

  echo "Downloading Node.js v${NODE_VERSION}..."
  curl -fL "${NODE_URL}" -o "${DOWNLOAD_DIR}/${NODE_ARCHIVE}"

  rm -rf "${NODE_HOME}"
  mkdir -p "${NODE_HOME}"
  tar -xJf "${DOWNLOAD_DIR}/${NODE_ARCHIVE}" -C "${NODE_HOME}" --strip-components=1
fi

cat > "${ROOT_DIR}/.deps/node-env.sh" <<EOF
export PATH="${NODE_HOME}/bin:\$PATH"
EOF

export PATH="${NODE_HOME}/bin:${PATH}"

node -v
npm -v
npx -v

echo
echo "Node is ready for this repository."
echo "Run: source .deps/node-env.sh"
