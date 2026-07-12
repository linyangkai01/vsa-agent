## Context

项目已经完成原版 Search UI、FastAPI、SearchAgent 和 Elasticsearch 的快速验证，但数据来自预制 metadata 和 deterministic mock embedding。原版录播业务依赖 VST 分块上传、完成回调、RTVI/Cosmos 分析与 VST 媒体读取；本项目的目标是移除这些 NVIDIA 必需依赖，而不是重新部署或完整复刻它们。

目标运行环境是一台无管理员权限的 Ubuntu 服务器：Docker Compose 可用于 Elasticsearch，Python 通过 conda 运行，浏览器通过 SSH 隧道访问。第一阶段要求准生产单机能力，支持 2-5 个并发任务、最大约 10 GB 的 MP4/MKV、持久任务状态和服务重启恢复。

## Goals / Non-Goals

**Goals:**

- 从原版 UI 上传真实视频并完成本地持久化、自动分析、真实 embedding、ES 入库、搜索、缩略图和时间段播放。
- 保留原版 UI 的三段式 nvstreamer 上传契约和搜索契约，只做异步任务状态所需的最小前端调整。
- 使用独立 Worker 和 SQLite WAL 建立可恢复、可重试、幂等的单机任务执行边界。
- 从第一阶段定义可替换的 AssetStore、JobRepository、Segmenter、VisionProvider 和 EmbeddingProvider 接口。
- 保持单脚本启动、完整分组件日志、无 sudo、默认仅监听 loopback，并允许浏览器只转发 UI 一个端口。

**Non-Goals:**

- RTSP 实时流、告警、Kafka/MDX、多租户、多节点和横向扩展。
- 引入或完整复刻 NVIDIA VST、RTVI、Cosmos/NIM 等运行服务。
- 第一阶段同时实现 MinIO/S3、Redis/Celery、本地模型或场景检测分段。
- 把 Elasticsearch 作为视频字节、任务状态或不可重建业务数据的事实源。

## Decisions

### 1. 采用独立 Worker + SQLite WAL，而不是 API 内后台任务或 Redis/Celery

API 只处理上传、状态、资产、媒体和搜索短请求；Worker 领取持久任务并执行耗时流水线。SQLite 使用 WAL、原子领取、租约和心跳，满足当前单机 2-5 并发和重启恢复。相比 FastAPI 内后台任务，它提供更好的故障隔离；相比 Redis/Celery，它不增加当前阶段无收益的常驻服务。JobRepository 接口允许后续替换。

### 2. 通过兼容 facade 保留原版 UI 契约

后端实现 `POST /api/v1/videos`、nvstreamer 分块接收、`POST /api/v1/videos/{sensorId}/complete`、任务状态 API，以及原版 UI 实际使用的 VST 读取子集。`sensorId` 和 `streamId` 都映射稳定 `asset_id`。完成回调返回 202、job ID 和状态 URL；原版 UI 仅增加轮询终态的最小逻辑。

### 3. 本地文件保存资产，SQLite 保存业务真相，ES 保存检索投影

用户文件名只作为展示信息，所有物理路径由 UUID asset ID 派生。上传块先写临时目录，完整文件通过原子 rename 发布。SQLite 保存资产、上传会话、任务、阶段检查点和片段 metadata；派生 manifest 保存可重建 ES 的描述和向量产物；ES 每个 segment 一份文档，不保存视频字节。

### 4. 采用可替换的固定时间 Segmenter

第一阶段按配置的固定时长产生片段并抽取代表帧。Segmenter 只输出稳定的片段计划，不负责模型调用或索引。未来场景检测或事件算法只需实现同一接口，不改变上传、Worker、存储、搜索和播放主链路。

### 5. VLM 与 embedding 分别使用 OpenAI-compatible provider

两个 provider 分别配置 base URL、model、密钥环境变量、超时和并发限制。每次任务保存不含密钥的配置快照、prompt/pipeline 版本和模型标识。生产 profile 中模型失败或向量维度不符必须明确失败；deterministic mock 仅用于测试或显式 smoke profile。

### 6. 使用显式版本化 ES mapping 和确定性文档 ID

索引 bootstrap 显式创建 keyword/date/long/text/dense_vector mapping，向量维度和模型绑定索引版本并通过 alias 暴露。启动只校验已有 mapping，不偷偷修改。文档 ID 由 asset ID、pipeline version 和 segment index 决定，使重试覆盖同一文档且不会产生重复记录。

### 7. 使用绝对时间兼容原版 UI，使用 offset 驱动媒体定位

上传参数中存在合法采集时间时作为 timeline origin，否则使用上传完成时间 UTC。片段同时保存 ISO start/end 和毫秒 offset。媒体 facade 将原版 UI 的绝对时间转换为 offset，返回支持 HTTP Range 的同源 URL；不适合浏览器播放的 MKV/编码生成 MP4 proxy。

### 8. 保留一个用户入口脚本，但把业务逻辑留在 Python 模块

继续使用 `scripts/es-runtime-stack.sh` 作为唯一启动命令，管理 ES、API、Worker、UI、信号和日志。脚本在启动前运行 doctor，检查依赖、端口、目录权限、磁盘、模型配置和 ES mapping。默认启动只做非写入 readiness；`--validate` 使用隔离索引并自动清理，不污染生产索引。

### 9. 通过 UI 同源代理适配 SSH 隧道

浏览器只访问 UI 的相对 `/api/v1` 路径，Next 代理以流式方式转发上传 chunk、Range 媒体和普通请求到 loopback API。服务器默认只绑定 127.0.0.1，客户端只需转发 UI 端口，不暴露 API 或 ES。

### 10. 以相关 ID 和分运行目录提供诊断证据

每次启动建立独立 run 目录，保存 stack、API、Worker、UI、ES 日志和进程清单，`latest` 指向最近运行。日志包含 request ID、asset ID、job ID、stage、attempt 和外部调用耗时，但不记录密钥、Authorization 或视频内容。

## Risks / Trade-offs

- [SQLite 限制多节点扩展] → 将 JobRepository 定义为端口；当前明确单机，后续迁移 PostgreSQL/队列。
- [本地文件限制横向 Worker] → 将 AssetStore 定义为端口并使用稳定 asset key；后续切换 S3/MinIO。
- [OpenAI-compatible 服务对视频输入格式支持不一致] → VisionProvider 只接收已抽取的代表帧和结构化 prompt，并在 doctor/验证中检查模型能力。
- [长视频产生大量模型调用和成本] → 固定片段时长、帧数、Worker 并发和 provider 并发均可配置；阶段检查点避免重试重复调用。
- [浏览器不能直接播放部分 MKV/编码] → 媒体探测后按需生成 MP4 proxy；保留原文件用于重处理。
- [VST facade 范围持续膨胀] → 只实现原版录播上传、列表、缩略图和播放实际调用的子集；RTSP/告警接口明确不在本 change。
- [ES bulk 成功而 SQLite 提交失败] → 使用确定性文档 ID，恢复时重复写入并对账；失败任务可安全清理本次文档。
- [端口被其他用户进程占用] → 只终止当前用户拥有的监听进程；无权限时明确失败，不尝试 sudo。

## Migration Plan

1. 新增数据根目录、SQLite schema 和配置，保持现有 smoke API 与主索引不变。
2. 实现上传/资产/VST facade 和本地存储，先用假 provider 完成 API 合约测试。
3. 实现 Worker、固定 Segmenter、真实 provider、manifest 和 ES 版本化索引。
4. 扩展原版 UI 完成回调和任务轮询，接入缩略图与媒体 facade。
5. 将启动脚本升级为 ES/API/Worker/UI 单入口，并将默认 smoke 改为非写入 readiness。
6. 在本地通过单元、集成和故障测试后，同步到服务器，以真实 MP4/MKV 和真实 OpenAI-compatible 服务执行端到端验证。

回滚时停止 Worker/API/UI，恢复上一版代码和索引 alias；新视频数据目录和 SQLite 保留，不自动删除。旧 smoke 搜索链路在迁移期间继续可用。

## Open Questions

无阻塞性问题。具体默认 segment 时长、代表帧数、并发数和日志保留天数在实施计划中以保守默认值确定，并保持可配置。
