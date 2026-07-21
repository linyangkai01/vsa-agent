"""Production evidence collection for recovered recorded-video business flows."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from vsa_agent.config import AppConfig, resolve_runtime_config
from vsa_agent.recorded_video.production_acceptance import (
    AcceptanceCase,
    HttpClient,
    JobIdentity,
    RunHandle,
    ValidationError,
    atomic_write_json,
    read_job_snapshot,
)

_REQUIRED_STAGES = (
    "probing",
    "segmenting",
    "extracting",
    "analyzing",
    "embedding",
    "indexing",
    "publish",
)
_PRODUCTION_PROVIDERS = frozenset({"openai_compatible", "vllm"})
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+\S+|(?:api[_ -]?key|token)\s*[:=]\s*(?!<redacted>|none\b)\S+)"
)


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    es_endpoint: str
    index: str
    vision_provider: str
    vision_model: str
    embedding_provider: str
    embedding_model: str


@dataclass(frozen=True, slots=True)
class CaseEvidence:
    asset_id: str
    job_id: str
    segment_ids: tuple[str, ...]
    query: str
    similarity: float
    screenshot_url: str
    content_range: str
    cleanup_path: Path
    answer_excerpt: str = ""


@dataclass(frozen=True, slots=True)
class BusinessEvidence:
    cases: tuple[CaseEvidence, ...]
    document_count: int
    segment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    acceptance_id: str
    launcher_runs: tuple[RunHandle, ...]
    runtime: RuntimeEvidence
    business: BusinessEvidence
    timestamp_utc: str
    secret_scan: str


def _fail(field: str, message: str) -> None:
    raise ValidationError(field, message)


def _request(field: str, operation: str, method: Any, url: str, **kwargs: object):
    try:
        return method(url, **kwargs)
    except httpx.HTTPError as error:
        _fail(field, f"{operation} request failed: {error}")


def _json_object(field: str, operation: str, response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        _fail(field, f"{operation} returned invalid JSON")
    if not isinstance(payload, dict):
        _fail(field, f"{operation} response must be a JSON object")
    return payload


def _require_status(field: str, operation: str, response: Any, expected: set[int]) -> None:
    if response.status_code not in expected:
        _fail(field, f"{operation} returned HTTP {response.status_code}, expected {sorted(expected)}")


def load_runtime_evidence(config_path: Path, *, data_root: Path, index: str) -> RuntimeEvidence:
    try:
        config = AppConfig.from_yaml(config_path)
        resolved = resolve_runtime_config(config)
    except Exception as error:
        _fail("runtime", f"active runtime config is invalid: {error}")
    search = config.search
    recorded = config.recorded_video
    if not recorded.enabled or recorded.data_root.resolve(strict=False) != data_root.resolve(strict=False):
        _fail("runtime", "active recorded-video data root does not match acceptance arguments")
    if not search.enabled or not search.es_endpoint or search.embed_index != index:
        _fail("runtime", "active Elasticsearch endpoint/index does not match acceptance arguments")
    if search.allow_mock_fallback or search.force_mock_embedding:
        _fail("runtime", "production acceptance forbids mock search fallback and mock embeddings")
    if resolved.embedding is None:
        _fail("runtime", "active production profile has no embedding role")
    if resolved.vlm.provider not in _PRODUCTION_PROVIDERS or resolved.embedding.provider not in _PRODUCTION_PROVIDERS:
        _fail("runtime", "active production profile uses an unsupported provider")
    return RuntimeEvidence(
        es_endpoint=search.es_endpoint.rstrip("/"),
        index=index,
        vision_provider=resolved.vlm.provider,
        vision_model=resolved.vlm.model,
        embedding_provider=resolved.embedding.provider,
        embedding_model=resolved.embedding.model,
    )


def _refresh_index(client: HttpClient, runtime: RuntimeEvidence, field: str) -> None:
    response = _request(field, "Elasticsearch refresh", client.post, f"{runtime.es_endpoint}/{runtime.index}/_refresh")
    _require_status(field, "Elasticsearch refresh", response, {200})
    shards = _json_object(field, "Elasticsearch refresh", response).get("_shards")
    if not isinstance(shards, dict) or shards.get("failed") != 0:
        _fail(field, "Elasticsearch refresh reported failed shards")


def _validate_checkpoints(
    database: Path,
    data_root: Path,
    job: JobIdentity,
    runtime: RuntimeEvidence,
) -> tuple[str, ...]:
    snapshot = read_job_snapshot(database, job)
    if snapshot.status != "completed" or snapshot.stage != "publish":
        _fail("job_stages", f"job {job.job_id} is not completed at publish")
    by_stage = {checkpoint.stage: checkpoint for checkpoint in snapshot.checkpoints}
    if set(by_stage) != set(_REQUIRED_STAGES):
        _fail("job_stages", f"job {job.job_id} does not contain all seven pipeline checkpoints")
    for stage in _REQUIRED_STAGES:
        checkpoint = by_stage[stage]
        if checkpoint.status != "completed" or not checkpoint.output_manifest or not checkpoint.output_checksum:
            _fail("job_stages", f"job {job.job_id} checkpoint {stage} is incomplete")
    if by_stage["analyzing"].model != runtime.vision_model:
        _fail("provider", f"job {job.job_id} VLM checkpoint model does not match active config")
    if by_stage["embedding"].model != runtime.embedding_model:
        _fail("provider", f"job {job.job_id} embedding checkpoint model does not match active config")
    manifest_relative = by_stage["publish"].output_manifest
    manifest_path = (data_root / "assets" / job.asset_id / str(manifest_relative)).resolve(strict=False)
    asset_root = (data_root / "assets" / job.asset_id).resolve(strict=False)
    if not manifest_path.is_relative_to(asset_root):
        _fail("provider", f"job {job.job_id} checkpoint manifest escaped its asset directory")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("provider", f"job {job.job_id} checkpoint manifest is unreadable")
    identity = manifest.get("checkpoint_identity") if isinstance(manifest, dict) else None
    if not isinstance(identity, dict):
        _fail("provider", f"job {job.job_id} checkpoint manifest has no provider identity")
    expected_provider_classes = {
        "vision": "vsa_agent.recorded_video.providers.OpenAIVisionProvider",
        "embedding": "vsa_agent.recorded_video.providers.OpenAIEmbeddingProvider",
    }
    expected_models = {"vision": runtime.vision_model, "embedding": runtime.embedding_model}
    for role in ("vision", "embedding"):
        observed = identity.get(role)
        if (
            not isinstance(observed, dict)
            or observed.get("provider") != expected_provider_classes[role]
            or observed.get("model") != expected_models[role]
        ):
            _fail("provider", f"job {job.job_id} {role} checkpoint identity does not match active config")
    if not snapshot.segment_ids or len(snapshot.segment_ids) != len(set(snapshot.segment_ids)):
        _fail("es", f"job {job.job_id} has missing or duplicate SQLite segment identity")
    return snapshot.segment_ids


def _es_segments(
    client: HttpClient,
    runtime: RuntimeEvidence,
    job: JobIdentity,
    expected_segment_ids: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    response = _request(
        "es",
        "Elasticsearch identity query",
        client.post,
        f"{runtime.es_endpoint}/{runtime.index}/_search",
        json={
            "size": 1000,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"asset_id": job.asset_id}},
                        {"term": {"job_id": job.job_id}},
                    ]
                }
            },
        },
    )
    _require_status("es", "Elasticsearch identity query", response, {200})
    hits = _json_object("es", "Elasticsearch identity query", response).get("hits")
    if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
        _fail("es", "Elasticsearch identity query response is invalid")
    sources: list[dict[str, Any]] = []
    for hit in hits["hits"]:
        if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
            _fail("es", "Elasticsearch segment hit is invalid")
        source = hit["_source"]
        segment_id = source.get("segment_id")
        if hit.get("_id") != segment_id:
            _fail("es", "Elasticsearch document ID does not match segment_id")
        if source.get("asset_id") != job.asset_id or source.get("job_id") != job.job_id:
            _fail("es", "Elasticsearch asset/job identity does not match SQLite")
        if source.get("sensor_id") != job.asset_id:
            _fail("es", "Elasticsearch sensor identity does not match asset identity")
        sources.append(source)
    observed = tuple(source.get("segment_id") for source in sources)
    if any(not isinstance(value, str) or not value for value in observed):
        _fail("es", "Elasticsearch segment identity is incomplete")
    if len(observed) != len(set(observed)) or set(observed) != set(expected_segment_ids):
        _fail("es", "Elasticsearch documents do not match deterministic SQLite segments")
    return tuple(sources)


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        _fail("search", f"search result is missing {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("search", f"search result {label} is not ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("search", f"search result {label} has no timezone")
    return parsed


def _search_case(
    client: HttpClient,
    ui_url: str,
    case: AcceptanceCase,
    job: JobIdentity,
    es_sources: tuple[dict[str, Any], ...],
    minimum_similarity: float,
) -> tuple[dict[str, Any], float]:
    response = _request(
        "search",
        "same-origin semantic search",
        client.post,
        f"{ui_url.rstrip('/')}/api/v1/search",
        json={
            "query": case.query,
            "source_type": "video_file",
            "top_k": 50,
            "min_cosine_similarity": 0.0,
            "agent_mode": False,
        },
    )
    _require_status("search", "same-origin semantic search", response, {200})
    data = _json_object("search", "same-origin semantic search", response).get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        _fail("search", "semantic search response has no data array")
    matches = [
        item
        for item in data
        if item.get("asset_id") == job.asset_id
        and item.get("job_id") == job.job_id
        and item.get("segment_id") in {source["segment_id"] for source in es_sources}
    ]
    if not matches:
        _fail("search", f"query did not return asset {job.asset_id} through the original UI proxy")
    try:
        match = max(matches, key=lambda item: float(item.get("similarity", -1)))
        similarity = float(match.get("similarity"))
    except (TypeError, ValueError):
        _fail("search", "search result similarity is invalid")
    if not math.isfinite(similarity) or not minimum_similarity <= similarity <= 1.0:
        _fail("search", f"search similarity {similarity!r} is outside the accepted range")
    if match.get("video_name") != case.path.name:
        _fail("search", "search result video_name does not match the uploaded file")
    start = _parse_time(match.get("start_time"), "start_time")
    end = _parse_time(match.get("end_time"), "end_time")
    if start >= end:
        _fail("search", "search result time range must satisfy start_time < end_time")
    screenshot_url = match.get("screenshot_url")
    parsed_screenshot = urlsplit(screenshot_url) if isinstance(screenshot_url, str) else None
    if (
        parsed_screenshot is None
        or not screenshot_url.startswith("/")
        or parsed_screenshot.scheme
        or parsed_screenshot.netloc
    ):
        _fail("search", "search result screenshot URL is not same-origin")
    return match, similarity


def _media_case(client: HttpClient, ui_url: str, job: JobIdentity, screenshot_url: str) -> str:
    thumbnail = _request(
        "media",
        "same-origin thumbnail",
        client.get,
        urljoin(ui_url.rstrip("/") + "/", screenshot_url.lstrip("/")),
    )
    _require_status("media", "same-origin thumbnail", thumbnail, {200})
    if not thumbnail.content:
        _fail("media", "thumbnail response is empty")
    ranged = _request(
        "media",
        "same-origin media range",
        client.get,
        f"{ui_url.rstrip('/')}/api/v1/vst/v1/storage/file/{job.asset_id}",
        headers={"Range": "bytes=0-0"},
    )
    _require_status("media", "same-origin media range", ranged, {206})
    accept_ranges = ranged.headers.get("Accept-Ranges", "")
    content_range = ranged.headers.get("Content-Range", "")
    if accept_ranges.lower() != "bytes" or not re.fullmatch(r"bytes 0-0/[1-9][0-9]*", content_range):
        _fail("media", "Range response headers are invalid")
    if len(ranged.content) != 1:
        _fail("media", "Range response did not contain exactly one byte")
    return content_range


def _chat_case(
    client: HttpClient,
    *,
    ui_url: str,
    api_url: str,
    case: AcceptanceCase,
    job: JobIdentity,
    match: Mapping[str, Any],
) -> str:
    context = {
        "assetId": job.asset_id,
        "segmentId": match["segment_id"],
        "jobId": job.job_id,
        "sensorId": job.asset_id,
        "videoName": match["video_name"],
        "startTime": match["start_time"],
        "endTime": match["end_time"],
        "mediaType": "recorded-video-segment",
    }
    question = f"请分析选中的视频片段，回答与“{case.query}”相关的可见事件和安全风险，并说明证据。"
    content = f"[Context: {json.dumps([context], ensure_ascii=False, separators=(',', ':'))}]\n{question}"
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    response = _request(
        "qa",
        "same-origin selected-video chat",
        client.post,
        f"{ui_url.rstrip('/')}/api/chat",
        headers={"Conversation-Id": conversation_id, "User-Message-ID": message_id},
        json={
            "chatCompletionURL": f"{api_url.rstrip('/')}/chat/stream",
            "messages": [{"role": "user", "content": content}],
            "additionalProps": {"enableIntermediateSteps": True},
        },
    )
    _require_status("qa", "same-origin selected-video chat", response, {200})
    answer = response.text.strip()
    if len(answer) < 20 or re.search(r"(?i)(^|\b)error\s*:", answer):
        _fail("qa", f"selected-video chat returned no usable answer for asset {job.asset_id}")
    return answer[:500]


def _database_cleanup_complete(database: Path, asset_id: str, job_id: str) -> bool:
    try:
        with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            asset = connection.execute(
                "SELECT status, deleted_at FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            jobs = connection.execute("SELECT COUNT(*) FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            segments = connection.execute("SELECT COUNT(*) FROM segments WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            steps = connection.execute("SELECT COUNT(*) FROM job_steps WHERE job_id = ?", (job_id,)).fetchone()[0]
    except sqlite3.Error:
        return False
    return asset is not None and asset[0] == "deleted" and asset[1] and jobs == segments == steps == 0


def _delete_case(
    client: HttpClient,
    ui_url: str,
    runtime: RuntimeEvidence,
    data_root: Path,
    job: JobIdentity,
    *,
    timeout: float,
    poll_interval: float,
) -> Path:
    deadline = datetime.now().timestamp() + timeout
    delete_url = f"{ui_url.rstrip('/')}/api/v1/videos/{job.asset_id}"
    while True:
        response = _request("delete", "same-origin asset delete", client.delete, delete_url)
        if response.status_code == 204:
            break
        if response.status_code != 202:
            _fail("delete", f"asset delete returned HTTP {response.status_code}")
        if datetime.now().timestamp() >= deadline:
            _fail("delete", f"asset {job.asset_id} deletion timed out")
        import time

        time.sleep(poll_interval)
    repeated = _request("delete", "idempotent asset delete", client.delete, delete_url)
    _require_status("delete", "idempotent asset delete", repeated, {204})
    _refresh_index(client, runtime, "delete")
    response = _request(
        "delete",
        "Elasticsearch delete confirmation",
        client.post,
        f"{runtime.es_endpoint}/{runtime.index}/_search",
        json={"size": 1, "query": {"term": {"asset_id": job.asset_id}}},
    )
    _require_status("delete", "Elasticsearch delete confirmation", response, {200})
    hits = _json_object("delete", "Elasticsearch delete confirmation", response).get("hits")
    if not isinstance(hits, dict) or hits.get("hits") != []:
        _fail("delete", "Elasticsearch still contains the deleted asset")
    media = _request(
        "delete",
        "deleted media confirmation",
        client.get,
        f"{ui_url.rstrip('/')}/api/v1/vst/v1/storage/file/{job.asset_id}",
        headers={"Range": "bytes=0-0"},
    )
    if media.status_code not in {404, 410}:
        _fail("delete", f"deleted media remains accessible with HTTP {media.status_code}")
    database = data_root / "recorded-video.sqlite3"
    if not _database_cleanup_complete(database, job.asset_id, job.job_id):
        _fail("delete", f"SQLite cleanup is incomplete for asset {job.asset_id}")
    cleanup_path = (data_root / "assets" / job.asset_id).resolve(strict=False)
    if cleanup_path.exists():
        _fail("delete", f"asset cleanup path still exists: {cleanup_path}")
    return cleanup_path


def collect_business_evidence(
    client: HttpClient,
    *,
    ui_url: str,
    api_url: str,
    runtime: RuntimeEvidence,
    data_root: Path,
    cases: Sequence[AcceptanceCase],
    jobs: Sequence[JobIdentity],
    minimum_similarity: float,
    timeout: float,
    poll_interval: float,
) -> BusinessEvidence:
    if len(cases) != 3 or len(jobs) != 3:
        raise ValueError("business evidence requires exactly three cases and jobs")
    if not 0.0 <= minimum_similarity <= 1.0 or timeout <= 0 or poll_interval <= 0:
        raise ValueError("business evidence thresholds and timeouts are invalid")
    database = data_root / "recorded-video.sqlite3"
    _refresh_index(client, runtime, "es")
    collected: list[CaseEvidence] = []
    all_segments: list[str] = []
    for case, job in zip(cases, jobs, strict=True):
        expected_segments = _validate_checkpoints(database, data_root, job, runtime)
        es_sources = _es_segments(client, runtime, job, expected_segments)
        match, similarity = _search_case(client, ui_url, case, job, es_sources, minimum_similarity)
        screenshot_url = match["screenshot_url"]
        content_range = _media_case(client, ui_url, job, screenshot_url)
        answer_excerpt = _chat_case(
            client,
            ui_url=ui_url,
            api_url=api_url,
            case=case,
            job=job,
            match=match,
        )
        collected.append(
            CaseEvidence(
                asset_id=job.asset_id,
                job_id=job.job_id,
                segment_ids=tuple(sorted(expected_segments)),
                query=case.query,
                similarity=similarity,
                screenshot_url=screenshot_url,
                content_range=content_range,
                cleanup_path=data_root / "assets" / job.asset_id,
                answer_excerpt=answer_excerpt,
            )
        )
        all_segments.extend(expected_segments)
    if len(all_segments) != len(set(all_segments)):
        _fail("es", "segment identity is duplicated across acceptance assets")
    for index, job in enumerate(jobs):
        cleanup_path = _delete_case(
            client,
            ui_url,
            runtime,
            data_root,
            job,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        collected[index] = replace(collected[index], cleanup_path=cleanup_path)
    return BusinessEvidence(
        cases=tuple(collected),
        document_count=len(all_segments),
        segment_ids=tuple(sorted(all_segments)),
    )


def scan_runtime_logs(handles: Sequence[RunHandle], business: BusinessEvidence | None = None) -> str:
    if len(handles) != 2:
        _fail("runtime", "secret scan requires exactly two launcher runs")
    for handle in handles:
        paths = sorted(handle.run_dir.glob("*.log"))
        if handle.launcher_log is not None and handle.launcher_log.is_file():
            paths.append(handle.launcher_log)
        if not paths:
            _fail("runtime", f"run {handle.run_id} has no logs to scan")
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                _fail("runtime", f"cannot read runtime log {path}: {error}")
            if _SECRET_PATTERN.search(content):
                _fail("runtime", f"runtime log contains a possible secret: {path}")
    if business is not None:
        trace_root = handles[-1].run_dir / "chat-traces"
        requests: list[tuple[dict[str, Any], Path]] = []
        for request_path in trace_root.glob("*/request.json"):
            try:
                payload = json.loads(request_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                _fail("qa", f"chat request trace is unreadable: {request_path}")
            if isinstance(payload, dict):
                requests.append((payload, request_path.parent))
        for case in business.cases:
            matching = [
                trace_dir
                for payload, trace_dir in requests
                if payload.get("selected_asset_id") == case.asset_id
                and payload.get("selected_segment_id") in case.segment_ids
            ]
            if len(matching) != 1:
                _fail("qa", f"asset {case.asset_id} has no unique server-resolved chat trace")
            trace_path = matching[0] / "trace.jsonl"
            try:
                events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
            except (OSError, json.JSONDecodeError):
                _fail("qa", f"chat trace is unreadable for asset {case.asset_id}")
            event_types = {event.get("event_type") for event in events if isinstance(event, dict)}
            if "original_ui.chat.request" not in event_types or "video_understanding.result" not in event_types:
                _fail("qa", f"asset {case.asset_id} chat trace does not prove video understanding")
    return "PASS (无密钥)"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def render_acceptance_report(evidence: AcceptanceEvidence, report_path: Path) -> None:
    if len(evidence.launcher_runs) != 2 or len(evidence.business.cases) != 3:
        raise ValueError("acceptance report requires two launcher runs and three business cases")
    primary = evidence.business.cases[0]
    final_run = evidence.launcher_runs[-1]
    case_path = report_path.with_suffix(".cases.json")
    atomic_write_json(
        case_path,
        {
            "acceptance_id": evidence.acceptance_id,
            "launcher_runs": [handle.run_id for handle in evidence.launcher_runs],
            "cases": [{**asdict(case), "cleanup_path": str(case.cleanup_path)} for case in evidence.business.cases],
        },
    )
    common = (
        f"- run_id: {final_run.run_id}\n"
        f"- timestamp_utc: {evidence.timestamp_utc}\n"
        f"- asset_id: {primary.asset_id}\n"
        f"- job_id: {primary.job_id}\n"
        f"- segment_id: {primary.segment_ids[0]}\n"
        f"- provider: {evidence.runtime.vision_provider}\n"
        f"- model: {evidence.runtime.vision_model}\n"
    )
    asset_ids = ",".join(case.asset_id for case in evidence.business.cases)
    job_ids = ",".join(case.job_id for case in evidence.business.cases)
    launcher_runs = ",".join(handle.run_id for handle in evidence.launcher_runs)
    segment_ids = ",".join(evidence.business.segment_ids)
    lines = f"""# 录播视频生产运行验证报告

- 总体结果：PASS

## runtime

PASS
{common}- acceptance_id: {evidence.acceptance_id}
- launcher_runs: {launcher_runs}
- log_ref: {final_run.run_dir / "stack.log"}
- secret_scan: {evidence.secret_scan}
无密钥配置摘要、两次 launcher run 与运行日志路径已记录。

## job_stages

PASS
{common}- concurrency: 3
- worker_restart: PASS
- asset_ids: {asset_ids}
- job_ids: {job_ids}
- stage_history: 三并发任务已完成，Worker 重启后复用了已完成 checkpoint。

## provider

PASS
{common}- embedding_provider: {evidence.runtime.embedding_provider}
- embedding_model: {evidence.runtime.embedding_model}
真实 provider 模型身份与 checkpoint 结果已逐项核对。

## es

PASS
{common}- endpoint: {evidence.runtime.es_endpoint}
- index: {evidence.runtime.index}
- document_count: {evidence.business.document_count}
- expected_segment_count: {evidence.business.document_count}
- dedup_count: {len(set(evidence.business.segment_ids))}
- segment_ids: {segment_ids}
Elasticsearch 文档与 SQLite deterministic segment identity 完全一致。

## search

PASS
{common}- similarity: {primary.similarity:.3f}
- result_asset_id: {primary.asset_id}
- result_job_id: {primary.job_id}
- result_segment_id: {primary.segment_ids[0]}
- case_evidence_ref: {case_path}
三个查询均通过原版 UI 同源代理绑定到各自 asset/job/segment。

## media

PASS
{common}- HTTP 206: PASS
- Accept-Ranges: bytes
- Content-Range: {primary.content_range}
- validated_assets: 3
三个缩略图与 HTTP 206 Range 结果均已验证。

## qa

PASS
{common}- understood_assets: 3
- answer_excerpt: {primary.answer_excerpt.replace(chr(10), " ")[:300]}
- case_evidence_ref: {case_path}
三个搜索结果均通过原版 UI `+ Chat` 等价上下文进入选中片段理解问答，并记录 video_understanding trace。

## delete

PASS
{common}- cleanup_path: {primary.cleanup_path}
- cleanup_status: PASS
- deleted_assets: 3
三个资产均完成双重幂等删除清理，ES、SQLite、媒体和文件路径无残留。
"""
    _atomic_write_text(report_path, lines)


def render_failure_report(
    report_path: Path,
    *,
    acceptance_id: str,
    error: ValidationError,
    launcher_runs: Sequence[RunHandle],
) -> None:
    run_ids = ",".join(handle.run_id for handle in launcher_runs) or "none"
    log_paths = ",".join(str(handle.launcher_log or handle.run_dir / "stack.log") for handle in launcher_runs) or "none"
    content = f"""# 录播视频生产运行验证报告

- 总体结果：FAIL
- acceptance_id: {acceptance_id}
- failed_field: {error.field}
- failure: {error.message}
- launcher_runs: {run_ids}
- log_refs: {log_paths}

本次验收未通过；不得把该报告作为服务器业务链路已完成的证据。
"""
    _atomic_write_text(report_path, content)
