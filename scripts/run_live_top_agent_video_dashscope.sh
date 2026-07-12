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

if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
  exit 2
fi

export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
export VSA_CONDA_ENV="${VSA_CONDA_ENV:-vsa-agent}"
export VSA_PROFILE="${VSA_PROFILE:-dashscope_remote}"
export VSA_LIVE_VIDEO_MODE="${VSA_LIVE_VIDEO_MODE:-shared}"

export VSA_CONFIG="${CONFIG_PATH}"

echo "Resolved unified runtime config"
conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config doctor --config "${VSA_CONFIG}"
conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config print --config "${VSA_CONFIG}"

OPENAI_API_KEY="$(
  conda run -n "${VSA_CONDA_ENV}" python -c "from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml('${VSA_CONFIG}')).llm.api_key or '')"
)"
if [[ -z "${OPENAI_API_KEY}" ]]; then
  echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
  exit 2
fi
export OPENAI_API_KEY

VIDEO_PATH="${1:-}"
if [[ -z "${VIDEO_PATH}" ]]; then
  VIDEO_PATH="$(conda run -n "${VSA_CONDA_ENV}" python -c "from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml('${VSA_CONFIG}')).runtime.video_path)")"
fi
QA_QUERY="${2:-}"

echo "Running DashScope live TopAgent video acceptance"
echo "  config: ${VSA_CONFIG}"
echo "  profile: ${VSA_PROFILE}"
echo "  conda env: ${VSA_CONDA_ENV}"
echo "  mode: ${VSA_LIVE_VIDEO_MODE}"
echo "  video: ${VIDEO_PATH}"

cd "${REPO_ROOT}"
if [[ -n "${QA_QUERY}" ]]; then
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent.live_video_acceptance "${VIDEO_PATH}" "${QA_QUERY}" --mode "${VSA_LIVE_VIDEO_MODE}"
else
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent.live_video_acceptance "${VIDEO_PATH}" --mode "${VSA_LIVE_VIDEO_MODE}"
fi
