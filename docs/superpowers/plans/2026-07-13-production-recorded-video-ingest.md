---
change: production-recorded-video-ingest
design-doc: docs/superpowers/specs/2026-07-12-production-recorded-video-ingest-design.md
base-ref: b3cbea8473da7f15fccebbd4a0aabb8e4c357676
---

# 真实录播视频生产闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入 NVIDIA VST、RTSP、Redis/Celery、S3/MinIO 或管理员权限的前提下，让原版 UI 对真实 MP4/MKV 完成上传、异步分析、语义检索、缩略图和 Range 播放的可恢复单机闭环。

**Architecture:** 新建 `vsa_agent.recorded_video` 领域包，SQLite WAL 记录唯一业务状态，`LocalAssetStore` 保存原始/派生字节，ES 只保存可重建的 segment 搜索投影。FastAPI 仅处理短请求并通过 `/api/v1` 提供上传、任务、媒体和 VST facade；独立 Worker 通过租约执行可检查点的 `probe -> segment -> extract -> analyze -> embed -> index -> publish` 流水线。原版 UI 保持 nvstreamer 三段式上传，Next 同源 rewrite 流式转发到 loopback API。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite WAL、`elasticsearch[async]` 8.14-<9、OpenAI-compatible HTTP API、ffprobe/ffmpeg、Next.js 15、React 18、Jest、Playwright、Docker Compose、Bash/PowerShell。

## Global Constraints

- 所有产物语言为 `zh-CN`；实现基线为 `b3cbea8473da7f15fccebbd4a0aabb8e4c357676`。
- 默认仅绑定 `127.0.0.1`；浏览器只通过 `ssh -L 3000:127.0.0.1:3000 <server>` 访问 UI，不开放 API/ES 端口。
- 不引入 NVIDIA 运行时、RTSP、告警、Kafka/MDX、多节点、S3/MinIO、Redis/Celery、本地模型或场景分段依赖。
- 上传仅接受配置允许的 `.mp4`、`.mkv`，默认单文件上限 `10737418240` 字节，chunk 固定 `10485760` 字节；物理路径只能由 UUID 派生，绝不拼接用户文件名。
- SQLite 是资产和任务状态事实源，ES 是可重放搜索投影；未 `ready` 的资产和未 `completed` 的任务不得出现在生产 alias 的搜索结果中。
- `asset_id`、`sensorId`、`streamId` 使用同一稳定 UUID；`segment_id = uuid5(asset_id + pipeline_version + ordinal)`，ES 文档 ID 等于 `segment_id`。
- VLM/embedding 使用 OpenAI-compatible API；生产 profile 禁止静默 mock/in-memory fallback，测试/smoke profile 必须显式开启 fallback。
- 不在 YAML、SQLite 快照、manifest 或日志中写入 API key、Authorization、原始视频字节或完整模型请求图片。
- 不使用 sudo；端口回收只终止当前用户拥有的监听进程，其他所有者导致启动失败并打印 PID/命令。
- 默认启动只做非写入 readiness；`--validate` 必须使用隔离 validation alias/数据并在结束后清理。

---

## 文件结构与职责

| 路径 | 职责 |
|---|---|
| `src/vsa_agent/config.py`、`config.yaml` | `recorded_video`、provider 与生产搜索配置的解析、校验、脱敏输出。 |
| `src/vsa_agent/recorded_video/models.py` | Asset、UploadSession、Job、JobStep、Segment、状态机和错误码。 |
| `src/vsa_agent/recorded_video/ports.py` | `AssetStore`、`JobRepository`、`Segmenter`、`VisionProvider`、`EmbeddingProvider` 协议。 |
| `src/vsa_agent/recorded_video/repository.py` | SQLite WAL schema/migration、事务、租约、重试、删除和查询。 |
| `src/vsa_agent/recorded_video/assets.py` | UUID 文件布局、chunk 写入、fsync/rename、Range 文件打开、磁盘与临时目录回收。 |
| `src/vsa_agent/recorded_video/segmenter.py`、`media.py` | 固定时段、时间轴换算、ffprobe/ffmpeg、帧/缩略图/proxy。 |
| `src/vsa_agent/recorded_video/providers.py` | OpenAI-compatible Vision/Embedding 调用、结构校验、限流和安全日志。 |
| `src/vsa_agent/recorded_video/pipeline.py`、`worker.py` | manifest/checkpoint、ES 投影调用、取消、恢复、Worker 入口。 |
| `src/vsa_agent/recorded_video/es_index.py` | 版本化 mapping、alias bootstrap/校验、bulk 投影、对账与删除。 |
| `src/vsa_agent/api/recorded_video.py`、`recorded_video_vst.py` | `/api/v1/videos`、jobs、媒体、删除和 VST-compatible facade。 |
| `src/vsa_agent/api/routes.py` | 注册新路由，保留既有 `/api/v1/search` 契约。 |
| `frontend/original-ui/.../next.config.js` | `/api/v1` 同源流式 rewrite，保留内部 API 基址。 |
| `frontend/original-ui/.../video-management/**`、`packages/common/**` | job/status 类型、轮询、processing/failed/cancelled UI、缩略图/播放调用。 |
| `scripts/recorded-video-worker.py`、`scripts/runtime-doctor.py`、`scripts/es-runtime-stack.{sh,ps1}` | doctor、Worker 生命周期、run-id 日志、非写入启动与显式验证。 |
| `tests/unit/recorded_video/**`、`tests/unit/api/**`、`tests/integration/**`、`tests/acceptance/**`、前端 Jest/Playwright | 单元、组件、故障注入和真实服务器验收。 |

### Task 1: 配置、依赖与生产 profile（OpenSpec 1.1）

**Files:**
- Modify: `pyproject.toml`, `src/vsa_agent/config.py`, `config.yaml`, `tests/unit/test_config.py`
- Create: `tests/unit/recorded_video/test_config.py`

**Interfaces:**
- Produces: `RecordedVideoConfig`、`ProviderRuntimeConfig`、`validate_recorded_video_runtime(config: AppConfig) -> ConfigDiagnostics`；`AppConfig.recorded_video: RecordedVideoConfig`。

- [x] **Step 1: 写出配置缺失/越界的失败测试。**
```python
def test_production_recorded_video_rejects_mock_and_invalid_limits():
    with pytest.raises(ValidationError, match="max_upload_bytes"):
        RecordedVideoConfig(max_upload_bytes=0)
    with pytest.raises(ValueError, match="allow_mock_fallback"):
        validate_recorded_video_runtime(production_config(force_mock_embedding=True))
```
- [x] **Step 2: 运行失败测试。** Run: `pytest tests/unit/recorded_video/test_config.py -q`。Expected: FAIL，导入或验证器不存在。
- [x] **Step 3: 实现最小配置和依赖。**
```python
class RecordedVideoConfig(BaseModel):
    enabled: bool = False; data_root: Path = Path(".runtime/recorded-video")
    max_upload_bytes: int = Field(10737418240, gt=0)
    allowed_extensions: set[str] = {"mp4", "mkv"}; segment_duration_sec: int = Field(30, gt=0)
    representative_frames: int = Field(4, gt=0); worker_concurrency: int = Field(3, ge=1, le=5)
    lease_sec: int = Field(120, gt=0); max_attempts: int = Field(3, ge=1)
```
在 `project.dependencies` 添加 `httpx>=0.28`、`aiosqlite>=0.21`，在 `project.optional-dependencies.dev` 添加 `pytest-httpserver>=1.1`；配置校验要求 production 的 `allow_mock_fallback=False`、`force_mock_embedding=False` 和 provider 凭据环境变量存在。`data_root` 的默认值保证既有 `AppConfig()` 无需调用方补值。
- [x] **Step 4: 运行配置测试。** Run: `pytest tests/unit/test_config.py tests/unit/recorded_video/test_config.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add pyproject.toml config.yaml src/vsa_agent/config.py tests/unit/test_config.py tests/unit/recorded_video/test_config.py && git commit -m "feat: add recorded video runtime configuration"`。

### Task 2: 领域模型、状态机、错误分类和基础协议（OpenSpec 1.2、3.1）

**Files:**
- Create: `src/vsa_agent/recorded_video/models.py`, `src/vsa_agent/recorded_video/errors.py`, `src/vsa_agent/recorded_video/ports.py`, `tests/unit/recorded_video/__init__.py`, `tests/unit/recorded_video/test_models.py`, `tests/unit/recorded_video/test_ports.py`

**Interfaces:**
- Produces: `AssetStatus`, `JobStatus`, `JobStage`, `Asset`, `UploadSession`, `Job`, `JobStep`, `Segment`, `RecordedVideoError(code, retryable)`；`transition_job(job, target) -> Job`；`AssetStore`、`JobRepository`、`Segmenter`、`VisionProvider`、`EmbeddingProvider`、`SearchProjectionStore`。

- [x] **Step 1: 写非法迁移和协议可替换性测试。**
```python
def test_running_job_cannot_return_to_queued_and_segment_id_is_stable():
    with pytest.raises(InvalidStateTransition): transition_job(job(JobStatus.RUNNING), JobStatus.QUEUED)
    assert segment_id("a", "v1", 2) == segment_id("a", "v1", 2)

def test_projection_store_is_a_structural_port():
    assert isinstance(FakeProjectionStore(), SearchProjectionStore)
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_models.py tests/unit/recorded_video/test_ports.py -q`。Expected: FAIL，模块或协议不存在。
- [x] **Step 3: 实现受限状态图和先行端口。**
```python
ALLOWED_JOB_TRANSITIONS = {QUEUED:{RUNNING,CANCELLED}, RUNNING:{COMPLETED,RETRY_WAIT,FAILED,CANCELLED}, RETRY_WAIT:{QUEUED}, COMPLETED:set(), FAILED:set(), CANCELLED:set()}
def segment_id(asset_id: str, pipeline_version: str, ordinal: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{asset_id}:{pipeline_version}:{ordinal}"))

@runtime_checkable
class SearchProjectionStore(Protocol):
    async def project(self, documents: Sequence[Mapping[str, Any]]) -> ProjectionResult: ...
    async def delete_asset(self, asset_id: str) -> None: ...
```
同一文件定义 `ProjectionResult(indexed_ids: list[str], failed_ids: list[str])`，并用 `Protocol` 定义其余端口的最小方法：`AssetStore.write_chunk/assemble_source`、`JobRepository.claim_due_job/checkpoint_step`、`Segmenter.plan`、`VisionProvider.describe`、`EmbeddingProvider.embed`。定义永久错误 `CORRUPT_MEDIA/UNSUPPORTED_MEDIA/FFMPEG_MISSING/CONFIGURATION/EMBEDDING_DIMENSION`，可重试错误 `MODEL_RATE_LIMIT/MODEL_TIMEOUT/MODEL_5XX/ES_TIMEOUT/ES_5XX`。
`JobStage` 必须包含最终 `publish` 阶段；`Job.config_snapshot` 必须保持递归不可变且可 JSON 序列化，状态迁移副本不得共享可变配置。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_models.py tests/unit/recorded_video/test_ports.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/models.py src/vsa_agent/recorded_video/errors.py src/vsa_agent/recorded_video/ports.py tests/unit/recorded_video/__init__.py tests/unit/recorded_video/test_models.py tests/unit/recorded_video/test_ports.py && git commit -m "feat: define recorded video domain ports"`。

### Task 3: SQLite WAL repository 与租约（OpenSpec 1.3）

**Files:**
- Create: `src/vsa_agent/recorded_video/repository.py`, `tests/unit/recorded_video/test_repository.py`

**Interfaces:**
- Consumes: Task 2 的 `JobRepository` 协议和领域模型。
- Produces: `JobRepository.initialize()`, `create_upload_session()`, `record_chunk()`, `complete_upload()`, `claim_due_job(owner, now)`, `renew_lease()`, `checkpoint_step()`, `schedule_retry()`, `request_cancel()`, `soft_delete_asset()`。

- [x] **Step 1: 写并发 claim 与重复 complete 测试。**
```python
async def test_only_one_worker_claims_job_and_complete_is_idempotent(repo):
    first, second = await asyncio.gather(repo.claim_due_job("w1", NOW), repo.claim_due_job("w2", NOW))
    assert [first, second].count(None) == 1
    assert (await repo.complete_upload("asset", "v1")).job_id == (await repo.complete_upload("asset", "v1")).job_id
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_repository.py -q`。Expected: FAIL。
- [x] **Step 3: 建 schema/migration 和原子 claim。** 使用 `PRAGMA journal_mode=WAL`、`BEGIN IMMEDIATE`；建立 `assets/upload_sessions/upload_chunks/jobs/job_steps/segments/schema_migrations`，对 `identifier`、`(session_id,chunk_number)`、`(asset_id,pipeline_version)` 加唯一索引；claim 用 `UPDATE ... WHERE status='queued' AND next_run_at<=? RETURNING *`。
- [x] **Step 4: 验证 repository。** Run: `pytest tests/unit/recorded_video/test_repository.py -q`。Expected: PASS，包含租约过期回收、heartbeat、checkpoint 持久化。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/repository.py tests/unit/recorded_video/test_repository.py && git commit -m "feat: persist recorded video jobs in sqlite"`。

### Task 4: 本地资产存储与安全回收（OpenSpec 1.4）

**Files:**
- Create: `src/vsa_agent/recorded_video/assets.py`, `tests/unit/recorded_video/test_assets.py`
- Modify: `src/vsa_agent/recorded_video/errors.py`, `src/vsa_agent/recorded_video/repository.py`, `tests/unit/recorded_video/test_models.py`, `tests/unit/recorded_video/test_repository.py`

**Interfaces:**
- Consumes: Task 2 的 `AssetStore` 协议。
- Produces: `LocalAssetStore.create_session()`, `write_chunk()`, `assemble_source()`, `write_atomic()`, `open_media_range()`, `free_bytes()`, `cleanup_expired_sessions()`；`JobRepository.list_expired_unreferenced_sessions(now)` 为回收提供真实、只读的“过期且无引用”候选证据。

- [x] **Step 1: 写路径穿越、重复 chunk、原子合并测试。**
```python
async def test_store_never_uses_user_filename_in_physical_path(store):
    await store.write_chunk("sid", 1, b"x", "../../evil.mkv")
    source = await store.assemble_source("sid", "asset-uuid", 1, "../../evil.mkv")
    assert source.is_relative_to(store.root / "assets" / "asset-uuid")
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_assets.py -q`。Expected: FAIL。
- [x] **Step 3: 实现 UUID 布局和 fsync/rename。** chunk 写到 `uploads/{session}/chunks/{number:06}.part.tmp` 后 `os.replace`；组合写 `source/original.{ext}.tmp`，每文件 `flush+os.fsync` 后 rename；仅删除 repository 判定过期且无引用的目录。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_assets.py tests/unit/recorded_video/test_repository.py -q`。Expected: PASS，含磁盘不足、unsafe filename、并发 source/原子写入以及仓储证明的过期无引用回收。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/assets.py tests/unit/recorded_video/test_assets.py && git commit -m "feat: add local recorded video asset store"`。

### Task 5: 三段式上传 API（OpenSpec 2.1、2.2）

**Files:**
- Create: `src/vsa_agent/api/recorded_video.py`, `tests/unit/api/test_recorded_video_upload.py`
- Modify: `src/vsa_agent/api/routes.py`, `src/vsa_agent/recorded_video/repository.py`, `tests/unit/recorded_video/test_repository.py`

**Interfaces:**
- Produces: `POST /api/v1/videos -> {url,asset_id,upload_session_id}`；`POST /api/v1/vst/v1/storage/file` 接收 multipart `mediaFile` 和 nvstreamer headers；repository 提供会话+资产读取、首次 identifier 原子绑定和已存字节读取，供 API 在写入前实施持久化配额检查。

- [x] **Step 1: 写名称预校验、累计大小和协议测试。**
```python
async def test_final_chunk_returns_same_sensor_and_stream_id(client):
    created = (await client.post("/api/v1/videos", json={"filename":"yard.mkv"})).json()
    response = await upload_one_chunk(client, created["url"], identifier="i", filename="yard.mkv")
    assert response.json()["sensorId"] == response.json()["streamId"] == created["asset_id"]

async def test_chunk_cumulative_size_limit_rejects_before_assembly(client, upload_url):
    response = await upload_chunk(client, upload_url, b"x" * 11, max_upload_bytes=10)
    assert response.status_code == 413
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/api/test_recorded_video_upload.py -q`。Expected: FAIL，404。
- [x] **Step 3: 实现输入契约。** `POST /videos` 请求体只有 `filename`，创建会话时只验证 basename、允许扩展和安全字符，绝不宣称可从该请求得知文件总大小；chunk handler 验证 `1 <= chunk <= total`、每块实际长度、identifier 一致性，并在写入前比较 `stored_bytes + incoming_bytes <= max_upload_bytes`。它调用 Task 3/4，重复同字节返回 200、同键不同摘要返回 409，最后块才返回 `sensorId/streamId/filePath/bytes/chunkCount`。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/api/test_recorded_video_upload.py -q`。Expected: PASS，含 400/409/413 与不发布半成品。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/api/recorded_video.py src/vsa_agent/api/routes.py tests/unit/api/test_recorded_video_upload.py && git commit -m "feat: accept original ui recorded video chunks"`。

### Task 6: 完成、状态、重试和取消 API（OpenSpec 2.3）

**Files:**
- Modify: `src/vsa_agent/api/recorded_video.py`, `src/vsa_agent/recorded_video/repository.py`, `src/vsa_agent/recorded_video/models.py`, `tests/unit/api/test_recorded_video_jobs.py`, `tests/unit/recorded_video/test_repository.py`, `tests/unit/recorded_video/test_models.py`

**Interfaces:**
- Produces: `POST /api/v1/videos/{asset_id}/complete -> {asset_id,job_id,status,status_url}`；`GET /api/v1/jobs/{job_id}`；`POST /api/v1/jobs/{job_id}/retry`；`POST /api/v1/jobs/{job_id}/cancel`；repository 提供持久任务读取和仅允许 `failed -> queued` 的原子重试入口。

- [x] **Step 1: 写 complete 幂等与可见状态测试。**
```python
async def test_repeated_complete_returns_same_job_and_status_url(client, ready_asset):
    one = await client.post(f"/api/v1/videos/{ready_asset}/complete", json={})
    two = await client.post(f"/api/v1/videos/{ready_asset}/complete", json={})
    assert one.json()["job_id"] == two.json()["job_id"]
    assert (await client.get(one.json()["status_url"])).json()["status"] == "queued"
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/api/test_recorded_video_jobs.py -q`。Expected: FAIL。
- [x] **Step 3: 实现 API。** complete 先确认所有 chunk/assemble 成功，再调用 repository 的唯一 `(asset_id,pipeline_version)` job 创建；状态仅返回安全 error 摘要、stage、attempt、timestamps；retry 只允许 failed，cancel 对 queued 立即生效、running 标记 `cancel_requested`。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/api/test_recorded_video_jobs.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/api/recorded_video.py tests/unit/api/test_recorded_video_jobs.py && git commit -m "feat: expose recorded video job lifecycle"`。

### Task 7: VST 列表、缩略图和媒体 facade（OpenSpec 2.4、2.5）

**Files:**
- Create: `src/vsa_agent/api/recorded_video_vst.py`, `tests/unit/api/test_recorded_video_vst.py`, `tests/unit/api/test_recorded_video_media.py`
- Modify: `src/vsa_agent/api/routes.py`, `src/vsa_agent/recorded_video/repository.py`, `src/vsa_agent/recorded_video/assets.py`, `tests/unit/recorded_video/test_repository.py`, `tests/unit/recorded_video/test_assets.py`

**Interfaces:**
- Produces: `/api/v1/vst/v1/replay/streams`、`/sensor/list`、`/storage/size`、`/storage/file/{asset}/url`、`/storage/file/{asset}`、`/replay/stream/{asset}/picture`。

- [x] **Step 1: 写 VST 响应和 Range 边界测试。**
```python
async def test_media_range_returns_206_and_rejects_unsatisfiable(client, ready_asset):
    ok = await client.get(f"/api/v1/vst/v1/storage/file/{ready_asset}", headers={"Range":"bytes=2-4"})
    assert (ok.status_code, ok.headers["content-range"], ok.content) == (206, "bytes 2-4/10", b"234")
    assert (await client.get(f"/api/v1/vst/v1/storage/file/{ready_asset}", headers={"Range":"bytes=20-"})).status_code == 416
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/api/test_recorded_video_vst.py tests/unit/api/test_recorded_video_media.py -q`。Expected: FAIL。
- [x] **Step 3: 实现 facade。** 仅列出 ready 资产；storage URL 生成同源带 `startTime/endTime` 的 URL；picture 返回该 segment thumbnail；媒体端点支持无 Range 的 200、单范围 206、`Accept-Ranges: bytes`、正确 `Content-Range`，资产不存在/软删返回 404。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/api/test_recorded_video_vst.py tests/unit/api/test_recorded_video_media.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/api/recorded_video_vst.py src/vsa_agent/api/routes.py tests/unit/api/test_recorded_video_vst.py tests/unit/api/test_recorded_video_media.py && git commit -m "feat: serve recorded video through vst facade"`。

### Task 8: 级联删除与恢复安全（OpenSpec 2.6、4.4）

**Files:**
- Modify: `src/vsa_agent/api/recorded_video.py`, `src/vsa_agent/recorded_video/repository.py`, `src/vsa_agent/recorded_video/assets.py`, `tests/unit/recorded_video/test_repository.py`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/videoDelete.ts`
- Create: `tests/unit/api/test_recorded_video_delete.py`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__/videoDelete.test.ts`

**Interfaces:**
- Consumes: Task 2 的 `SearchProjectionStore`、`AssetStore`、`JobRepository` 协议；不得引用具体 ES 类。
- Produces: `DELETE /api/v1/videos/{asset_id}`；`DeletionService.delete(asset_id, projection_store: SearchProjectionStore) -> DeleteResult`。

- [x] **Step 1: 写 running 删除、重试删除测试。**
```python
async def test_delete_requests_cancel_then_is_idempotent(client, running_asset):
    assert (await client.delete(f"/api/v1/videos/{running_asset}")).status_code == 202
    assert (await client.delete(f"/api/v1/videos/{running_asset}")).status_code in {202, 204}
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/api/test_recorded_video_delete.py -q`。Expected: FAIL。
- [x] **Step 3: 实现严格顺序。** `DeletionService` 仅调用注入的 `SearchProjectionStore.delete_asset(asset_id)`，而不导入 ES implementation；running 先写 cancel；safe point 后按 projection 删除、derived、source、upload 目录、SQLite soft-delete 处理，每步记录可重试 deletion step；对已删除资产返回 204，绝不按路径参数访问任意文件。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/api/test_recorded_video_delete.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/api/recorded_video.py src/vsa_agent/recorded_video/repository.py src/vsa_agent/recorded_video/assets.py tests/unit/api/test_recorded_video_delete.py tests/unit/recorded_video/test_repository.py frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/videoDelete.ts frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__/videoDelete.test.ts && git commit -m "feat: delete recorded video assets idempotently"`。

### Task 9: 固定时段 Segmenter（OpenSpec 3.2）

**Files:**
- Create: `src/vsa_agent/recorded_video/segmenter.py`, `tests/unit/recorded_video/test_segmenter.py`

**Interfaces:**
- Consumes: Task 2 的 `Segmenter` 协议。
- Produces: `FixedDurationSegmenter(Segmenter)`，其 `plan(asset, duration_ms) -> list[Segment]`。

- [x] **Step 1: 写边界分段和 ISO/offset 换算测试。**
```python
def test_fixed_duration_segmenter_emits_stable_last_partial_segment():
    segments = FixedDurationSegmenter(30).plan(asset("a", "2026-01-01T00:00:00Z"), 61_000)
    assert [(s.ordinal,s.start_offset_ms,s.end_offset_ms) for s in segments] == [(0,0,30000),(1,30000,60000),(2,60000,61000)]
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_segmenter.py -q`。Expected: FAIL。
- [x] **Step 3: 实现固定分段算法。** `FixedDurationSegmenter` 实现 Task 2 已定义的 `Segmenter` 协议；固定时段按毫秒左闭右开区间，时间显示使用 `timeline_origin + offset`，segment ID 调用 Task 2 的 `segment_id`，本任务不再修改协议文件。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_segmenter.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/segmenter.py tests/unit/recorded_video/test_segmenter.py && git commit -m "feat: add replaceable recorded video segmentation"`。

### Task 10: ffprobe、代表帧和浏览器 proxy（OpenSpec 3.3）

**Files:**
- Create: `src/vsa_agent/recorded_video/media.py`, `tests/unit/recorded_video/test_media.py`

**Interfaces:**
- Produces: `MediaProcessor.probe(path) -> MediaProbe`、`extract_representative_frames()`、`ensure_playback_proxy()`。

- [x] **Step 1: 写 subprocess 命令和坏媒体测试。**
```python
async def test_mkv_creates_proxy_and_corrupt_probe_is_permanent(fake_runner, processor):
    assert (await processor.ensure_playback_proxy(asset_mkv)).suffix == ".mp4"
    with pytest.raises(RecordedVideoError, match="CORRUPT_MEDIA"): await processor.probe(corrupt_path)
```
- [x] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_media.py -q`。Expected: FAIL。
- [x] **Step 3: 实现最小 processor。** `ffprobe -v error -show_format -show_streams -of json` 解析 duration/resolution/codecs；每 segment 均匀选 `representative_frames` offset；MP4 仅在浏览器可播时复用 source，否则 ffmpeg 写 `playback/proxy.mp4.tmp` 后原子发布；找不到二进制抛 `FFMPEG_MISSING`。
- [x] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_media.py -q`。Expected: PASS。
- [x] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/media.py tests/unit/recorded_video/test_media.py && git commit -m "feat: process recorded video media assets"`。

### Task 11: OpenAI-compatible Vision 与 Embedding provider（OpenSpec 3.4、3.5）

**Files:**
- Create: `src/vsa_agent/recorded_video/providers.py`, `tests/unit/recorded_video/test_providers.py`

**Interfaces:**
- Produces: `OpenAIVisionProvider.describe(frames, segment) -> VisionDescription`；`OpenAIEmbeddingProvider.embed(text) -> Embedding`。

- [ ] **Step 1: 写 429/5xx、结构错误和维度错误测试。**
```python
async def test_embedding_dimension_mismatch_is_permanent(httpserver, provider):
    httpserver.expect_request("/embeddings").respond_with_json({"data":[{"embedding":[0.1]}]})
    with pytest.raises(RecordedVideoError, match="EMBEDDING_DIMENSION"): await provider.embed("forklift", expected_dims=4)
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_providers.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现 provider。** 使用 `httpx.AsyncClient(timeout=...)`、provider `asyncio.Semaphore`；只接受 schema 验证后的 `{description, tags}` 和浮点非空向量；429/超时/网络/5xx 标为 retryable；日志只写 model、status、duration、asset/job/stage，不写 Authorization 或图片 payload。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_providers.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/providers.py tests/unit/recorded_video/test_providers.py && git commit -m "feat: add recorded video model providers"`。

### Task 12: Pipeline manifest、检查点与可重放处理（OpenSpec 3.6）

**Files:**
- Create: `src/vsa_agent/recorded_video/pipeline.py`, `tests/unit/recorded_video/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2 的 `AssetStore`、`JobRepository`、`VisionProvider`、`EmbeddingProvider`、`SearchProjectionStore` 协议，以及 Task 9/10 的实现。
- Produces: `RecordedVideoPipeline.run(job) -> PipelineResult`；`load_verified_checkpoint()`。

- [ ] **Step 1: 写 resume 不重复 provider 调用测试。**
```python
async def test_valid_analysis_checkpoint_skips_second_vision_call(pipeline, repo, vision):
    await pipeline.run(job); await pipeline.run(reclaimed_job)
    assert vision.describe.await_count == 1
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_pipeline.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现 stage 编排。** 每 stage 写 `derived/{pipeline_version}/manifest.json.tmp`，记录 provider model、prompt/segmenter version、输入/输出 SHA-256、UTC timestamps；核对 checksum 后复用 checkpoint；按 `probing/segmenting/extracting/analyzing/embedding/indexing/publish` 更新 `job_steps`，其中 `indexing` 生成并校验 ES 投影 manifest，`publish` 幂等 bulk upsert 后才把资产/任务置为可搜索终态；manifest 中排除密钥。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_pipeline.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/pipeline.py tests/unit/recorded_video/test_pipeline.py && git commit -m "feat: checkpoint recorded video processing pipeline"`。

### Task 13: Worker、并发槽位与重试（OpenSpec 4.1、4.2）

**Files:**
- Create: `src/vsa_agent/recorded_video/worker.py`, `scripts/recorded-video-worker.py`, `tests/unit/recorded_video/test_worker.py`

**Interfaces:**
- Produces: `RecordedVideoWorker.run()`、`run_once()`、`readiness()`；CLI `python scripts/recorded-video-worker.py --config PATH`。

- [ ] **Step 1: 写并发上限、heartbeat/backoff 测试。**
```python
async def test_worker_limits_parallel_jobs_and_schedules_30_120_600_backoff(worker, repo):
    await worker.run_until_idle()
    assert worker.max_observed_jobs <= 3
    assert await repo.retry_delays("job") == [30, 120, 600]
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_worker.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现 Worker。** 通过 `asyncio.Semaphore(worker_concurrency)` 调用 Task 3 原子 claim，后台每 `lease_sec//3` renew，失败以 attempt 选择 30/120/600 秒，超过 `max_attempts` 终态 failed；stdout 写 JSON heartbeat/readiness。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_worker.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/worker.py scripts/recorded-video-worker.py tests/unit/recorded_video/test_worker.py && git commit -m "feat: run recorded video jobs in worker"`。

### Task 14: 崩溃恢复、取消和临时产物回收（OpenSpec 4.3、4.4）

**Files:**
- Modify: `src/vsa_agent/recorded_video/worker.py`, `src/vsa_agent/recorded_video/pipeline.py`, `src/vsa_agent/recorded_video/repository.py`
- Create: `tests/unit/recorded_video/test_worker_recovery.py`

**Interfaces:**
- Produces: `recover_expired_jobs(now)`、`PipelineCancelled`、`cleanup_after_cancel()`。

- [ ] **Step 1: 写 lease 过期恢复和 safe-point cancel 测试。**
```python
async def test_reclaimed_job_uses_checkpoint_and_honors_cancel_before_embedding(worker, repo):
    await repo.expire_lease("job"); await repo.request_cancel("job")
    assert (await worker.run_once()).status is JobStatus.CANCELLED
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_worker_recovery.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现恢复规则。** Worker 启动先将过期 `running` 任务回收为 queued，再验证 manifest/checksum；每 stage 前后查询 cancel；取消时不 publish、不写 ES，回收未引用 `.tmp`/chunk，保留 source；显式 retry 从 failed 创建/复用同一 pipeline job。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_worker_recovery.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/worker.py src/vsa_agent/recorded_video/pipeline.py src/vsa_agent/recorded_video/repository.py tests/unit/recorded_video/test_worker_recovery.py && git commit -m "feat: recover and cancel recorded video work"`。

### Task 15: 版本化 ES mapping 与 alias readiness（OpenSpec 5.1）

**Files:**
- Create: `src/vsa_agent/recorded_video/es_index.py`, `tests/unit/recorded_video/test_es_index.py`

**Interfaces:**
- Produces: `RecordedVideoIndex.bootstrap(model, dims) -> str`、`validate_alias()`、`SegmentDocument`。

- [ ] **Step 1: 写 mapping/dimension 冲突测试。**
```python
async def test_existing_alias_with_wrong_vector_dimension_blocks_readiness(index, fake_es):
    fake_es.mapping_dims = 1536
    with pytest.raises(RecordedVideoError, match="EMBEDDING_DIMENSION"): await index.validate_alias(expected_dims=1024)
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_es_index.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现显式 mapping。** 索引名包含 model/version/dims；mapping 精确声明 keyword/text/date/long 和 `dense_vector(dims, similarity='cosine')`；创建后原子更新 alias；已有 alias 只校验，不动态猜测或修改 mapping。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_es_index.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/es_index.py tests/unit/recorded_video/test_es_index.py && git commit -m "feat: bootstrap recorded video search index"`。

### Task 16: ES 投影、生产查询与原版搜索契约（OpenSpec 5.2、5.3、5.4）

**Files:**
- Modify: `src/vsa_agent/recorded_video/es_index.py`, `src/vsa_agent/tools/embed_search.py`, `src/vsa_agent/api/video_search_ingest.py`, `tests/unit/api/test_original_ui_search_route.py`
- Create: `tests/unit/recorded_video/test_es_projection.py`, `tests/unit/tools/test_embed_search_production.py`

**Interfaces:**
- Produces: `project_segments(manifest) -> ProjectionResult`；生产 `embed_search` 的 controlled failure；`SearchResult` 使用 asset identity/timestamps/thumbnail。

- [ ] **Step 1: 写 bulk 部分失败与生产 fail-closed 测试。**
```python
async def test_production_embedding_failure_never_uses_mock(monkeypatch):
    monkeypatch.setattr("vsa_agent.tools.embed_search._embed_query", failing_embed)
    with pytest.raises(SearchDependencyError): await embed_search("forklift", production_config())
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/recorded_video/test_es_projection.py tests/unit/tools/test_embed_search_production.py tests/unit/api/test_original_ui_search_route.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现投影和读取。** manifest 生成 `SegmentDocument(id=segment_id)`，`async_bulk` 逐项处理 errors，成功可重放、部分失败保留 retryable job；只在 ES 完成后事务 publish asset/job；生产关闭 `allow_mock_fallback`/`force_mock_embedding`，测试 profile 明确允许；保留 `{data:[{video_name,description,start_time,end_time,sensor_id,screenshot_url,similarity}]}`。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/recorded_video/test_es_projection.py tests/unit/tools/test_embed_search_production.py tests/unit/api/test_original_ui_search_route.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add src/vsa_agent/recorded_video/es_index.py src/vsa_agent/tools/embed_search.py src/vsa_agent/api/video_search_ingest.py tests/unit/recorded_video/test_es_projection.py tests/unit/tools/test_embed_search_production.py tests/unit/api/test_original_ui_search_route.py && git commit -m "feat: index recorded video segments for production search"`。

### Task 17: 原版 UI 上传完成类型与任务轮询（OpenSpec 6.1、6.2）

**Files:**
- Modify: `frontend/original-ui/packages/common/lib-src/utils/videoUpload.ts`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/types.ts`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/VideoManagementComponent.tsx`
- Create: `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/jobStatus.ts`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__/jobStatus.test.ts`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__/components/VideoManagementComponent.jobs.test.tsx`

**Interfaces:**
- Produces: `CompletedUpload {asset_id,job_id,status,status_url}`；`pollRecordedVideoJob(statusUrl, signal): Promise<JobStatusResponse>`。

- [ ] **Step 1: 写 processing 到终态 UI 测试。**
```tsx
it('keeps upload in processing until the job is completed', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({status:'running'})).mockResolvedValueOnce(jsonResponse({status:'completed'}));
  renderComponent(); await uploadFixture();
  expect(await screen.findByText('Processing')).toBeInTheDocument();
  expect(await screen.findByText('Completed')).toBeInTheDocument();
});
```
- [ ] **Step 2: 验证失败。** Run: `npm --prefix frontend/original-ui test --workspace @nv-metropolis-bp-vss-ui/video-management -- --runInBand --testPathPatterns="jobStatus|VideoManagementComponent.jobs"`。Expected: FAIL。
- [ ] **Step 3: 实现最小 UI 状态。** complete helper 返回 body；轮询仅在 `queued/running/retry_wait` 继续，`failed` 展示服务端安全摘要并提供 retry，`cancelled` 显示取消；AbortSignal 停止轮询，保留已有 chunk headers、路径和上传进度。
- [ ] **Step 4: 验证通过。** Run: `npm --prefix frontend/original-ui test --workspace @nv-metropolis-bp-vss-ui/video-management -- --runInBand --testPathPatterns="jobStatus|VideoManagementComponent.jobs"`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add frontend/original-ui/packages/common/lib-src/utils/videoUpload.ts frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management && git commit -m "feat: show recorded video processing status in ui"`。

### Task 18: 同源流式代理与 UI 媒体验证（OpenSpec 6.3、6.4、7.5）

**Files:**
- Modify: `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/next.config.js`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/api.ts`
- Create: `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/pages/api/v1/[...path].ts`, `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/__tests__/api/proxy.test.ts`, `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__/utils/vstFacade.test.ts`

**Interfaces:**
- Produces: streaming `proxyApiRequest(req,res,targetBase)`；浏览器固定使用相对 `/api/v1` 与 `/api/v1/vst`。

- [ ] **Step 1: 写 multipart/Range 不缓冲测试。**
```ts
it('forwards Range and pipes the upstream body without json parsing', async () => {
  await proxyApiRequest(reqWith({range:'bytes=0-9'}), res, 'http://127.0.0.1:8000');
  expect(upstreamHeaders.range).toBe('bytes=0-9'); expect(res.statusCode).toBe(206);
});
```
- [ ] **Step 2: 验证失败。** Run: `npm --prefix frontend/original-ui test --workspace nv-metropolis-bp-vss-ui -- --runInBand --testPathPatterns="proxy" && npm --prefix frontend/original-ui test --workspace @nv-metropolis-bp-vss-ui/video-management -- --runInBand --testPathPatterns="vstFacade"`。Expected: FAIL。
- [ ] **Step 3: 实现 streaming proxy。** API route 禁用 body parser，透传 method、headers、request readable stream 和 upstream status/headers/body；保持 rewrite 仅作 GET/普通 API 回退，代理不读取完整 10 MB chunk/媒体；VST API endpoint 使用 `/api/v1/vst`。
- [ ] **Step 4: 验证通过。** Run: `npm --prefix frontend/original-ui test --workspace nv-metropolis-bp-vss-ui -- --runInBand --testPathPatterns="proxy" && npm --prefix frontend/original-ui test --workspace @nv-metropolis-bp-vss-ui/video-management -- --runInBand --testPathPatterns="vstFacade"`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add frontend/original-ui/apps/nv-metropolis-bp-vss-ui frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/lib-src/api.ts frontend/original-ui/packages/nv-metropolis-bp-vss-ui/video-management/__tests__ && git commit -m "feat: proxy recorded video ui requests same origin"`。

### Task 19: Runtime doctor 与安全启动前检查（OpenSpec 7.1）

**Files:**
- Create: `scripts/runtime-doctor.py`, `tests/unit/scripts/test_runtime_doctor.py`
- Modify: `scripts/es-runtime-stack.sh`, `scripts/es-runtime-stack.ps1`

**Interfaces:**
- Produces: `python scripts/runtime-doctor.py --config PATH --es-endpoint URL --json`；`DoctorResult(ok, checks)`。

- [ ] **Step 1: 写失败依赖和生产 mapping 测试。**
```python
def test_doctor_reports_ffmpeg_and_foreign_port_without_killing(monkeypatch):
    result = run_doctor(command_exists=lambda name: name != "ffmpeg", port_owner=lambda _: "other-user")
    assert {c.code for c in result.checks} >= {"FFMPEG_MISSING", "PORT_FOREIGN_OWNER"}
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/scripts/test_runtime_doctor.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现 doctor。** 检查 conda/Python 包、npm、Docker Compose、ffprobe/ffmpeg、data_root 创建写入/剩余空间、provider 配置、端口所有者、ES 连接/alias mapping；每项给出 component、code、remediation，禁止 subprocess sudo 和任何写生产索引。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/scripts/test_runtime_doctor.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add scripts/runtime-doctor.py tests/unit/scripts/test_runtime_doctor.py scripts/es-runtime-stack.sh scripts/es-runtime-stack.ps1 && git commit -m "feat: add recorded video runtime doctor"`。

### Task 20: 单脚本 Worker 生命周期、run-id 日志与显式验证（OpenSpec 7.2、7.3、7.4）

**Files:**
- Modify: `scripts/es-runtime-stack.sh`, `scripts/es-runtime-stack.ps1`, `tests/unit/scripts/test_es_runtime_stack_script.py`
- Create: `tests/unit/scripts/test_recorded_video_runtime_launcher.py`

**Interfaces:**
- Produces: `--data-root PATH`、`--validate`；`.runtime/es-stack/runs/{run_id}/{stack,api,worker,ui,es}.log` 和 `processes.json`。

- [ ] **Step 1: 写脚本文本/行为测试。**
```python
def test_launcher_starts_worker_and_default_mode_does_not_run_ingest_smoke():
    text = BASH_SCRIPT.read_text(); assert "recorded-video-worker.py" in text
    assert "--validate" in text and "es_ingest_smoke.py" not in normal_start_block(text)
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py -q`。Expected: FAIL。
- [ ] **Step 3: 实现 run lifecycle。** 先 doctor/ES alias/API health/Worker readiness/UI proxy；生成 UUID run directory 和 latest 指针；`[stack]/[api]/[worker]/[ui]/[es]` 聚合行，进程 manifest 写 PID/command/start；终止仅当前用户进程；默认不调用 smoke，`--validate` 使用 `validation-{run_id}` alias 并 finally 删除。
- [ ] **Step 4: 验证通过。** Run: `pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_recorded_video_runtime_launcher.py -q`。Expected: PASS。
- [ ] **Step 5: 提交。** Run: `git add scripts/es-runtime-stack.sh scripts/es-runtime-stack.ps1 tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_recorded_video_runtime_launcher.py && git commit -m "feat: run recorded video stack with worker logs"`。

### Task 21: 后端集成与故障注入（OpenSpec 8.1、8.2、8.3）

**Files:**
- Create: `tests/integration/conftest.py`, `tests/integration/test_recorded_video_flow.py`, `tests/integration/test_recorded_video_failures.py`

**Interfaces:**
- Consumes: Task 5-16 的 API、Worker、端口和 ES alias。
- Produces: `recorded_video_stack` fixture，提供 `upload_and_complete()`、`wait_completed()`、`es_ids()`、`kill_worker()`。

- [ ] **Step 1: 写真实 ES 三并发视频测试。**
```python
async def test_three_uploads_create_exactly_one_document_per_segment(stack):
    jobs = await asyncio.gather(*(stack.upload_and_complete(name) for name in ("a.mp4","b.mp4","c.mkv")))
    await stack.wait_completed(jobs); assert await stack.es_ids() == await stack.expected_segment_ids()
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/integration/test_recorded_video_flow.py tests/integration/test_recorded_video_failures.py -q`。Expected: FAIL，fixture 与临时运行时不存在。
- [ ] **Step 3: 实现可控集成夹具。** 测试启动临时 SQLite/目录、真实 Docker ES 和本地 `pytest-httpserver` OpenAI-compatible 服务；通过显式环境变量启用测试 fallback，不访问外网。
- [ ] **Step 4: 补全确定性故障用例。** 分别注入重复 chunk/complete、provider 429/5xx、ES bulk 部分失败、Worker kill/lease reclaim、磁盘不足、坏媒体、取消和删除中断；每个用例断言 job 状态、attempt、ES 文档数和残留文件。
- [ ] **Step 5: 验证与提交。** Run: `pytest tests/integration/test_recorded_video_flow.py tests/integration/test_recorded_video_failures.py -q`。Expected: PASS。Run: `git add tests/integration && git commit -m "test: cover recorded video integration failures"`。

### Task 22: 原版 UI Playwright 端到端验收（OpenSpec 8.4）

**Files:**
- Create: `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/playwright.config.ts`, `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts`, `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/fixtures.ts`
- Modify: `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/package.json`, `frontend/original-ui/package-lock.json`

**Interfaces:**
- Consumes: Task 18 的同源 UI 代理和 Task 21 的可控运行时。
- Produces: Playwright `runtimeBaseUrl` fixture；浏览器验收的 `upload -> processing -> completed -> search -> thumbnail -> 206` 证据。

- [ ] **Step 1: 写 MP4/MKV UI 行为测试。**
```ts
test('uploads, indexes and plays a recorded-video segment', async ({ page, request }, testInfo) => {
  const media = await createRecordedVideoFixtures(testInfo.outputDir);
  await page.goto('/');
  await page.setInputFiles('input[type=file]', media.mp4);
  await expect(page.getByText('Completed')).toBeVisible();
  await page.getByPlaceholder('Search').fill('forklift');
  await expect(page.locator('img').first()).toBeVisible();
  const range = await request.get(await page.locator('video').getAttribute('src') as string, {
    headers: { Range: 'bytes=0-9' },
  });
  expect(range.status()).toBe(206);
});
```
- [ ] **Step 2: 验证失败。** 在 app devDependencies 添加 `@playwright/test` 和 `test:e2e` script 后，Run: `npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts`。Expected: FAIL，运行 fixture 或页面状态尚不存在。
- [ ] **Step 3: 实现 Playwright 配置与 fixture。** `webServer.command` 使用 Task 20 的隔离 `--validate` 配置启动 UI/API/Worker/ES；`fixtures.ts` 通过已由 doctor 验证的 ffmpeg 在 `testInfo.outputDir` 生成短 MP4/MKV，不提交二进制；测试分别上传两种容器，并覆盖 processing、failed/cancelled、retry、thumbnail、VST URL 和 Range 206。
- [ ] **Step 4: 验证通过。** Run: `npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts`。Expected: PASS，Playwright trace 在失败时保留。
- [ ] **Step 5: 提交。** Run: `git add frontend/original-ui/apps/nv-metropolis-bp-vss-ui frontend/original-ui/package-lock.json && git commit -m "test: verify recorded video original ui flow"`。

### Task 23: 中文运行文档、验证脚本与服务器同步清单（OpenSpec 9.1、9.3）

**Files:**
- Create: `scripts/recorded-video-validate.py`, `docs/recorded-video-runtime.md`, `docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md`, `tests/unit/scripts/test_recorded_video_validate.py`
- Modify: `docs/DEVELOPMENT_STATUS.md`, `scripts/sync-server-files.ps1`

**Interfaces:**
- Produces: `python scripts/recorded-video-validate.py --api-url URL --ui-url URL --report PATH`，失败返回非零；报告字段为 `runtime/job_stages/provider/es/search/media/delete`。

- [ ] **Step 1: 写验证脚本失败传播测试。**
```python
def test_validation_script_returns_nonzero_when_media_range_is_not_206(tmp_path):
    result = run_validator(fake_api(status=200), report=tmp_path / 'report.md')
    assert result.exit_code == 1
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/unit/scripts/test_recorded_video_validate.py -q`。Expected: FAIL，验证器不存在。
- [ ] **Step 3: 实现验证器。** 顺序检查无密钥配置摘要、组件 readiness、job stage history、provider/ES outcomes、search asset/segment identity、Range 206 和删除 cleanup；任一依赖/质量断言失败即写失败报告并返回 1，不允许跳过。
- [ ] **Step 4: 编写中文运行与同步文档。** 文档给出 Ubuntu 单脚本、唯一 SSH UI 隧道、日志路径、故障诊断、`--validate` 和无 sudo 前提；同步清单逐项列出新增 API/领域/脚本/前端/测试/文档。
- [ ] **Step 5: 验证与提交。** Run: `pytest tests/unit/scripts/test_recorded_video_validate.py -q`。Expected: PASS。Run: `git add scripts/recorded-video-validate.py scripts/sync-server-files.ps1 docs tests/unit/scripts/test_recorded_video_validate.py && git commit -m "docs: document recorded video runtime validation"`。

### Task 24: 全量质量门与 Ubuntu 真实模型验收证据（OpenSpec 8.5、9.2、9.4）

**Files:**
- Create: `tests/acceptance/test_recorded_video_validation_report.py`
- Modify: `openspec/changes/production-recorded-video-ingest/tasks.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md`

**Interfaces:**
- Consumes: Task 21-23 的自动化测试、验证器和同步清单。
- Produces: 通过的本地质量记录、Ubuntu 真实模型三并发/重启证据和已勾选 OpenSpec 任务。

- [ ] **Step 1: 先写质量门完整性测试。**
```python
def test_validation_report_records_all_required_server_evidence():
    report = Path('docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md').read_text()
    assert all(label in report for label in ('三并发', 'Worker 重启', 'HTTP 206', '删除清理', '无密钥'))
```
- [ ] **Step 2: 验证失败。** Run: `pytest tests/acceptance/test_recorded_video_validation_report.py -q`。Expected: FAIL，真实服务器证据尚未写入。
- [ ] **Step 3: 执行本地质量门。**
```bash
pytest -q
npm --prefix frontend/original-ui test --workspace nv-metropolis-bp-vss-ui -- --runInBand
npm --prefix frontend/original-ui test --workspace @nv-metropolis-bp-vss-ui/video-management -- --runInBand
npm --prefix frontend/original-ui run lint --workspace nv-metropolis-bp-vss-ui
npm --prefix frontend/original-ui run typecheck --workspace nv-metropolis-bp-vss-ui
npx openspec validate production-recorded-video-ingest --strict
```
Expected: 全部 PASS；本 change 引入的失败或非条件 skip 必须在此任务修复。
- [ ] **Step 4: 执行批准的 Ubuntu 验收。** 用 `scripts/sync-server-files.ps1` 同步，再运行 `./scripts/es-runtime-stack.sh --data-root /data/project/lyk/vsa-data --validate --conda-env vsa-agent`；以真实 OpenAI-compatible 配置提交三个视频，处理中重启 Worker，验证搜索、thumbnail、206、删除与无密钥日志。
- [ ] **Step 5: 记录证据、勾选任务并提交。** Run: `pytest tests/acceptance/test_recorded_video_validation_report.py -q`。Expected: PASS。Run: `git add openspec/changes/production-recorded-video-ingest/tasks.md docs/DEVELOPMENT_STATUS.md docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md tests/acceptance/test_recorded_video_validation_report.py && git commit -m "test: accept recorded video production runtime"`。

## OpenSpec 覆盖自检

| OpenSpec 任务 | 计划任务 |
|---|---|
| 1.1-1.4 | 1-4 |
| 2.1-2.6 | 5-8 |
| 3.1-3.6 | 9-12 |
| 4.1-4.4 | 13-14 |
| 5.1-5.4 | 15-16 |
| 6.1-6.4 | 17-18 |
| 7.1-7.5 | 18-20 |
| 8.1-8.3 | 21 |
| 8.4 | 22 |
| 8.5 | 24 |
| 9.1、9.3 | 23 |
| 9.2、9.4 | 24 |

自检结果：42/42 项均有实现与验证任务；接口名称在生产者任务中定义后才被后续任务消费；验收已拆为后端、UI、文档和服务器四个独立 gate；未包含禁止的占位符、泛化错误处理或跨任务省略引用。实际工作区隔离、执行方式、TDD 和审查模式由 Comet 的 `build_pause: plan-ready` 决策门处理。
