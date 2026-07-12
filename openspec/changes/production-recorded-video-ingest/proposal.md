## Why

当前录播视频链路只能通过预制 metadata 和 deterministic mock embedding 验证 Elasticsearch 与原版 UI 搜索契约，尚未覆盖真实视频上传、持久化、自动分析、真实向量入库和片段播放。下一阶段需要在不恢复 NVIDIA VST、RTVI、Cosmos 等专有运行依赖的前提下，建立可在无管理员权限的单机服务器上运行并可逐步演进的真实业务闭环。

## What Changes

- 兼容原版 UI 的三段式分块上传和必要的 VST 读取接口，以本地文件存储替代 NVIDIA VST。
- 增加 SQLite WAL 持久任务仓储和独立 Worker，支持异步分析、租约、心跳、重试、取消及服务重启恢复。
- 增加可替换的录播处理流水线：媒体探测、固定时间分段、代表帧提取、OpenAI-compatible VLM 描述、真实 embedding 和 Elasticsearch 批量索引。
- 增加稳定的资产、上传会话、任务、阶段检查点和视频片段数据模型，并提供缩略图、HTTP Range 媒体访问和时间段播放。
- 将生产检索改为显式索引 mapping 和 fail-closed 真实 embedding；mock embedding 仅保留在测试或显式 smoke profile。
- 扩展单脚本启动能力，同时管理 Elasticsearch、API、Worker 和原版 UI，提供启动 doctor、同源代理、按运行分组的完整日志及非破坏性的验证模式。
- 增加覆盖上传幂等、故障恢复、并发处理、ES 一致性、删除清理和原版 UI 端到端业务流的验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `recorded-video-business-flow`: 将现有录播搜索验证扩展为真实视频上传、持久异步处理、真实语义索引、原版 UI 搜索与时间段播放的准生产单机闭环。

## Impact

- 后端：`src/vsa_agent/api/`、录播处理与存储模块、配置模型、搜索 embedding 和 Elasticsearch 索引生命周期。
- 前端：原版 UI 上传完成响应和任务状态轮询的最小兼容调整，以及同源 API/VST facade 配置。
- 运行脚本：`scripts/es-runtime-stack.sh`、运行 doctor、Worker 生命周期、日志布局和验证模式。
- 数据：新增可配置的视频数据根目录和 SQLite 数据库；Elasticsearch 继续保存视频片段检索文档，不保存视频字节。
- 依赖：使用项目已有 Python/FastAPI/OpenCV/Elasticsearch/OpenAI-compatible 体系；ffprobe/ffmpeg 作为核心媒体运行依赖；不引入 Redis、Celery、MinIO、Kafka、MDX、VST 或 RTVI。
