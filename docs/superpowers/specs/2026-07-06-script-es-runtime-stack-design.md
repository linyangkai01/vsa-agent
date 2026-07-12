---
comet_change: script-es-runtime-stack
role: technical-design
canonical_spec: openspec
---

# ES 运行时全栈与原版前端验证设计

## 背景

项目已有用于视频片段检索验证的 ES 运行时基础能力：

- `docker-compose.es.yml` 定义单节点开发用 Elasticsearch 服务。
- `scripts/es-dev-start.ps1`、`scripts/es-dev-probe.ps1` 和
  `scripts/es-dev-stop.ps1` 直接管理 Elasticsearch。
- `scripts/es_ingest_smoke.py` 在 API 与 ES 都可访问时，验证写入与检索。
- `vsa_agent.api.routes:app` 已提供 `/health` 并注册 `/api/search/ingest`。

现有运行脚本只覆盖 ES、FastAPI 和自动化 smoke 验证。它没有启动原版
VSS 前端，且后端没有实现前端已经调用的 `/api/v1/search` 契约。因此浏览器
输入无法证明真实业务流确实经过 Elasticsearch。

本变更将这些步骤收敛为一条可重复的全栈路径，可在本地或映射的服务器项目
`Z:\vsa-agent` 中运行：启动 ES、API 与原版 UI，预写入一条可检索的样例记录，
再从前端搜索框输入查询确认结果。

## 目标

- 提供一键启动 ES、FastAPI 与原版 UI 的交互式脚本。
- 保持提交的 `config.yaml` 安全，默认仍为 `search.enabled: false`。
- 生成临时运行配置，并只向本次 API 子进程传入 `VSA_CONFIG`。
- 让原版 VSS Search UI 的请求经 `/api/v1/search` 进入项目后端。
- 复用已有 `SearchAgent`、`SearchInput` 和注册的 `embed_search` 工具，使启用
  搜索时由工具查询 Elasticsearch，而不是新增平行检索实现。
- 在快速验证时强制 ingest 与查询使用同一确定性 mock embedding；生产配置仍默认
  使用已配置的真实 embedding。
- 启动后等待 ES、API 和 UI 就绪，运行一次 ingest smoke 以建立浏览器可查的
  样例记录。
- 服务就绪后保持运行，直到用户按 `Ctrl+C`。
- 输出 UI、API、ES、索引地址和可核验的日志位置。
- 仅处理用户明确指定的 ES、API、UI 端口占用，不影响其他端口进程。

## 非目标

- 不实现 NVIDIA 原版的 Kafka、Logstash、VST 或 MDX 服务。
- 不将视频字节写入 Elasticsearch。
- 不改变提交的默认 `config.yaml`，也不管理生产 ES 集群。
- 不要求普通单元测试启动 Docker、Elasticsearch、浏览器或真实模型服务。
- 不新增专供验证使用的前端页面、前端 ES 客户端或重复的搜索算法。

## 方案

### 全栈启动器

保留 `scripts/es-runtime-stack.ps1` 与对应 Linux 脚本为统一入口，并在其上增加
交互模式。PowerShell/Bash 负责进程生命周期；Python 保持负责 API 业务与
ingest/search smoke 验证。

交互模式按下列顺序运行：

1. 由脚本位置解析仓库根目录。
2. 检查选定的 ES、API 与 UI 端口。
3. 若端口被占用，记录端口、PID 和进程命令行，结束占用进程并轮询端口释放。
4. 端口无法释放则立即失败，不启动任何新的部分服务。
5. 通过现有 `scripts/es-dev-start.ps1` 启动或复用开发 ES。
6. 在 `.runtime/es-stack/config.yaml` 写入搜索已启用的临时配置。
7. 以 `VSA_CONFIG` 指向临时配置的方式启动
   `uvicorn vsa_agent.api.routes:app`，并等待 `/health` 返回成功。
8. 运行 `scripts/es_ingest_smoke.py`，将已知视频检索记录写入 ES 并验证可检索。
9. 设置原版 UI 所需的运行环境，启动 UI 并等待其 HTTP 服务可访问。
10. 输出浏览器地址、API 地址、ES 地址、索引名和日志路径，然后保持前台运行。

用户按 `Ctrl+C` 后，脚本只停止本次启动的 API 与 UI 子进程；ES 是否停止沿用
显式 `-StopElasticsearch` 选项。脚本不会恢复启动前因占用目标端口而被终止的
旧进程。

### 原版前端搜索业务流

原版 VSS Search 组件已经固定使用如下请求：

```text
POST ${NEXT_PUBLIC_AGENT_API_URL_BASE}/search
```

请求包含 `query`、`top_k`、`source_type`、可选时间/视频源过滤条件以及
`agent_mode`；它要求响应为：

```json
{ "data": ["SearchResult", "..."] }
```

实际响应中的数组元素仍是已有的 `SearchResult` 字段，例如 `video_name`、
`description`、`start_time`、`end_time`、`sensor_id`、`similarity`、
`screenshot_url` 和 `object_ids`。

后端新增 `/api/v1/search` 路由，将该请求适配给已有 `SearchInput` 并调用
`execute_search_agent`。该代理继续从工具注册表取 `embed_search`；当临时配置
启用搜索时，`embed_search` 使用 Elasticsearch。路由将工具结果封装回
`{ "data": [...] }`，由原版结果列表直接渲染。

这条链路为：

```text
VSS Search 输入
  -> POST /api/v1/search
  -> SearchAgent
  -> 已注册 embed_search
  -> Elasticsearch
  -> { data: [...] }
  -> 原版视频搜索结果列表
```

快速验证临时配置额外设置 `search.force_mock_embedding: true`。该标志使
`embed_search` 跳过真实 embedding 客户端，始终生成与 smoke 写入记录一致的
确定性 4 维向量。此标志默认关闭，不改变生产或真实模型验证的行为。

API 日志需要记录搜索请求与 `search_agent.embed_search` 执行事件。两者和前端
结果共同构成“浏览器输入确实经过 ES”的验证证据。

## 临时运行配置

临时配置从已提交的 `config.yaml` 复制后，仅修改搜索段，避免复制或破坏模型、
工具、服务与 profile 设置：

```yaml
search:
  enabled: true
  es_endpoint: http://127.0.0.1:9200
  embed_index: vsa-video-embeddings
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: true
  force_mock_embedding: true
```

## 命令与参数

交互式启动默认使用：

```powershell
.\scripts\es-runtime-stack.ps1 `
  -ApiPort 8000 `
  -EsPort 9200 `
  -UiPort 3000 `
  -Index vsa-video-embeddings `
  -CondaEnv vsa-agent
```

- `ApiPort`：默认 `8000`。
- `EsPort`：默认 `9200`。
- `UiPort`：默认 `3000`。
- `Index`：默认 `vsa-video-embeddings`。
- `CondaEnv`：默认空；提供后通过 `conda run -n <env>` 启动 Python/Uvicorn。
- `StopElasticsearch`：默认 `false`；仅在退出时显式停止 ES。
- 非交互 smoke 模式保留给 CI 或无浏览器环境，并在验证完成后按现有语义清理。

## 错误处理与端口接管

脚本对缺少 Docker Compose、ES 无法就绪、Python/Uvicorn 不可用、API/UI 早退和
smoke 失败输出明确错误，不得报告成功。

端口接管的边界如下：

- 只检查并结束选定的 `EsPort`、`ApiPort` 和 `UiPort` 的占用进程。
- 结束前必须记录 PID、命令行及其目标端口。
- 结束后等待端口确认释放；超过限定时间仍未释放即失败。
- 不扫描、不结束其他端口的进程。
- 正常退出或异常退出时，只清理本次脚本自身启动的 API/UI 进程。

## 测试与验收

普通单元测试不启动 Docker 或浏览器，覆盖以下边界：

- `/api/v1/search` 的原版请求与 `{data: [...]}` 响应契约。
- 路由到 `SearchAgent` 和注册 `embed_search` 的调用路径。
- 端口发现、停止命令构造、端口释放等待和失败信息。
- UI 启动命令与 `NEXT_PUBLIC_AGENT_API_URL_BASE`、Search tab 环境变量。
- 既有 `tests/unit/scripts/test_es_ingest_smoke.py` 的 ingest/search 保障。

服务器实测时，启动器完成 smoke 后在浏览器打开 UI，输入与样例记录匹配的查询。
验收同时要求：结果列表有对应视频记录；API 日志有搜索请求和
`search_agent.embed_search` 事件；ES 索引中仍可查询到该记录。

## 服务端同步

本地验证通过后，将修改的脚本、API、测试、文档与 OpenSpec 文件同步到
`Z:\vsa-agent`。映射盘只用于同步；真实运行验证仍在服务器侧具备 Docker、
Python、Node 及项目依赖的终端中执行。若依赖缺失，记录确切阻塞原因，不将其
误报为验证通过。

## 风险与缓解

- Docker 或容器运行环境不可用：启动前检查并报告阻塞项。
- 目标端口属于无关服务：只接管用户明确选择的三类端口，并完整记录证据。
- API/UI 在运行期退出：就绪检查和子进程状态检查会立即返回失败。
- 临时配置与提交配置混淆：只写入 `.runtime/es-stack/`，仅对子进程设置
  `VSA_CONFIG`。
- ES 调用未被人工确认：前端结果、API 搜索日志、工具事件与 ES 文档四者共同
  提供可追溯证据。
