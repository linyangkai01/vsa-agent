#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${REPO_ROOT}/config.yaml"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required but was not found on PATH" >&2
  exit 2
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing config: ${CONFIG_PATH}" >&2
  exit 2
fi

export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
export VSA_CONDA_ENV="${VSA_CONDA_ENV:-vsa-agent}"
export VSA_PROFILE="${VSA_PROFILE:-dashscope_remote}"
export VSA_LIVE_TRACE_PATH="${VSA_LIVE_TRACE_PATH:-${REPO_ROOT}/artifacts/live-traces/dashscope-live-acceptance.jsonl}"

export VSA_CONFIG="${CONFIG_PATH}"

mkdir -p "$(dirname "${VSA_LIVE_TRACE_PATH}")"

echo "Resolved unified runtime config"
conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config doctor --config "${VSA_CONFIG}"
conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config print --config "${VSA_CONFIG}"

LIVE_API_KEY="$(
  conda run -n "${VSA_CONDA_ENV}" python -c "from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml('${VSA_CONFIG}')).llm.api_key or '')"
)"
LIVE_API_BASE_URL="$(
  conda run -n "${VSA_CONDA_ENV}" python -c "from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml('${VSA_CONFIG}')).llm.base_url)"
)"
LIVE_API_MODEL="$(
  conda run -n "${VSA_CONDA_ENV}" python -c "from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml('${VSA_CONFIG}')).llm.model)"
)"
if [[ -z "${LIVE_API_KEY}" ]]; then
  echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
  exit 2
fi

export LIVE_API_KEY
export LIVE_API_BASE_URL
export LIVE_API_MODEL

echo "Running DashScope live acceptance"
echo "  config: ${VSA_CONFIG}"
echo "  profile: ${VSA_PROFILE}"
echo "  conda env: ${VSA_CONDA_ENV}"
echo "  base url: ${LIVE_API_BASE_URL}"
echo "  llm model: ${LIVE_API_MODEL}"
echo "  trace log: ${VSA_LIVE_TRACE_PATH}"

cd "${REPO_ROOT}"
conda run -n "${VSA_CONDA_ENV}" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs
