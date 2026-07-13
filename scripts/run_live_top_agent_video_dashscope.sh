#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/dashscope_runtime.sh"

export VSA_LIVE_VIDEO_MODE="${VSA_LIVE_VIDEO_MODE:-shared}"

vsa_dashscope_preflight

OPENAI_API_KEY="${VSA_RESOLVED_LLM_API_KEY}"
export OPENAI_API_KEY

VIDEO_PATH="${1:-}"
if [[ -z "${VIDEO_PATH}" ]]; then
  VIDEO_PATH="$(
    conda run -n "${VSA_CONDA_ENV}" python -c \
      "import os; from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml(os.environ['VSA_CONFIG'])).runtime.video_path)"
  )"
fi
QA_QUERY="${2:-}"

echo "Running DashScope live TopAgent video acceptance"
echo "  config: ${VSA_CONFIG}"
echo "  profile: ${VSA_PROFILE}"
echo "  conda env: ${VSA_CONDA_ENV}"
echo "  mode: ${VSA_LIVE_VIDEO_MODE}"
echo "  video: ${VIDEO_PATH}"

cd "${VSA_REPO_ROOT}"
if [[ -n "${QA_QUERY}" ]]; then
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent.live_video_acceptance "${VIDEO_PATH}" "${QA_QUERY}" --mode "${VSA_LIVE_VIDEO_MODE}"
else
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent.live_video_acceptance "${VIDEO_PATH}" --mode "${VSA_LIVE_VIDEO_MODE}"
fi
