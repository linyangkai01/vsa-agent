#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${REPO_ROOT}/config_live_dashscope.yaml"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required but was not found on PATH" >&2
  exit 2
fi

if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "DASHSCOPE_API_KEY is required. Export it before running this script." >&2
  exit 2
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing config: ${CONFIG_PATH}" >&2
  exit 2
fi

export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
export DASHSCOPE_LLM_MODEL="${DASHSCOPE_LLM_MODEL:-qwen-plus}"
export DASHSCOPE_VLM_MODEL="${DASHSCOPE_VLM_MODEL:-qwen3-vl-plus}"
export VSA_CONDA_ENV="${VSA_CONDA_ENV:-vsa-agent}"

export VSA_CONFIG="${CONFIG_PATH}"
export LIVE_API_KEY="${DASHSCOPE_API_KEY}"
export LIVE_API_BASE_URL="${DASHSCOPE_BASE_URL}"
export LIVE_API_MODEL="${DASHSCOPE_LLM_MODEL}"

echo "Running DashScope live acceptance"
echo "  config: ${VSA_CONFIG}"
echo "  conda env: ${VSA_CONDA_ENV}"
echo "  base url: ${LIVE_API_BASE_URL}"
echo "  llm model: ${DASHSCOPE_LLM_MODEL}"
echo "  vlm model: ${DASHSCOPE_VLM_MODEL}"

cd "${REPO_ROOT}"
conda run -n "${VSA_CONDA_ENV}" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs
