import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from vsa_agent.config import (
    AppConfig,
    BackendConfig,
    LocalVLLMRuntimeConfig,
    ProfileConfig,
    ProviderRuntimeConfig,
    RecordedVideoConfig,
    ResolvedRoleConfig,
    RoleBindingConfig,
    SearchBackendConfig,
    ServerConfig,
    validate_recorded_video_runtime,
)


@pytest.fixture(autouse=True)
def isolate_runtime_config(monkeypatch):
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("VSA_LOCAL_CONFIG", "")


def production_config(
    *,
    allow_mock_fallback: bool = False,
    force_mock_embedding: bool = False,
    api_key_env: str | None = "PROVIDER_API_KEY",
    api_key: str = "",
    api_key_required: bool = True,
) -> AppConfig:
    return AppConfig(
        active_profile="production",
        backends={
            "provider": BackendConfig(
                base_url="https://provider.example/v1",
                api_key_env=api_key_env,
                api_key=api_key,
                api_key_required=api_key_required,
            )
        },
        profiles={
            "production": ProfileConfig(
                llm=RoleBindingConfig(backend="provider", model="llm"),
                vlm=RoleBindingConfig(backend="provider", model="vlm"),
                embedding=RoleBindingConfig(backend="provider", model="embedding"),
            )
        },
        recorded_video=RecordedVideoConfig(enabled=True),
        search=SearchBackendConfig(
            allow_mock_fallback=allow_mock_fallback,
            force_mock_embedding=force_mock_embedding,
        ),
    )


def test_recorded_video_defaults_and_limits():
    config = RecordedVideoConfig()

    assert config.enabled is False
    assert config.data_root == Path(".runtime/recorded-video")
    assert config.max_upload_bytes == 10_737_418_240
    assert config.allowed_extensions == {"mp4", "mkv"}
    assert config.segment_duration_sec == 30
    assert config.representative_frames == 4
    assert config.worker_concurrency == 3
    assert config.provider_concurrency == 1
    assert config.lease_sec == 120
    assert config.max_attempts == 3
    assert config.ffmpeg_path == "ffmpeg"
    assert config.ffprobe_path == "ffprobe"


def test_provider_runtime_config_is_public_resolved_role_alias():
    runtime = ProviderRuntimeConfig(
        role="vlm",
        backend="local-vlm",
        provider="vllm",
        base_url="http://localhost:8000/v1",
        model="Qwen3-VL",
    )

    assert ProviderRuntimeConfig is ResolvedRoleConfig
    assert runtime.role == "vlm"
    assert runtime.api_key is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_upload_bytes", 0),
        ("segment_duration_sec", 0),
        ("representative_frames", 0),
        ("representative_frames", 25),
        ("worker_concurrency", 0),
        ("worker_concurrency", 6),
        ("provider_concurrency", 0),
        ("provider_concurrency", 6),
        ("lease_sec", 0),
        ("max_attempts", 0),
    ],
)
def test_recorded_video_rejects_invalid_limits(field, value):
    with pytest.raises(ValidationError, match=field):
        RecordedVideoConfig(**{field: value})


def test_disabled_recorded_video_does_not_require_production_providers():
    diagnostics = validate_recorded_video_runtime(AppConfig())

    assert diagnostics.ok is True
    assert diagnostics.issues == []


@pytest.mark.parametrize(
    ("search_overrides", "message"),
    [
        ({"allow_mock_fallback": True}, "allow_mock_fallback"),
        ({"force_mock_embedding": True}, "force_mock_embedding"),
    ],
)
def test_production_recorded_video_rejects_mock_fallback(search_overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_recorded_video_runtime(production_config(**search_overrides))


def test_production_recorded_video_requires_embedding_provider():
    config = production_config()
    config.profiles["production"].embedding = None

    diagnostics = validate_recorded_video_runtime(config)

    assert diagnostics.ok is False
    assert any("embedding" in issue.message for issue in diagnostics.issues)


def test_production_recorded_video_reports_missing_provider_credentials(monkeypatch):
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)

    diagnostics = validate_recorded_video_runtime(production_config())

    assert diagnostics.ok is False
    assert any("PROVIDER_API_KEY" in issue.message for issue in diagnostics.issues)


def test_production_recorded_video_rejects_inline_only_provider_credentials(monkeypatch):
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)

    diagnostics = validate_recorded_video_runtime(production_config(api_key_env=None, api_key="inline-secret"))

    assert diagnostics.ok is False
    assert any("api_key_env" in issue.message for issue in diagnostics.issues)


def test_production_recorded_video_points_missing_credentials_to_api_key_env():
    diagnostics = validate_recorded_video_runtime(production_config(api_key_env=None))

    assert any("api_key_env (not configured)" in issue.message for issue in diagnostics.issues)
    assert not any(
        issue.message.startswith(("vlm backend", "embedding backend")) and issue.message.endswith("from api_key")
        for issue in diagnostics.issues
    )


def test_production_recorded_video_allows_provider_that_does_not_require_credentials():
    diagnostics = validate_recorded_video_runtime(production_config(api_key_env=None, api_key_required=False))

    assert diagnostics.ok is True


def test_production_recorded_video_accepts_resolvable_providers(monkeypatch):
    monkeypatch.setenv("PROVIDER_API_KEY", "test-only-secret")

    diagnostics = validate_recorded_video_runtime(production_config())

    assert diagnostics.ok is True


@pytest.mark.parametrize(
    "invalid_llm",
    ["binding_backend", "base_url", "model", "credential"],
)
def test_recorded_video_ignores_invalid_llm_when_required_roles_are_valid(monkeypatch, invalid_llm):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config = AppConfig(
        active_profile="production",
        backends={
            "llm": BackendConfig(
                base_url="https://llm.example/v1",
                api_key_required=False,
            ),
            "vlm": BackendConfig(
                base_url="https://vlm.example/v1",
                api_key_required=False,
            ),
            "embedding": BackendConfig(
                base_url="https://embedding.example/v1",
                api_key_required=False,
            ),
        },
        profiles={
            "production": ProfileConfig(
                llm=RoleBindingConfig(backend="llm", model="llm-model"),
                vlm=RoleBindingConfig(backend="vlm", model="vlm-model"),
                embedding=RoleBindingConfig(backend="embedding", model="embedding-model"),
            )
        },
        recorded_video=RecordedVideoConfig(enabled=True),
        search=SearchBackendConfig(
            allow_mock_fallback=False,
            force_mock_embedding=False,
        ),
    )
    if invalid_llm == "binding_backend":
        config.profiles["production"].llm.backend = "missing-llm"
    elif invalid_llm == "base_url":
        config.backends["llm"].base_url = ""
    elif invalid_llm == "model":
        config.profiles["production"].llm.model = ""
    else:
        config.backends["llm"].api_key_required = True
        config.backends["llm"].api_key_env = "LLM_API_KEY"

    diagnostics = validate_recorded_video_runtime(config)

    assert diagnostics.ok is True
    assert diagnostics.issues == []


def test_main_config_enables_production_recorded_video_without_secrets(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-secret")

    config = AppConfig.from_yaml("config.yaml")
    diagnostics = validate_recorded_video_runtime(config)

    assert config.recorded_video.enabled is True
    assert config.search.allow_mock_fallback is False
    assert config.search.force_mock_embedding is False
    assert config.profiles[config.active_profile].embedding is not None
    assert config.active_profile == "local_vlm_hybrid"
    assert config.local_vllm.enabled is True
    assert config.backends["local_vllm"].base_url == "http://127.0.0.1:8001/v1"
    assert config.profiles[config.active_profile].vlm.model == "qwen2.5-vl-local"
    assert config.backends["dashscope"].api_key == ""
    assert diagnostics.ok is True


def local_vllm_production_config(*, base_url: str = "http://127.0.0.1:8001/v1") -> AppConfig:
    return AppConfig(
        active_profile="local",
        backends={
            "remote": BackendConfig(
                base_url="https://dashscope.example/v1",
                api_key_required=False,
            ),
            "local": BackendConfig(
                provider="vllm",
                base_url=base_url,
                api_key_required=False,
            ),
        },
        profiles={
            "local": ProfileConfig(
                llm=RoleBindingConfig(backend="remote", model="llm"),
                vlm=RoleBindingConfig(backend="local", model="qwen2.5-vl-local"),
                embedding=RoleBindingConfig(backend="remote", model="embedding"),
            )
        },
        local_vllm=LocalVLLMRuntimeConfig(enabled=True),
        recorded_video=RecordedVideoConfig(enabled=True),
        search=SearchBackendConfig(allow_mock_fallback=False, force_mock_embedding=False),
    )


def test_local_vllm_production_config_is_valid():
    diagnostics = validate_recorded_video_runtime(local_vllm_production_config())

    assert diagnostics.ok is True


def test_local_vllm_rejects_non_loopback_endpoint():
    diagnostics = validate_recorded_video_runtime(local_vllm_production_config(base_url="https://vlm.example/v1"))

    assert diagnostics.ok is False
    assert any("loopback" in issue.message for issue in diagnostics.issues)


def test_local_vllm_rejects_business_api_port_conflict():
    config = local_vllm_production_config(base_url="http://127.0.0.1:8000/v1")
    config.local_vllm.port = 8000
    config.server = ServerConfig(port=8000)

    diagnostics = validate_recorded_video_runtime(config)

    assert diagnostics.ok is False
    assert any("business API port" in issue.message for issue in diagnostics.issues)


def test_local_vllm_requires_served_model_alias():
    config = local_vllm_production_config()
    config.profiles["local"].vlm.model = "repository-name-is-not-the-served-alias"

    diagnostics = validate_recorded_video_runtime(config)

    assert diagnostics.ok is False
    assert any("served_model_name" in issue.message for issue in diagnostics.issues)


def test_recorded_video_dependencies_are_declared_in_correct_groups():
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = metadata["project"]["dependencies"]
    dev_dependencies = metadata["project"]["optional-dependencies"]["dev"]

    assert "httpx>=0.28" in runtime_dependencies
    assert "aiosqlite>=0.21" in runtime_dependencies
    assert "pytest-httpserver>=1.1" not in runtime_dependencies
    assert "pytest-httpserver>=1.1" in dev_dependencies
