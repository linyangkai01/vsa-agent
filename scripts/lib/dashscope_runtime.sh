#!/usr/bin/env bash

VSA_DASHSCOPE_RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export VSA_REPO_ROOT="$(cd "${VSA_DASHSCOPE_RUNTIME_DIR}/../.." && pwd)"

vsa_dashscope_preflight() {
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda is required but was not found on PATH" >&2
    return 2
  fi

  export VSA_CONFIG="${VSA_CONFIG:-${VSA_REPO_ROOT}/config.yaml}"
  if [[ ! -f "${VSA_CONFIG}" ]]; then
    echo "Missing config: ${VSA_CONFIG}" >&2
    return 2
  fi

  if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
    echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
    return 2
  fi

  export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
  export VSA_CONDA_ENV="${VSA_CONDA_ENV:-vsa-agent}"
  export VSA_PROFILE="${VSA_PROFILE:-dashscope_remote}"

  echo "Resolved unified runtime config"
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config doctor --config "${VSA_CONFIG}"
  conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config print --config "${VSA_CONFIG}"

  VSA_RESOLVED_LLM_API_KEY="$(
    conda run -n "${VSA_CONDA_ENV}" python -c \
      "import os; from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml(os.environ['VSA_CONFIG'])).llm.api_key or '')"
  )"
  VSA_RESOLVED_LLM_BASE_URL="$(
    conda run -n "${VSA_CONDA_ENV}" python -c \
      "import os; from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml(os.environ['VSA_CONFIG'])).llm.base_url)"
  )"
  VSA_RESOLVED_LLM_MODEL="$(
    conda run -n "${VSA_CONDA_ENV}" python -c \
      "import os; from vsa_agent.config import AppConfig, resolve_runtime_config; print(resolve_runtime_config(AppConfig.from_yaml(os.environ['VSA_CONFIG'])).llm.model)"
  )"

  if [[ -z "${VSA_RESOLVED_LLM_API_KEY}" ]]; then
    echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
    return 2
  fi

  export VSA_RESOLVED_LLM_API_KEY
  export VSA_RESOLVED_LLM_BASE_URL
  export VSA_RESOLVED_LLM_MODEL
}
