import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field

LOCAL_CONFIG_FILENAME = "config.local.yaml"


def _deep_merge_config(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_local_config_path(path: Path) -> Path | None:
    override = os.environ.get("VSA_LOCAL_CONFIG")
    if override == "":
        return None
    if override:
        return Path(override)
    return path.with_name(LOCAL_CONFIG_FILENAME)


def _load_yaml_dict(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


class PromptsConfig(BaseModel):
    """All prompt strings consumed by agents and tools."""

    default_system: str = ""
    safety_routine_inspection: str = ""
    safety_incident_investigation: str = ""
    vlm_format_instruction: str = ""


class ModelDevConfig(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    llm_model: str = "gpt-4o"
    vlm_model: str = "gpt-4o"


class ModelProdConfig(BaseModel):
    provider: str = "vllm"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = ""
    llm_model: str = "Qwen3-VL-8B-Instruct"
    vlm_model: str = "Qwen3-VL-8B-Instruct"


class ModelConfig(BaseModel):
    mode: Literal["dev", "prod"] = "dev"
    dev: ModelDevConfig = ModelDevConfig()
    prod: ModelProdConfig = ModelProdConfig()


class BackendConfig(BaseModel):
    """Reusable model-service backend definition."""

    provider: Literal["openai_compatible", "vllm"] = "openai_compatible"
    base_url: str = ""
    api_key_env: str | None = None
    api_key: str = ""
    api_key_required: bool = True
    test_only: bool = False


class RoleBindingConfig(BaseModel):
    backend: str
    model: str


class ProfileConfig(BaseModel):
    llm: RoleBindingConfig
    vlm: RoleBindingConfig
    embedding: RoleBindingConfig | None = None


class RuntimeConfig(BaseModel):
    conda_env: str = "vsa-agent"
    video_path: str = ""
    trace_dir: str = "artifacts/live-video-runs"
    qa_query: str = "Describe what happened in this video and identify any safety risks."


class LocalVLLMRuntimeConfig(BaseModel):
    """Pinned local vLLM deployment and capacity contract."""

    enabled: bool = False
    conda_env: str = "vsa-vllm"
    model_repository: str = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
    model_revision: str = "536a35794df8831aa814970ee8f89eff577e7718"
    served_model_name: str = "qwen2.5-vl-local"
    model_root: Path = Path("/data/project/lyk/models/vsa-agent")
    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(8001, ge=1, le=65535)
    gpu_memory_utilization: float = Field(0.70, gt=0.0, lt=1.0)
    gpu_safety_reserve_mib: int = Field(4096, ge=1024)
    min_available_ram_gib: int = Field(24, ge=1)
    warn_available_ram_gib: int = Field(32, ge=1)
    max_model_len: int = Field(16384, ge=1024)
    max_num_seqs: int = Field(1, ge=1)
    max_num_batched_tokens: int = Field(16384, ge=1024)
    max_images: int = Field(24, ge=1, le=24)
    min_pixels: int = Field(3136, ge=1)
    max_pixels: int = Field(200704, ge=3136)
    dtype: Literal["half"] = "half"
    quantization: Literal["awq"] = "awq"


class ResolvedRoleConfig(BaseModel):
    role: str
    backend: str
    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    api_key_env: str | None = None


class RuntimeResolvedConfig(BaseModel):
    active_profile: str
    llm: ResolvedRoleConfig
    vlm: ResolvedRoleConfig
    embedding: ResolvedRoleConfig | None = None
    runtime: RuntimeConfig = RuntimeConfig()

    def model_dump_redacted(self) -> dict:
        data = self.model_dump()
        for role_name in ("llm", "vlm", "embedding"):
            role = data.get(role_name)
            if role and role.get("api_key"):
                role["api_key"] = "<redacted>"
        return data


ProviderRuntimeConfig = ResolvedRoleConfig


class ConfigIssue(BaseModel):
    severity: Literal["error", "warning"] = "error"
    message: str


class ConfigDiagnostics(BaseModel):
    issues: list[ConfigIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class ToolsConfig(BaseModel):
    """Which tool modules to import at startup."""

    enabled_modules: list[str] = Field(default_factory=lambda: ["vsa_agent.tools.echo_tool"])


class AgentConfig(BaseModel):
    max_iterations: int = 15
    planning_enabled: bool = True
    postprocessing_enabled: bool = True
    log_level: str = "INFO"
    max_history: int = 10


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class VideoUnderstandingConfig(BaseModel):
    """Configuration for short-video understanding."""

    max_fps: float = 2.0
    max_frames: int = Field(24, ge=1, le=24)
    min_pixels: int = Field(56 * 56, ge=1)
    max_pixels: int = Field(448 * 448, ge=56 * 56)
    reasoning_effort: str = "medium"
    filter_thinking: bool = True
    max_retries: int = 3
    time_format: Literal["iso", "offset"] = "iso"
    source_mode: Literal["local", "translated"] = "local"
    translated_base_dir: str | None = None
    vst_sensor_source_map: dict[str, str] = Field(default_factory=dict)


class LVSVideoUnderstandingConfig(BaseModel):
    """Configuration for long-video understanding orchestration."""

    chunk_duration_sec: int = 30
    max_frames_per_chunk: int = 8
    max_chunks: int | None = None
    merge_adjacent_events: bool = True


class SearchBackendConfig(BaseModel):
    """Elasticsearch-backed video search configuration."""

    enabled: bool = False
    es_endpoint: str = ""
    embed_index: str = "vsa-video-embeddings"
    embedding_dimensions: int = Field(1024, gt=0)
    behavior_index: str = "vsa-video-behavior"
    frames_index: str | None = None
    vector_field: str = "vector"
    embed_confidence_threshold: float = 0.0
    request_timeout_sec: float = 30.0
    verify_certs: bool = True
    allow_mock_fallback: bool = True
    force_mock_embedding: bool = False

    @property
    def legacy_embed_index(self) -> str:
        """Dedicated compatibility index; never aliases the production contract."""
        return f"{self.embed_index}-legacy-smoke"


class RecordedVideoConfig(BaseModel):
    """Runtime limits for the recorded-video ingestion pipeline."""

    enabled: bool = False
    data_root: Path = Path(".runtime/recorded-video")
    max_upload_bytes: int = Field(10_737_418_240, gt=0)
    allowed_extensions: set[str] = Field(default_factory=lambda: {"mp4", "mkv"})
    segment_duration_sec: int = Field(30, gt=0)
    representative_frames: int = Field(4, ge=1, le=24)
    worker_concurrency: int = Field(3, ge=1, le=5)
    provider_concurrency: int = Field(1, ge=1, le=5)
    lease_sec: int = Field(120, gt=0)
    max_attempts: int = Field(3, ge=1)
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"


class AppConfig(BaseModel):
    active_profile: str = ""
    backends: dict[str, BackendConfig] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    runtime: RuntimeConfig = RuntimeConfig()
    local_vllm: LocalVLLMRuntimeConfig = LocalVLLMRuntimeConfig()
    model: ModelConfig = ModelConfig()
    tools: ToolsConfig = ToolsConfig()
    agent: AgentConfig = AgentConfig()
    server: ServerConfig = ServerConfig()
    prompts: PromptsConfig = PromptsConfig()
    video_understanding: VideoUnderstandingConfig = VideoUnderstandingConfig()
    lvs_video_understanding: LVSVideoUnderstandingConfig = LVSVideoUnderstandingConfig()
    search: SearchBackendConfig = SearchBackendConfig()
    recorded_video: RecordedVideoConfig = RecordedVideoConfig()

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "AppConfig":
        config_path = Path(path)
        data = _load_yaml_dict(config_path)
        local_path = _resolve_local_config_path(config_path)
        if local_path and local_path.exists():
            data = _deep_merge_config(data, _load_yaml_dict(local_path))
        return cls(**data)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        config_path = os.environ.get("VSA_CONFIG", "config.yaml")
        _config = AppConfig.from_yaml(config_path)
    return _config


def reset_config_cache() -> None:
    global _config
    _config = None


def _legacy_backend_and_profiles(config: AppConfig) -> tuple[dict[str, BackendConfig], dict[str, ProfileConfig], str]:
    if config.model.mode == "dev":
        dev = config.model.dev
        return (
            {
                "dev": BackendConfig(
                    provider="openai_compatible",
                    base_url=dev.base_url,
                    api_key=dev.api_key,
                    api_key_required=False,
                )
            },
            {
                "legacy-dev": ProfileConfig(
                    llm=RoleBindingConfig(backend="dev", model=dev.llm_model),
                    vlm=RoleBindingConfig(backend="dev", model=dev.vlm_model),
                )
            },
            "legacy-dev",
        )

    prod = config.model.prod
    return (
        {
            "prod": BackendConfig(
                provider="vllm",
                base_url=prod.base_url,
                api_key=prod.api_key,
                api_key_required=False,
            )
        },
        {
            "legacy-prod": ProfileConfig(
                llm=RoleBindingConfig(backend="prod", model=prod.llm_model),
                vlm=RoleBindingConfig(backend="prod", model=prod.vlm_model),
            )
        },
        "legacy-prod",
    )


def _runtime_sources(config: AppConfig) -> tuple[dict[str, BackendConfig], dict[str, ProfileConfig], str]:
    if config.active_profile and config.backends and config.profiles:
        active_profile = os.getenv("VSA_PROFILE", "").strip() or config.active_profile
        return config.backends, config.profiles, active_profile
    backends, profiles, active_profile = _legacy_backend_and_profiles(config)
    active_profile = os.getenv("VSA_PROFILE", "").strip() or active_profile
    return backends, profiles, active_profile


def _resolve_api_key(backend: BackendConfig) -> str | None:
    if backend.api_key_env:
        value = os.getenv(backend.api_key_env, "").strip()
        if value:
            return value
    return backend.api_key or None


def _resolve_role(
    role_name: str,
    binding: RoleBindingConfig,
    backends: dict[str, BackendConfig],
) -> ResolvedRoleConfig:
    backend = backends[binding.backend]
    return ResolvedRoleConfig(
        role=role_name,
        backend=binding.backend,
        provider=backend.provider,
        base_url=backend.base_url,
        model=binding.model,
        api_key=_resolve_api_key(backend),
        api_key_env=backend.api_key_env,
    )


def resolve_runtime_config(config: AppConfig | None = None) -> RuntimeResolvedConfig:
    app_config = config or get_config()
    backends, profiles, active_profile = _runtime_sources(app_config)
    profile = profiles[active_profile]
    return RuntimeResolvedConfig(
        active_profile=active_profile,
        llm=_resolve_role("llm", profile.llm, backends),
        vlm=_resolve_role("vlm", profile.vlm, backends),
        embedding=_resolve_role("embedding", profile.embedding, backends) if profile.embedding else None,
        runtime=app_config.runtime,
    )


def _validate_role_bindings(
    backends: dict[str, BackendConfig],
    roles: tuple[tuple[str, RoleBindingConfig | None], ...],
    *,
    require_api_key_env: bool = False,
) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for role_name, binding in roles:
        if binding is None:
            continue
        if binding.backend not in backends:
            issues.append(ConfigIssue(message=f"{role_name} backend '{binding.backend}' is not defined"))
            continue
        backend = backends[binding.backend]
        if not backend.base_url:
            issues.append(ConfigIssue(message=f"{role_name} backend '{binding.backend}' has empty base_url"))
        if not binding.model:
            issues.append(ConfigIssue(message=f"{role_name} model is empty"))
        if not backend.api_key_required:
            continue
        if require_api_key_env:
            api_key_env = backend.api_key_env
            if api_key_env and os.getenv(api_key_env, "").strip():
                continue
            issues.append(
                ConfigIssue(
                    message=(
                        f"{role_name} backend '{binding.backend}' requires API key "
                        f"from api_key_env ({api_key_env or 'not configured'})"
                    )
                )
            )
        elif not _resolve_api_key(backend):
            source = backend.api_key_env or "api_key"
            issues.append(
                ConfigIssue(message=f"{role_name} backend '{binding.backend}' requires API key from {source}")
            )
    return issues


def _validate_local_vllm_runtime(
    config: AppConfig,
    backends: dict[str, BackendConfig],
    profile: ProfileConfig,
) -> list[ConfigIssue]:
    local = config.local_vllm
    if not local.enabled:
        return []

    issues: list[ConfigIssue] = []
    binding = profile.vlm
    backend = backends.get(binding.backend)
    if backend is None:
        return issues
    if backend.provider != "vllm":
        issues.append(ConfigIssue(message="local_vllm requires the active VLM role to use provider 'vllm'"))
        return issues
    if backend.test_only:
        issues.append(ConfigIssue(message="local_vllm VLM backend cannot be test_only"))

    parsed = urlsplit(backend.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        issues.append(ConfigIssue(message="local_vllm VLM backend must use an HTTP loopback base_url"))
    try:
        backend_port = parsed.port
    except ValueError:
        backend_port = None
    if backend_port != local.port:
        issues.append(ConfigIssue(message=f"local_vllm VLM backend must use configured port {local.port}"))
    if local.port == config.server.port:
        issues.append(ConfigIssue(message="local_vllm port must not conflict with the business API port"))
    if binding.model != local.served_model_name:
        issues.append(
            ConfigIssue(message=(f"local_vllm VLM model must match served_model_name '{local.served_model_name}'"))
        )
    if config.video_understanding.max_frames > local.max_images:
        issues.append(ConfigIssue(message="video_understanding.max_frames exceeds local_vllm.max_images"))
    if config.video_understanding.max_pixels > local.max_pixels:
        issues.append(ConfigIssue(message="video_understanding.max_pixels exceeds local_vllm.max_pixels"))
    if config.recorded_video.representative_frames > local.max_images:
        issues.append(ConfigIssue(message="recorded_video.representative_frames exceeds local_vllm.max_images"))
    return issues


def validate_runtime_config(config: AppConfig | None = None) -> ConfigDiagnostics:
    app_config = config or get_config()
    backends, profiles, active_profile = _runtime_sources(app_config)
    if active_profile not in profiles:
        return ConfigDiagnostics(
            issues=[ConfigIssue(message=f"active_profile '{active_profile}' is not defined in profiles")]
        )

    profile = profiles[active_profile]
    issues = _validate_role_bindings(
        backends,
        (
            ("llm", profile.llm),
            ("vlm", profile.vlm),
            ("embedding", profile.embedding),
        ),
    )
    issues.extend(_validate_local_vllm_runtime(app_config, backends, profile))
    return ConfigDiagnostics(issues=issues)


def validate_recorded_video_runtime(config: AppConfig) -> ConfigDiagnostics:
    if not config.recorded_video.enabled:
        return ConfigDiagnostics()
    if config.search.allow_mock_fallback:
        raise ValueError("production recorded video requires allow_mock_fallback=False")
    if config.search.force_mock_embedding:
        raise ValueError("production recorded video requires force_mock_embedding=False")

    backends, profiles, active_profile = _runtime_sources(config)
    if active_profile not in profiles:
        return ConfigDiagnostics(
            issues=[ConfigIssue(message=f"active_profile '{active_profile}' is not defined in profiles")]
        )

    profile = profiles[active_profile]
    issues: list[ConfigIssue] = []
    if profile.embedding is None:
        issues.append(ConfigIssue(message="recorded video requires an embedding provider"))
    issues.extend(
        _validate_role_bindings(
            backends,
            (("vlm", profile.vlm), ("embedding", profile.embedding)),
            require_api_key_env=True,
        )
    )
    issues.extend(_validate_local_vllm_runtime(config, backends, profile))
    return ConfigDiagnostics(issues=issues)
