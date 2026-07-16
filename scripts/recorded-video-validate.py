#!/usr/bin/env python3
"""Validate one production recorded-video business flow and write evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import yaml

REPORT_FIELDS = ("runtime", "job_stages", "provider", "es", "search", "media", "delete")
REQUIRED_STAGES = (
    "probing",
    "segmenting",
    "extracting",
    "analyzing",
    "embedding",
    "indexing",
    "publish",
)
_TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
_PRODUCTION_PROVIDERS = frozenset({"openai_compatible", "vllm"})
_CHECKPOINT_PROVIDER_BY_ROLE = {
    "vision": {
        provider: "vsa_agent.recorded_video.providers.OpenAIVisionProvider" for provider in _PRODUCTION_PROVIDERS
    },
    "embedding": {
        provider: "vsa_agent.recorded_video.providers.OpenAIEmbeddingProvider" for provider in _PRODUCTION_PROVIDERS
    },
}


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> httpx.Response: ...

    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...

    def delete(self, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True)
class ValidationOptions:
    api_url: str
    ui_url: str
    report: Path
    config: Path
    data_root: Path
    video: Path
    query: str
    timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    minimum_similarity: float = 0.2


@dataclass(frozen=True)
class StepResult:
    status: str
    detail: str


@dataclass(frozen=True)
class StageEvidence:
    stage: str
    status: str
    output_manifest: str | None
    output_checksum: str | None
    model: str | None
    elapsed_ms: int | None


@dataclass(frozen=True)
class SearchEvidence:
    segment_id: str
    description: str
    start_time: str
    end_time: str
    screenshot_url: str
    similarity: float


@dataclass(frozen=True)
class RuntimeConfig:
    active_profile: str
    vision_provider: str
    vision_model: str
    vision_host: str
    embedding_provider: str
    embedding_model: str
    embedding_host: str
    es_endpoint: str
    index: str
    allow_mock_fallback: bool
    force_mock_embedding: bool


@dataclass(frozen=True)
class SegmentIdentity:
    segment_id: str
    asset_id: str
    job_id: str
    sensor_id: str
    video_name: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class ESEvidence:
    endpoint: str
    index: str
    document_count: int
    segments: tuple[SegmentIdentity, ...]


class ValidationError(RuntimeError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _fail(field: str, message: str) -> None:
    raise ValidationError(field, message)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("runtime", f"active config 缺少 {label} 对象")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("runtime", f"active config 缺少 {label}")
    return value.strip()


def _provider_identity(
    role_name: str,
    role: object,
    backends: dict[str, Any],
) -> tuple[str, str, str]:
    role_config = _mapping(role, f"profile.{role_name}")
    backend_name = _required_text(role_config.get("backend"), f"profile.{role_name}.backend")
    model = _required_text(role_config.get("model"), f"profile.{role_name}.model")
    backend = _mapping(backends.get(backend_name), f"backends.{backend_name}")
    provider = _required_text(backend.get("provider"), f"backends.{backend_name}.provider").lower()
    if re.search(r"(^|[._-])(mock|fake|test)([._-]|$)", provider):
        _fail("runtime", f"{role_name} production provider 禁止使用 mock/fake/test provider")
    if provider not in _PRODUCTION_PROVIDERS:
        _fail("runtime", f"{role_name} production provider 不受支持")
    base_url = _required_text(backend.get("base_url"), f"backends.{backend_name}.base_url")
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        _fail("runtime", f"{role_name} provider base_url 无效")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        _fail("runtime", f"{role_name} provider base_url 无效")
    return provider, model, host if port is None else f"{host}:{port}"


def _load_runtime_config(path: Path) -> RuntimeConfig:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        _fail("runtime", "active config 不可读取或 YAML 无效")
    root = _mapping(document, "root")
    active_profile = _required_text(root.get("active_profile"), "active_profile")
    profiles = _mapping(root.get("profiles"), "profiles")
    profile = _mapping(profiles.get(active_profile), f"profiles.{active_profile}")
    backends = _mapping(root.get("backends"), "backends")
    vision_provider, vision_model, vision_host = _provider_identity("vlm", profile.get("vlm"), backends)
    embedding_provider, embedding_model, embedding_host = _provider_identity(
        "embedding", profile.get("embedding"), backends
    )
    search = _mapping(root.get("search"), "search")
    if search.get("enabled") is not True:
        _fail("runtime", "production search 必须启用")
    allow_mock_fallback = search.get("allow_mock_fallback") is True
    force_mock_embedding = search.get("force_mock_embedding") is True
    if allow_mock_fallback or force_mock_embedding:
        _fail("runtime", "production validation requires mock fallback and mock embedding to be disabled")
    es_endpoint = _normalize_base_url(
        _required_text(search.get("es_endpoint"), "search.es_endpoint"),
        "search.es_endpoint",
    )
    index = _required_text(search.get("embed_index"), "search.embed_index")
    if not re.fullmatch(r"[a-z0-9._-]+", index):
        _fail("runtime", "search.embed_index 格式无效")
    return RuntimeConfig(
        active_profile=active_profile,
        vision_provider=vision_provider,
        vision_model=vision_model,
        vision_host=vision_host,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_host=embedding_host,
        es_endpoint=es_endpoint,
        index=index,
        allow_mock_fallback=allow_mock_fallback,
        force_mock_embedding=force_mock_embedding,
    )


def _runtime_config_summary(config: RuntimeConfig) -> str:
    return (
        f"profile={config.active_profile}; vision={config.vision_model}@{config.vision_host}; "
        f"vision_provider={config.vision_provider}; "
        f"embedding={config.embedding_model}@{config.embedding_host}; "
        f"embedding_provider={config.embedding_provider}; "
        f"es={config.es_endpoint}/{config.index}; mock_fallback=false; mock_embedding=false"
    )


def _normalize_base_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        _fail("runtime", f"{label} 必须是不含凭据的绝对 HTTP(S) URL")
    if parsed.query or parsed.fragment:
        _fail("runtime", f"{label} 不得包含查询参数或片段")
    try:
        port = parsed.port
    except ValueError:
        _fail("runtime", f"{label} 端口无效")
    netloc = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _same_origin_url(base_url: str, path_or_url: str, field: str) -> str:
    candidate = urljoin(f"{base_url}/", path_or_url)
    base = urlsplit(base_url)
    parsed = urlsplit(candidate)
    if (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
        _fail(field, "服务返回了跨源 URL，验证器拒绝访问")
    return candidate


def _request(field: str, operation: str, request: Any, *args: Any, **kwargs: Any) -> httpx.Response:
    try:
        return request(*args, **kwargs)
    except httpx.RequestError as exc:
        _fail(field, f"{operation} 请求失败（{type(exc).__name__}）")
    except TimeoutError:
        _fail(field, f"{operation} 请求超时")
    raise AssertionError("unreachable")


def _require_status(field: str, operation: str, response: httpx.Response, expected: set[int]) -> None:
    if response.status_code not in expected:
        expected_text = "/".join(str(value) for value in sorted(expected))
        _fail(field, f"{operation} 返回 HTTP {response.status_code}，期望 {expected_text}")


def _json_object(field: str, operation: str, response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        _fail(field, f"{operation} 未返回 JSON 对象")
    if not isinstance(payload, dict):
        _fail(field, f"{operation} 未返回 JSON 对象")
    return payload


def _check_runtime(options: ValidationOptions, client: HttpClient) -> tuple[str, str, RuntimeConfig]:
    api_url = _normalize_base_url(options.api_url, "api-url")
    ui_url = _normalize_base_url(options.ui_url, "ui-url")
    if not options.video.is_file() or options.video.stat().st_size <= 0:
        _fail("runtime", "验证视频不存在或为空")
    if not options.query.strip():
        _fail("runtime", "语义质量查询不能为空")
    database_path = options.data_root / "recorded-video.sqlite3"
    if not options.data_root.is_dir() or not database_path.is_file():
        _fail("runtime", "验证数据根目录或 SQLite 状态库不可用")
    runtime_config = _load_runtime_config(options.config)

    health = _request("runtime", "API readiness", client.get, f"{api_url}/health")
    _require_status("runtime", "API readiness", health, {200})
    health_payload = _json_object("runtime", "API readiness", health)
    if health_payload.get("status") != "ok" or health_payload.get("service") != "vsa-agent":
        _fail("runtime", "API readiness 响应不符合生产契约")

    ui = _request("runtime", "UI readiness", client.get, f"{ui_url}/")
    _require_status("runtime", "UI readiness", ui, {200})
    proxy = _request(
        "runtime",
        "UI same-origin proxy readiness",
        client.get,
        f"{ui_url}/api/v1/vst/v1/replay/streams",
    )
    _require_status("runtime", "UI same-origin proxy readiness", proxy, {200})
    return api_url, ui_url, runtime_config


def _upload_and_complete(
    options: ValidationOptions,
    client: HttpClient,
    api_url: str,
    created_assets: list[str],
) -> tuple[str, str, list[str]]:
    created = _request(
        "job_stages",
        "创建上传会话",
        client.post,
        f"{api_url}/api/v1/videos",
        json={"filename": options.video.name},
    )
    _require_status("job_stages", "创建上传会话", created, {200})
    create_payload = _json_object("job_stages", "创建上传会话", created)
    asset_id = create_payload.get("asset_id")
    upload_url = create_payload.get("url")
    if not isinstance(asset_id, str) or not asset_id or not isinstance(upload_url, str) or not upload_url:
        _fail("job_stages", "上传会话缺少稳定 asset_id 或同源 URL")
    created_assets.append(asset_id)

    identifier = f"validation-{uuid.uuid4()}"
    headers = {
        "nvstreamer-chunk-number": "1",
        "nvstreamer-total-chunks": "1",
        "nvstreamer-is-last-chunk": "true",
        "nvstreamer-identifier": identifier,
        "nvstreamer-file-name": options.video.name,
    }
    with options.video.open("rb") as source:
        uploaded = _request(
            "job_stages",
            "上传视频",
            client.post,
            _same_origin_url(api_url, upload_url, "job_stages"),
            files={"mediaFile": (options.video.name, source, "application/octet-stream")},
            headers=headers,
        )
    _require_status("job_stages", "上传视频", uploaded, {200})
    upload_payload = _json_object("job_stages", "上传视频", uploaded)
    if upload_payload.get("sensorId") != asset_id or upload_payload.get("streamId") != asset_id:
        _fail("job_stages", "上传响应的 sensor/stream identity 与 asset_id 不一致")

    completed = _request(
        "job_stages",
        "完成上传",
        client.post,
        f"{api_url}/api/v1/videos/{asset_id}/complete",
        json={},
    )
    _require_status("job_stages", "完成上传", completed, {202})
    complete_payload = _json_object("job_stages", "完成上传", completed)
    job_id = complete_payload.get("job_id")
    status_url = complete_payload.get("status_url")
    if complete_payload.get("asset_id") != asset_id or not isinstance(job_id, str) or not job_id:
        _fail("job_stages", "完成响应缺少匹配的 asset/job identity")
    if not isinstance(status_url, str) or not status_url:
        _fail("job_stages", "完成响应缺少任务状态 URL")

    deadline = time.monotonic() + options.timeout_seconds
    observed: list[str] = []
    while True:
        response = _request(
            "job_stages",
            "查询任务",
            client.get,
            _same_origin_url(api_url, status_url, "job_stages"),
        )
        _require_status("job_stages", "查询任务", response, {200})
        job = _json_object("job_stages", "查询任务", response)
        if job.get("asset_id") != asset_id or job.get("job_id") != job_id:
            _fail("job_stages", "任务查询返回了不一致的 asset/job identity")
        status = job.get("status")
        stage = job.get("stage")
        marker = f"{status}:{stage or '-'}"
        if not observed or observed[-1] != marker:
            observed.append(marker)
        if status in _TERMINAL_JOB_STATUSES:
            if status != "completed" or stage != "publish":
                _fail("job_stages", f"任务未完成 publish，终态为 {status}:{stage or '-'}")
            return asset_id, job_id, observed
        if time.monotonic() >= deadline:
            _fail("job_stages", "任务在验收超时前未进入终态")
        time.sleep(options.poll_interval_seconds)


def _read_stage_evidence(data_root: Path, job_id: str) -> list[StageEvidence]:
    database_path = data_root / "recorded-video.sqlite3"
    try:
        with _readonly_database(database_path) as connection:
            rows = connection.execute(
                """
                SELECT stage, status, output_manifest, output_checksum, model, elapsed_ms
                FROM job_steps WHERE job_id = ?
                """,
                (job_id,),
            ).fetchall()
    except sqlite3.Error:
        _fail("job_stages", "无法读取 SQLite stage checkpoints")
    order = {stage: ordinal for ordinal, stage in enumerate(REQUIRED_STAGES)}
    evidence = [StageEvidence(*row) for row in rows]
    evidence.sort(key=lambda item: order.get(item.stage, len(order)))
    return evidence


@contextmanager
def _readonly_database(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def _check_job_stages(data_root: Path, job_id: str, observed: list[str]) -> list[StageEvidence]:
    evidence = _read_stage_evidence(data_root, job_id)
    stages = tuple(item.stage for item in evidence)
    if stages != REQUIRED_STAGES:
        _fail("job_stages", "SQLite stage history 不完整或顺序错误")
    for item in evidence:
        if item.status != "completed":
            _fail("job_stages", f"stage {item.stage} 未完成")
        if not item.output_manifest or not item.output_checksum:
            _fail("job_stages", f"stage {item.stage} 缺少 manifest/checksum")
        if item.elapsed_ms is None or item.elapsed_ms < 0:
            _fail("job_stages", f"stage {item.stage} 缺少有效耗时")
    if not observed:
        _fail("job_stages", "任务 API 未记录任何状态变化")
    return evidence


def _load_checkpoint_identity(
    data_root: Path,
    asset_id: str,
    evidence: list[StageEvidence],
) -> dict[str, Any]:
    by_stage = {item.stage: item for item in evidence}
    manifests = {by_stage[stage].output_manifest for stage in ("analyzing", "embedding")}
    if None in manifests or len(manifests) != 1:
        _fail("provider", "provider checkpoints 未引用同一份 manifest")
    relative_manifest = manifests.pop()
    if not isinstance(relative_manifest, str):
        _fail("provider", "provider checkpoint manifest 路径无效")
    asset_root = (data_root / "assets" / asset_id).resolve()
    manifest_path = (asset_root / relative_manifest).resolve()
    if not manifest_path.is_relative_to(asset_root):
        _fail("provider", "provider checkpoint manifest 路径越界")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("provider", "provider checkpoint manifest 不可读取或 JSON 无效")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("checkpoint_identity"), dict):
        _fail("provider", "provider checkpoint manifest 缺少 identity")
    return manifest["checkpoint_identity"]


def _check_provider(
    config: RuntimeConfig,
    data_root: Path,
    asset_id: str,
    evidence: list[StageEvidence],
) -> str:
    by_stage = {item.stage: item for item in evidence}
    identity = _load_checkpoint_identity(data_root, asset_id, evidence)
    expected = {
        "vision": (config.vision_provider, config.vision_model, by_stage["analyzing"].model),
        "embedding": (config.embedding_provider, config.embedding_model, by_stage["embedding"].model),
    }
    for role, (active_provider, active_model, stage_model) in expected.items():
        checkpoint = identity.get(role)
        if not isinstance(checkpoint, dict):
            _fail("provider", f"{role} checkpoint 缺少 provider/model identity")
        expected_checkpoint_provider = _CHECKPOINT_PROVIDER_BY_ROLE[role].get(active_provider)
        if checkpoint.get("provider") != expected_checkpoint_provider:
            _fail("provider", f"{role} checkpoint provider 与 active config provider 不匹配")
        if checkpoint.get("model") != active_model or stage_model != active_model:
            _fail("provider", f"{role} checkpoint model 与 active config model 不匹配")
    if not by_stage["analyzing"].model or not by_stage["embedding"].model:
        _fail("provider", "provider checkpoint 缺少 vision/embedding 模型标识")
    return (
        f"vision={config.vision_provider}/{config.vision_model}; "
        f"embedding={config.embedding_provider}/{config.embedding_model}"
    )


def _check_es_checkpoints(evidence: list[StageEvidence]) -> None:
    by_stage = {item.stage: item for item in evidence}
    for stage in ("indexing", "publish"):
        checkpoint = by_stage[stage]
        if checkpoint.status != "completed" or not checkpoint.output_checksum:
            _fail("es", f"Elasticsearch {stage} checkpoint 未完成")


def _check_es(
    config: RuntimeConfig,
    client: HttpClient,
    asset_id: str,
    job_id: str,
) -> ESEvidence:
    index_url = f"{config.es_endpoint}/{config.index}"
    refreshed = _request("es", "Elasticsearch refresh", client.post, f"{index_url}/_refresh")
    _require_status("es", "Elasticsearch refresh", refreshed, {200})
    refresh_payload = _json_object("es", "Elasticsearch refresh", refreshed)
    shards = refresh_payload.get("_shards")
    if not isinstance(shards, dict) or shards.get("failed") != 0:
        _fail("es", "Elasticsearch refresh shard outcome 不完整或失败")

    response = _request(
        "es",
        "Elasticsearch identity query",
        client.post,
        f"{index_url}/_search",
        json={
            "size": 1000,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"asset_id": asset_id}},
                        {"term": {"job_id": job_id}},
                    ]
                }
            },
        },
    )
    _require_status("es", "Elasticsearch identity query", response, {200})
    payload = _json_object("es", "Elasticsearch identity query", response)
    hits_container = payload.get("hits")
    if not isinstance(hits_container, dict) or not isinstance(hits_container.get("hits"), list):
        _fail("es", "Elasticsearch identity query response 无效")
    raw_hits = hits_container["hits"]
    if not raw_hits:
        _fail("es", "Elasticsearch identity query 未命中验证资产")
    segments: list[SegmentIdentity] = []
    for hit in raw_hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
            _fail("es", "Elasticsearch segment hit 结构无效")
        source = hit["_source"]
        segment_id = source.get("segment_id")
        identity_values = {
            "segment_id": segment_id,
            "asset_id": source.get("asset_id"),
            "job_id": source.get("job_id"),
            "sensor_id": source.get("sensor_id"),
            "video_name": source.get("video_name"),
            "start_time": source.get("start_time"),
            "end_time": source.get("end_time"),
        }
        if any(not isinstance(value, str) or not value for value in identity_values.values()):
            _fail("es", "Elasticsearch segment identity 字段不完整")
        if hit.get("_id") != segment_id:
            _fail("es", "Elasticsearch _id 与 segment_id 不一致")
        if source.get("asset_id") != asset_id or source.get("job_id") != job_id:
            _fail("es", "Elasticsearch asset/job identity 不一致")
        if source.get("sensor_id") != asset_id:
            _fail("es", "Elasticsearch sensor/asset identity 不一致")
        segments.append(SegmentIdentity(**identity_values))
    return ESEvidence(
        endpoint=config.es_endpoint,
        index=config.index,
        document_count=len(segments),
        segments=tuple(segments),
    )


def _search(client: HttpClient, api_url: str, query: str, field: str) -> list[dict[str, Any]]:
    response = _request(
        field,
        "语义搜索",
        client.post,
        f"{api_url}/api/v1/search",
        json={
            "query": query,
            "source_type": "video_file",
            "top_k": 10,
            "min_cosine_similarity": 0.0,
            "agent_mode": False,
        },
    )
    _require_status(field, "语义搜索", response, {200})
    payload = _json_object(field, "语义搜索", response)
    data = payload.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        _fail(field, "语义搜索响应缺少 data 数组")
    return data


def _check_search(
    options: ValidationOptions,
    client: HttpClient,
    api_url: str,
    asset_id: str,
    es_evidence: ESEvidence,
) -> SearchEvidence:
    matches = [item for item in _search(client, api_url, options.query, "search") if item.get("sensor_id") == asset_id]
    if not matches:
        _fail("search", "语义查询未命中验证资产")
    match = max(matches, key=lambda item: float(item.get("similarity", -1)))
    description = match.get("description")
    start_time = match.get("start_time")
    end_time = match.get("end_time")
    screenshot_url = match.get("screenshot_url")
    video_name = match.get("video_name")
    try:
        similarity = float(match.get("similarity"))
    except (TypeError, ValueError):
        _fail("search", "搜索结果缺少有效相似度")
    if not math.isfinite(similarity) or not 0.0 <= similarity <= 1.0:
        _fail("search", "搜索结果相似度超出有效范围")
    if similarity < options.minimum_similarity:
        _fail("search", f"搜索质量低于阈值 {options.minimum_similarity:.3f}")
    if video_name != options.video.name:
        _fail("search", "搜索结果 video_name 与验证视频不一致")
    if not all(isinstance(value, str) and value for value in (description, start_time, end_time, screenshot_url)):
        _fail("search", "搜索结果缺少 segment 描述、时间或缩略图 identity")
    start = _parse_search_time(start_time, "start_time")
    end = _parse_search_time(end_time, "end_time")
    if start >= end:
        _fail("search", "搜索结果时间范围必须满足 start_time < end_time")
    matching_segments = [
        segment
        for segment in es_evidence.segments
        if segment.asset_id == asset_id
        and segment.sensor_id == asset_id
        and segment.video_name == video_name
        and segment.start_time == start_time
        and segment.end_time == end_time
    ]
    if len(matching_segments) != 1:
        _fail("search", "搜索 asset/sensor/time identity 无法对应唯一 Elasticsearch segment_id")
    return SearchEvidence(
        matching_segments[0].segment_id,
        description,
        start_time,
        end_time,
        screenshot_url,
        similarity,
    )


def _parse_search_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("search", f"搜索结果 {label} 不是合法 ISO 时间")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("search", f"搜索结果 {label} 缺少时区")
    return parsed


def _check_media(client: HttpClient, api_url: str, asset_id: str, search: SearchEvidence) -> None:
    screenshot = _request(
        "media",
        "缩略图",
        client.get,
        _same_origin_url(api_url, search.screenshot_url, "media"),
    )
    _require_status("media", "缩略图", screenshot, {200})
    if not screenshot.content:
        _fail("media", "缩略图响应为空")

    media_url = f"{api_url}/api/v1/vst/v1/storage/file/{asset_id}"
    ranged = _request("media", "HTTP Range", client.get, media_url, headers={"Range": "bytes=0-0"})
    if ranged.status_code != 206:
        _fail("media", f"HTTP Range 请求未返回 206，而是 {ranged.status_code}")
    if ranged.headers.get("Accept-Ranges", "").lower() != "bytes":
        _fail("media", "HTTP 206 缺少 Accept-Ranges: bytes")
    if not re.fullmatch(r"bytes 0-0/[1-9][0-9]*", ranged.headers.get("Content-Range", "")):
        _fail("media", "HTTP 206 的 Content-Range 不符合单字节请求")
    if len(ranged.content) != 1:
        _fail("media", "HTTP 206 未返回一个字节")


def _database_cleanup_complete(data_root: Path, asset_id: str, job_id: str | None) -> bool:
    database_path = data_root / "recorded-video.sqlite3"
    try:
        with _readonly_database(database_path) as connection:
            asset = connection.execute(
                "SELECT status, deleted_at FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            jobs = connection.execute("SELECT COUNT(*) FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            segments = connection.execute("SELECT COUNT(*) FROM segments WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            steps = (
                connection.execute(
                    "SELECT COUNT(*) FROM job_steps WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
                if job_id is not None
                else 0
            )
    except sqlite3.Error:
        return False
    return asset is not None and asset[0] == "deleted" and asset[1] is not None and jobs == segments == steps == 0


def _check_es_asset_deleted(config: RuntimeConfig, client: HttpClient, asset_id: str) -> None:
    index_url = f"{config.es_endpoint}/{config.index}"
    refreshed = _request("delete", "Elasticsearch delete refresh", client.post, f"{index_url}/_refresh")
    _require_status("delete", "Elasticsearch delete refresh", refreshed, {200})
    refresh_payload = _json_object("delete", "Elasticsearch delete refresh", refreshed)
    shards = refresh_payload.get("_shards")
    if not isinstance(shards, dict) or shards.get("failed") != 0:
        _fail("delete", "Elasticsearch delete refresh shard outcome 不完整或失败")
    response = _request(
        "delete",
        "Elasticsearch delete identity query",
        client.post,
        f"{index_url}/_search",
        json={"size": 1, "query": {"term": {"asset_id": asset_id}}},
    )
    _require_status("delete", "Elasticsearch delete identity query", response, {200})
    payload = _json_object("delete", "Elasticsearch delete identity query", response)
    hits = payload.get("hits")
    if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
        _fail("delete", "Elasticsearch delete identity query response 无效")
    if hits["hits"]:
        _fail("delete", "删除后 Elasticsearch 仍保留验证资产 identity")


def _delete_and_confirm(
    options: ValidationOptions,
    client: HttpClient,
    api_url: str,
    config: RuntimeConfig,
    asset_id: str,
    job_id: str | None,
) -> None:
    deadline = time.monotonic() + options.timeout_seconds
    delete_url = f"{api_url}/api/v1/videos/{asset_id}"
    while True:
        response = _request("delete", "删除验证资产", client.delete, delete_url)
        if response.status_code == 204:
            break
        if response.status_code != 202:
            _fail("delete", f"删除验证资产返回 HTTP {response.status_code}，期望 202/204")
        if time.monotonic() >= deadline:
            _fail("delete", "删除验证资产在超时前未完成")
        time.sleep(options.poll_interval_seconds)

    _check_es_asset_deleted(config, client, asset_id)
    media = _request(
        "delete",
        "删除后媒体确认",
        client.get,
        f"{api_url}/api/v1/vst/v1/storage/file/{asset_id}",
        headers={"Range": "bytes=0-0"},
    )
    if media.status_code not in {404, 410}:
        _fail("delete", f"删除后媒体仍可访问（HTTP {media.status_code}）")
    if not _database_cleanup_complete(options.data_root, asset_id, job_id):
        _fail("delete", "删除后 SQLite job/segment/tombstone 清理不完整")


def _write_report(options: ValidationOptions, results: dict[str, StepResult]) -> None:
    overall = "PASS" if all(results[field].status == "PASS" for field in REPORT_FIELDS) else "FAIL"
    lines = [
        "# 录播视频生产运行验证报告",
        "",
        f"- 生成时间（UTC）：{datetime.now(UTC).isoformat()}",
        f"- 总体结果：{overall}",
        f"- API：{_report_url(options.api_url)}",
        f"- UI：{_report_url(options.ui_url)}",
        f"- 验证视频：{options.video.name}（{options.video.stat().st_size if options.video.is_file() else 0} bytes）",
        "- 配置摘要：仅记录非敏感运行标识；未记录环境变量、Authorization 或 API key。",
        "",
    ]
    for field in REPORT_FIELDS:
        result = results[field]
        lines.extend((f"## {field}", "", result.status, "", result.detail, ""))
    options.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = options.report.with_name(f".{options.report.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(options.report)


def _report_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "invalid"
    try:
        port = parsed.port
    except ValueError:
        return "invalid"
    netloc = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _check_quality_options(options: ValidationOptions) -> None:
    if not math.isfinite(options.timeout_seconds) or options.timeout_seconds <= 0:
        _fail("runtime", "timeout must be a finite positive number")
    if not math.isfinite(options.poll_interval_seconds) or options.poll_interval_seconds < 0:
        _fail("runtime", "poll interval must be a finite non-negative number")
    if not math.isfinite(options.minimum_similarity) or not 0.0 <= options.minimum_similarity <= 1.0:
        _fail("runtime", "minimum similarity must be between 0 and 1")


def run_validation(options: ValidationOptions, *, client: HttpClient | None = None) -> int:
    results = {field: StepResult("FAIL", "未执行：前置验证尚未完成。") for field in REPORT_FIELDS}
    current_field = "runtime"
    asset_id: str | None = None
    job_id: str | None = None
    runtime_config: RuntimeConfig | None = None
    created_assets: list[str] = []
    owned_client = False
    http_client: HttpClient | None = client
    api_url = _report_url(options.api_url)
    failure: ValidationError | None = None
    try:
        _check_quality_options(options)
        if http_client is None:
            http_client = httpx.Client(timeout=options.timeout_seconds, follow_redirects=False)
            owned_client = True
        api_url, _, runtime_config = _check_runtime(options, http_client)
        results["runtime"] = StepResult(
            "PASS",
            "API、原版 UI 与 UI 同源代理 readiness 通过；本地 SQLite 与验证视频可读；"
            f"{_runtime_config_summary(runtime_config)}。",
        )

        current_field = "job_stages"
        asset_id, job_id, observed = _upload_and_complete(options, http_client, api_url, created_assets)
        stages = _check_job_stages(options.data_root, job_id, observed)
        results["job_stages"] = StepResult(
            "PASS",
            f"任务 {job_id} 完成；持久化阶段顺序：{' -> '.join(item.stage for item in stages)}；"
            f"API 轨迹：{', '.join(observed)}。",
        )

        current_field = "provider"
        provider_detail = _check_provider(runtime_config, options.data_root, asset_id, stages)
        results["provider"] = StepResult("PASS", f"真实 provider checkpoints 完成：{provider_detail}。")

        current_field = "es"
        _check_es_checkpoints(stages)
        es_evidence = _check_es(runtime_config, http_client, asset_id, job_id)
        results["es"] = StepResult(
            "FAIL",
            "真实 Elasticsearch identity query 已命中，但原版业务搜索 identity 尚未确认。",
        )

        current_field = "search"
        search = _check_search(options, http_client, api_url, asset_id, es_evidence)
        results["es"] = StepResult(
            "PASS",
            "indexing/publish checkpoints、真实 Elasticsearch 调用与业务搜索 identity 均通过；"
            f"endpoint={es_evidence.endpoint}; index={es_evidence.index}; documents={es_evidence.document_count}。",
        )
        segment_identity = f"{asset_id}|{search.segment_id}|{search.start_time}|{search.end_time}"
        results["search"] = StepResult(
            "PASS",
            f"语义查询命中验证资产；segment identity={segment_identity}；similarity={search.similarity:.3f}。",
        )

        current_field = "media"
        _check_media(http_client, api_url, asset_id, search)
        results["media"] = StepResult("PASS", "缩略图非空；单字节 Range 返回 HTTP 206 与有效 Content-Range。")
    except ValidationError as exc:
        failure = exc
        results[exc.field] = StepResult("FAIL", exc.message)
        for field in REPORT_FIELDS[REPORT_FIELDS.index(exc.field) + 1 :]:
            results[field] = StepResult("FAIL", f"未执行：受 {exc.field} 失败阻断。")
    except Exception as exc:
        failure = ValidationError(current_field, f"验证器发生未预期错误（{type(exc).__name__}）")
        results[current_field] = StepResult("FAIL", failure.message)
        for field in REPORT_FIELDS[REPORT_FIELDS.index(current_field) + 1 :]:
            results[field] = StepResult("FAIL", f"未执行：受 {current_field} 失败阻断。")
    finally:
        cleanup_asset_id = asset_id or (created_assets[-1] if created_assets else None)
        if cleanup_asset_id is not None and runtime_config is not None and http_client is not None:
            try:
                _delete_and_confirm(options, http_client, api_url, runtime_config, cleanup_asset_id, job_id)
                results["delete"] = StepResult("PASS", "ES、媒体和 SQLite 生命周期数据均已清理，资产仅保留 tombstone。")
            except ValidationError as exc:
                results["delete"] = StepResult("FAIL", exc.message)
                failure = failure or exc
            except Exception as exc:
                results["delete"] = StepResult("FAIL", f"清理发生未预期错误（{type(exc).__name__}）")
                failure = failure or ValidationError("delete", results["delete"].detail)
        if owned_client and http_client is not None:
            close = getattr(http_client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    close_failure = ValidationError("runtime", f"HTTP client 关闭失败（{type(exc).__name__}）")
                    results["runtime"] = StepResult("FAIL", close_failure.message)
                    failure = failure or close_failure
        try:
            _write_report(options, results)
        except OSError as exc:
            print(f"recorded-video validation report write failed: {type(exc).__name__}", file=sys.stderr)
            return 1

    return 0 if failure is None and all(results[field].status == "PASS" for field in REPORT_FIELDS) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="Loopback FastAPI base URL")
    parser.add_argument("--ui-url", required=True, help="Loopback original UI base URL")
    parser.add_argument("--report", required=True, type=Path, help="Markdown evidence report path")
    parser.add_argument("--config", default=os.getenv("VSA_CONFIG", "config.yaml"), type=Path)
    parser.add_argument("--data-root", default=os.getenv("VSA_RECORDED_VIDEO_DATA_ROOT", ""), type=Path)
    parser.add_argument("--video", default=os.getenv("VSA_VALIDATION_VIDEO", ""), type=Path)
    parser.add_argument("--query", default=os.getenv("VSA_VALIDATION_QUERY", ""))
    parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=600.0)
    parser.add_argument("--poll-interval", dest="poll_interval_seconds", type=float, default=1.0)
    parser.add_argument("--minimum-similarity", type=float, default=0.2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    options = ValidationOptions(
        api_url=args.api_url,
        ui_url=args.ui_url,
        report=args.report,
        config=args.config,
        data_root=args.data_root,
        video=args.video,
        query=args.query,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        minimum_similarity=args.minimum_similarity,
    )
    exit_code = run_validation(options)
    print(f"recorded-video validation {'passed' if exit_code == 0 else 'failed'}: {options.report}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
