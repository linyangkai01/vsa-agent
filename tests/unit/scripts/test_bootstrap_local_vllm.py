from pathlib import Path

BOOTSTRAP = Path("scripts/bootstrap-local-vllm.sh")
RUNTIME = Path("scripts/local_vllm_runtime.py")
STACK = Path("scripts/es-runtime-stack.sh")


def test_bootstrap_is_user_level_pinned_and_idempotent():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "${HOME}/.local/share/vsa-agent/local-vllm" in text
    assert 'MODEL_ID="Qwen/Qwen2.5-VL-7B-Instruct-AWQ"' in text
    assert 'MODEL_REVISION="536a35794df8831aa814970ee8f89eff577e7718"' in text
    assert 'VLLM_VERSION="0.8.5"' in text
    assert 'TORCH_CUDA_PREFIX="12.4"' in text
    assert "sudo" not in text
    assert "apt " not in text
    assert "environment_ready" in text
    assert "Pinned model is already verified" in text


def test_bootstrap_supports_strict_offline_verification_without_download():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "--offline" in text
    assert "--verify-only" in text
    assert "local_files_only=offline" in text
    assert "HF_HUB_OFFLINE=1" in text
    assert "TRANSFORMERS_OFFLINE=1" in text
    assert "verify-model --model-manifest" in text


def test_bootstrap_isolates_pytorch_index_from_general_dependency_resolution():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "--extra-index-url" not in text
    assert "--index-url https://download.pytorch.org/whl/cu124" in text
    assert "--no-deps" in text
    assert text.count('"${ENV_DIR}/bin/python" -m pip install') == 2
    torch_install, general_install = text.split('"${ENV_DIR}/bin/python" -m pip install')[1:]
    assert '"torch==${TORCH_VERSION}"' in torch_install
    assert '"vllm==${VLLM_VERSION}"' in general_install


def test_bootstrap_and_launcher_isolate_user_packages_and_disable_mm_cache():
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    stack = STACK.read_text(encoding="utf-8")

    assert "export PYTHONNOUSERSITE=1" in bootstrap
    assert "printf 'export PYTHONNOUSERSITE=1\\n'" in bootstrap
    assert '"${ENV_DIR}/bin/python" -m pip check' in bootstrap
    assert 'rm -f "$ENVIRONMENT_MANIFEST_PATH"' in bootstrap
    assert 'rm -f "$MANIFEST_PATH"' in bootstrap
    assert "--disable-mm-preprocessor-cache" in bootstrap
    assert "PYTHONNOUSERSITE=1" in stack
    assert "--disable-mm-preprocessor-cache" in stack
    assert "--mm-processor-cache-gb" not in bootstrap
    assert "--mm-processor-cache-gb" not in stack


def test_runtime_contains_exact_official_weight_hashes_and_preflight_contract():
    text = RUNTIME.read_text(encoding="utf-8")

    assert 'MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"' in text
    assert 'MODEL_REVISION = "536a35794df8831aa814970ee8f89eff577e7718"' in text
    assert "4f75e3de726546ee43620d1227d3596cd3ba0fdd19f11faeea71de578d2d1052" in text
    assert "dae4128bbfd2b8d489e838048edc0bbe6e31f269d9b96fa3effe11cc534b8f0c" in text
    assert '"--model-manifest"' in text
    assert '"--calibration"' in text
    assert "GPU_MEMORY_UTILIZATION = 0.70" in text
    assert "--allow-compute-pid" not in text
    assert "--skip-model-hash" not in text
    assert '"--output"' in text
