#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

MODEL_ID="Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
MODEL_REVISION="536a35794df8831aa814970ee8f89eff577e7718"
VLLM_VERSION="0.8.5"
TORCH_CUDA_PREFIX="12.4"
TORCH_VERSION="2.6.0"
TORCHVISION_VERSION="0.21.0"
TORCHAUDIO_VERSION="2.6.0"
TRANSFORMERS_VERSION="4.51.3"
HUGGINGFACE_HUB_VERSION="0.30.2"
COMPRESSED_TENSORS_VERSION="0.9.3"
XFORMERS_VERSION="0.0.29.post2"
ROOT_DIR="${VSA_VLLM_ROOT:-${HOME}/.local/share/vsa-agent/local-vllm}"
ENV_DIR="${ROOT_DIR}/env"
HF_HOME="${ROOT_DIR}/huggingface"
MANIFEST_PATH="${ROOT_DIR}/model-manifest.json"
ENVIRONMENT_MANIFEST_PATH="${ROOT_DIR}/environment-manifest.json"
RUNTIME_ENV_PATH="${ROOT_DIR}/runtime-env.sh"
OFFLINE=0
VERIFY_ONLY=0
PRINT_CONTRACT=0

usage() {
  cat <<'EOF'
Usage: ./scripts/bootstrap-local-vllm.sh [options]

Options:
  --root PATH       User-owned environment and model root.
  --offline         Never access the network; require cached packages/model.
  --verify-only     Do not install or download; verify the existing bootstrap.
  --print-contract  Print pinned model/runtime values without changing files.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT_DIR="$2"; ENV_DIR="${ROOT_DIR}/env"; HF_HOME="${ROOT_DIR}/huggingface"; MANIFEST_PATH="${ROOT_DIR}/model-manifest.json"; ENVIRONMENT_MANIFEST_PATH="${ROOT_DIR}/environment-manifest.json"; RUNTIME_ENV_PATH="${ROOT_DIR}/runtime-env.sh"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    --verify-only) VERIFY_ONLY=1; OFFLINE=1; shift ;;
    --print-contract) PRINT_CONTRACT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$PRINT_CONTRACT" == "1" ]]; then
  printf 'MODEL_ID=%s\nMODEL_REVISION=%s\nVLLM_VERSION=%s\nTORCH_CUDA_PREFIX=%s\n' \
    "$MODEL_ID" "$MODEL_REVISION" "$VLLM_VERSION" "$TORCH_CUDA_PREFIX"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_HELPER="${SCRIPT_DIR}/local_vllm_runtime.py"

if [[ ! -f "$RUNTIME_HELPER" ]]; then
  echo "ERROR: local vLLM runtime helper is missing: ${RUNTIME_HELPER}" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR" "$HF_HOME"
chmod 700 "$ROOT_DIR" "$HF_HOME"

available_kib="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $4}')"
required_kib=$((40 * 1024 * 1024))
if [[ "$VERIFY_ONLY" == "0" && "$available_kib" -lt "$required_kib" ]]; then
  echo "ERROR: local vLLM bootstrap requires at least 40 GiB free under ${ROOT_DIR}." >&2
  exit 1
fi

environment_ready() {
  [[ -x "${ENV_DIR}/bin/python" ]] || return 1
  [[ -r "$ENVIRONMENT_MANIFEST_PATH" ]] || return 1
  "${ENV_DIR}/bin/python" "$RUNTIME_HELPER" verify-environment \
    --manifest "$ENVIRONMENT_MANIFEST_PATH" >/dev/null 2>&1
}

if ! environment_ready; then
  if [[ "$VERIFY_ONLY" == "1" ]]; then
    echo "ERROR: pinned local vLLM environment is not ready at ${ENV_DIR}." >&2
    exit 1
  fi
  if [[ ! -x "${ENV_DIR}/bin/python" ]]; then
    if command -v conda >/dev/null 2>&1; then
      conda create --yes --prefix "$ENV_DIR" python=3.12 pip
    else
      bootstrap_python="${PYTHON:-python3}"
      "$bootstrap_python" -m venv "$ENV_DIR"
    fi
  fi
  if [[ "$OFFLINE" == "1" ]]; then
    echo "ERROR: offline mode cannot install a missing or incompatible vLLM environment." >&2
    exit 1
  fi
  "${ENV_DIR}/bin/python" -m pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu124 \
    "vllm==${VLLM_VERSION}" \
    "torch==${TORCH_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}" \
    "transformers==${TRANSFORMERS_VERSION}" \
    "huggingface-hub[hf_xet]==${HUGGINGFACE_HUB_VERSION}" \
    "compressed-tensors==${COMPRESSED_TENSORS_VERSION}" \
    "xformers==${XFORMERS_VERSION}"
  "${ENV_DIR}/bin/python" "$RUNTIME_HELPER" environment-manifest \
    --output "$ENVIRONMENT_MANIFEST_PATH" >/dev/null
  chmod 400 "$ENVIRONMENT_MANIFEST_PATH"
  if ! environment_ready; then
    echo "ERROR: installed local vLLM environment does not match the pinned dependency manifest." >&2
    exit 1
  fi
fi

verify_vllm_cli_contract() {
  local help_text option
  help_text="$("${ENV_DIR}/bin/python" -m vllm.entrypoints.openai.api_server --help)" || {
    echo "ERROR: vLLM API server CLI compatibility probe failed." >&2
    return 1
  }
  for option in \
    --served-model-name --host --port --tensor-parallel-size --quantization --dtype \
    --max-model-len --max-num-seqs --max-num-batched-tokens --gpu-memory-utilization \
    --limit-mm-per-prompt --mm-processor-kwargs --swap-space --cpu-offload-gb \
    --mm-processor-cache-gb --enforce-eager --disable-log-requests; do
    if ! grep -F -- "$option" <<<"$help_text" >/dev/null; then
      echo "ERROR: pinned vLLM ${VLLM_VERSION} does not support required option ${option}." >&2
      return 1
    fi
  done
}

verify_vllm_cli_contract

export HF_HOME
export HF_HUB_DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1
if [[ "$OFFLINE" == "1" ]]; then
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
fi

if [[ -f "$MANIFEST_PATH" ]] && "${ENV_DIR}/bin/python" "$RUNTIME_HELPER" verify-model --model-manifest "$MANIFEST_PATH" >/dev/null; then
  echo "Pinned model is already verified at ${MANIFEST_PATH}."
else
  if [[ "$VERIFY_ONLY" == "1" ]]; then
    echo "ERROR: pinned model manifest is missing or invalid: ${MANIFEST_PATH}." >&2
    exit 1
  fi
  snapshot_path="$("${ENV_DIR}/bin/python" - "$MODEL_ID" "$MODEL_REVISION" "$OFFLINE" <<'PY'
import sys
from huggingface_hub import snapshot_download

model_id, revision, offline = sys.argv[1:]
path = snapshot_download(
    repo_id=model_id,
    revision=revision,
    local_files_only=offline == "1",
)
print(path)
PY
)"
  "${ENV_DIR}/bin/python" "$RUNTIME_HELPER" model-manifest --snapshot "$snapshot_path" --output "$MANIFEST_PATH" >/dev/null
  "${ENV_DIR}/bin/python" "$RUNTIME_HELPER" verify-model --model-manifest "$MANIFEST_PATH" >/dev/null
  chmod 400 "$MANIFEST_PATH"
fi
chmod 400 "$MANIFEST_PATH" "$ENVIRONMENT_MANIFEST_PATH"

{
  printf 'export VSA_LOCAL_VLLM_ROOT=%q\n' "$ROOT_DIR"
  printf 'export VSA_LOCAL_VLLM_PYTHON=%q\n' "${ENV_DIR}/bin/python"
  printf 'export VSA_LOCAL_VLLM_MODEL_MANIFEST=%q\n' "$MANIFEST_PATH"
  printf 'export VSA_LOCAL_VLLM_ENVIRONMENT_MANIFEST=%q\n' "$ENVIRONMENT_MANIFEST_PATH"
  printf 'export HF_HOME=%q\n' "$HF_HOME"
  printf 'export HF_HUB_OFFLINE=1\n'
  printf 'export TRANSFORMERS_OFFLINE=1\n'
  printf 'export HF_HUB_DISABLE_TELEMETRY=1\n'
  printf 'export DO_NOT_TRACK=1\n'
} >"$RUNTIME_ENV_PATH"
chmod 600 "$RUNTIME_ENV_PATH"

remaining_kib="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $4}')"
minimum_remaining_kib=$((10 * 1024 * 1024))
if [[ "$remaining_kib" -lt "$minimum_remaining_kib" ]]; then
  echo "ERROR: bootstrap completed but less than 10 GiB remains under ${ROOT_DIR}." >&2
  exit 1
fi

echo "PASS: local vLLM environment and pinned model are ready."
echo "  root: ${ROOT_DIR}"
echo "  manifest: ${MANIFEST_PATH}"
echo "  environment: ${RUNTIME_ENV_PATH}"
