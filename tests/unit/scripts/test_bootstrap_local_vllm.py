from pathlib import Path

BOOTSTRAP = Path("scripts/bootstrap-local-vllm.sh")
RUNTIME = Path("scripts/local_vllm_runtime.py")


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
