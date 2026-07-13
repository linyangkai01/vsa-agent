#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/dashscope_runtime.sh"

export VSA_LIVE_TRACE_PATH="${VSA_LIVE_TRACE_PATH:-${VSA_REPO_ROOT}/artifacts/live-traces/dashscope-live-acceptance.jsonl}"

vsa_dashscope_preflight

mkdir -p "$(dirname "${VSA_LIVE_TRACE_PATH}")"

LIVE_API_KEY="${VSA_RESOLVED_LLM_API_KEY}"
LIVE_API_BASE_URL="${VSA_RESOLVED_LLM_BASE_URL}"
LIVE_API_MODEL="${VSA_RESOLVED_LLM_MODEL}"
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

cd "${VSA_REPO_ROOT}"
conda run -n "${VSA_CONDA_ENV}" python -m pytest tests/acceptance/test_evaluator_live_api.py -q -rs
