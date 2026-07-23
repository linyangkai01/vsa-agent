# 录播视频生产运行手册

本文面向批准的 Ubuntu 单机环境。生产栈只监听 `127.0.0.1`，由一个脚本管理 Elasticsearch、FastAPI、录播 Worker 和原版 UI；不要求 `sudo`，也不会终止其他用户拥有的端口监听进程。

## 1. 运行前提

当前用户需要能够直接执行以下命令：

```bash
conda --version
docker compose version
ffprobe -version
ffmpeg -version
node --version
npm --version
```

如果 Docker 只能通过 `sudo docker` 使用，应先由服务器管理员把当前账号加入批准的 Docker 运行方式；启动脚本不会尝试提权。数据目录必须由当前用户可写，并为上传源文件、代理视频、缩略图、SQLite WAL 和模型中间结果预留足够空间。

生产 profile 的 VLM 与 embedding 必须是真实 OpenAI-compatible provider。密钥只通过配置中 `api_key_env` 指定的环境变量注入。Ubuntu 启动器默认安全读取 `~/.config/vsa-agent/secrets.env`；文件只允许当前用户访问，只接受 `*_API_KEY=VALUE`，不会作为 shell 脚本执行。首次创建时使用：

```bash
install -d -m 700 "$HOME/.config/vsa-agent"
read -rsp 'DASHSCOPE_API_KEY: ' key && printf '\n'
umask 077
printf 'DASHSCOPE_API_KEY=%s\n' "$key" > "$HOME/.config/vsa-agent/secrets.env"
unset key
chmod 600 "$HOME/.config/vsa-agent/secrets.env"
```

可用 `--secrets-file /absolute/private/path.env` 或 `VSA_SECRETS_FILE` 覆盖默认路径。不要把密钥写入仓库 `config.yaml`、临时 YAML、验证报告、manifest 或日志。`search.allow_mock_fallback` 和 `search.force_mock_embedding` 在生产录播 profile 中必须为 `false`。`recorded_video.provider_concurrency` 默认是 1，用于限制真实模型请求并发；它与 Worker 的上传/任务并发独立。

## 2. 启动前真实 Provider 探针

在启动完整栈或重跑最终生产验收前，用同一个启动脚本执行一次显式探针：

```bash
./scripts/es-runtime-stack.sh \
  --config config.yaml \
  --conda-env vsa-agent \
  --probe-providers
```

探针按顺序向 active profile 的 embedding `/embeddings` 和 VLM `/chat/completions` 发送最小非业务请求，然后立即退出。它会读取与生产启动相同的私密密钥文件，但不会安装整套运行栈依赖，不会启动或停止 Docker、Elasticsearch、API、Worker、UI，不会回收端口、创建数据目录、索引或录播任务。普通启动未传 `--probe-providers` 时不会调用外部模型，也不会产生额外模型费用。

每个 role 输出一条脱敏结果，只包含 outcome、HTTP status、耗时、provider/model/host、安全过滤后的错误码和 request ID。不会输出密钥、Authorization、完整响应正文、提示词、assistant 内容或 embedding。退出码契约如下：

| 退出码 | 含义 | 处理 |
| --- | --- | --- |
| `0` | VLM 与 embedding 均可用 | 继续启动栈或执行最终生产验收 |
| `2` | 配置、密钥或探针依赖不完整 | 修复 active profile、配置路径、私密文件或 Python 环境 |
| `3` | 认证失败或供应商额度不可用 | 核对账号访问；`AllocationQuota.*` 需要恢复额度 |
| `4` | 限流、超时、网络或供应商 5xx | 检查网络并在暂态问题恢复后重试 |
| `5` | HTTP 契约或响应结构不兼容 | 核对 base URL、模型和 OpenAI-compatible 接口 |

当前已知 DashScope 状态是 embedding `ok`、VLM `quota`，因此额度恢复前预期整体退出 `3`。探针通过只证明两个模型接口可调用，不能替代第 6 节的三视频原版 UI 最终生产验收。

## 3. Ubuntu 单命令启动

在仓库根目录运行：

```bash
./scripts/es-runtime-stack.sh \
  --api-port 8000 \
  --es-port 9200 \
  --ui-port 3000 \
  --index vsa-recorded-video-production \
  --data-root /data/project/lyk/vsa-data \
  --conda-env vsa-agent
```

脚本依次执行私密配置加载、静态 doctor、Elasticsearch 启动、版本化生产索引幂等 bootstrap、只读 mapping readiness、API readiness、Worker heartbeat readiness、UI readiness 和同源代理检查。首次启动会按配置的 embedding 模型与维度创建显式 mapping 并绑定唯一 write alias；后续启动只验证同一契约。已有 alias、mapping 或实体索引冲突时脚本 fail-closed，不删除或动态改写现有数据。任一必需依赖失败时命令返回非零，并打印本次 run 的日志路径。正常启动不会调用写入型 ingest smoke，也不会向生产 alias 写入验证视频。

Worker 日志中的 `stage` 是最后完成的 checkpoint，`active_stage` 才是失败发生的当前阶段；provider 失败还会记录安全的 `error_detail`，只包含 HTTP 状态、有限字符集错误码和请求 ID。DashScope `AllocationQuota.*` 会明确分类为 `MODEL_QUOTA`，不会被误报成媒体或普通配置错误。

停止时在前台终端按 `Ctrl-C`。脚本只回收本次 run 记录的进程；`--stop-elasticsearch` 也只会停止由本次 run 启动的 Elasticsearch。

## 4. 唯一的 SSH UI 隧道

在客户端只转发 UI 端口：

```bash
ssh -N -L 3000:127.0.0.1:3000 <user>@10.157.68.44
```

浏览器访问 `http://127.0.0.1:3000`。上传、任务状态、搜索、缩略图和 Range 媒体请求全部经 Next 同源 `/api/v1` 与 `/api/v1/vst` 代理转发。不要再开放或转发 API `8000`、Elasticsearch `9200`；浏览器也不应直连这两个端口。

## 5. run ID、日志与进程 manifest

每次启动都会生成 UUID `run_id`：

```text
.runtime/es-stack/runs/{run_id}/
├── stack.log
├── api.log
├── worker.log
├── ui.log
├── es.log
├── processes.json
└── config.yaml
```

`.runtime/es-stack/latest` 指向最近一次 run。`processes.json` 记录受管组件的 PID、安全命令摘要、启动时间和最终退出状态。终端聚合行使用 `[stack]`、`[api]`、`[worker]`、`[ui]`、`[es]` 前缀。

排查单个业务流时，优先用 `run_id` 找到 run 目录，再按 `asset_id`、`job_id`、`stage` 和 `attempt` 搜索 API/Worker 日志。日志脱敏是防线，不是记录密钥的许可；发现 Authorization、API key、视频字节或完整模型图像请求时，应立即把该次验收判为失败。

## 6. normal 与 `--validate`

### normal 模式

第 2 节命令用于持续交互运行。它只做非写入 readiness，业务视频由原版 UI 上传，并写入配置的生产 alias 与数据根目录。

搜索结果卡片上的 `+ Chat` 会把 `asset_id`、`segment_id`、`job_id` 和时间范围作为原版 Chat context 发送。API 不接受浏览器提供的本地文件路径，而是用 `asset_id` 从 SQLite 读取 ready 资产，再由受控资产目录解析源文件；`segment_id` 必须属于该资产，问答只分析该片段的相对时间范围。相关日志事件为 `original_ui.chat.context.resolved`、`original_ui.chat.request`、`top_agent.tool.call` 和 `video_understanding.result`。

### 隔离 `--validate` 模式

下面命令创建 `validation-{run_id}` 索引和 run 内独立数据目录，执行隔离 readiness/smoke 后退出；成功、失败或中断都会清理临时配置、隔离数据和验证索引：

```bash
./scripts/es-runtime-stack.sh \
  --api-port 8000 \
  --es-port 9200 \
  --ui-port 3000 \
  --index vsa-recorded-video-production \
  --data-root /data/project/lyk/vsa-data \
  --conda-env vsa-agent \
  --validate
```

它用于证明启动器的隔离与清理契约，不替代真实录播语义验收。

### 真实录播链路验证器

#### 最终生产恢复验收（推荐 gate）

下面的一条命令自行启动完整栈两次，不需要预先运行 normal 栈。三个 `--video` 必须是存在、可读、内容 SHA-256 不同的真实 MP4/MKV；`--query` 可传一次供三个视频共用，也可按视频顺序传三次。生产 profile 必须关闭 mock fallback 和 mock embedding。

```bash
conda run --no-capture-output -n vsa-agent python scripts/recorded-video-production-acceptance.py \
  --video /data/project/lyk/validation/forklift-worker.mp4 \
  --video /data/project/lyk/validation/worker-fall.mp4 \
  --video /data/project/lyk/validation/smoke-event.mkv \
  --query 'forklift near worker' \
  --query 'worker falls to the ground' \
  --query 'visible smoke event' \
  --config config.yaml \
  --index vsa-recorded-video-production \
  --data-root /data/project/lyk/vsa-data \
  --conda-env vsa-agent \
  --api-port 8000 \
  --es-port 9200 \
  --ui-port 3000 \
  --report docs/recorded-video-validation.md
```

执行顺序固定为：第一次完整栈 readiness → 三并发原版分块上传 → 捕获持久化 checkpoint → 校验 manifest/UID/cmdline/run 路径后只向本次 Worker supervisor 发送 TERM → 第一次 launcher 完整退出 → 使用相同端口、索引和数据根目录启动第二次栈 → 至少一个 job 的 `attempt` 增加并完成 publish → 校验七阶段 checkpoint、真实 provider identity、ES 文档 → 通过原版 UI 同源代理执行三次搜索、缩略图、Range 播放和选中片段理解问答 → 幂等删除三资产 → 回收第二次 launcher → 扫描日志并原子写报告。

证据位于：

```text
.runtime/production-acceptance/{acceptance_id}/
├── acceptance.log
├── launcher-1.log
├── launcher-2.log
└── state.json

.runtime/es-stack/runs/{run_id}/
├── stack.log
├── api.log
├── worker.log
├── ui.log
├── processes.json
└── chat-traces/{request}/
    ├── request.json
    ├── trace.jsonl
    └── tool-results/

docs/recorded-video-validation.md
docs/recorded-video-validation.cases.json
```

只有报告同时包含两个不同 launcher run、`concurrency: 3`、`worker_restart: PASS`、三个唯一 asset/job、ES/SQLite segment 一致、三个 HTTP 206、三个 `video_understanding.result` trace 和三资产删除结果时，才允许写 `总体结果：PASS`。任一步失败都写 FAIL 报告并返回非零；运行栈仍可用时会尝试删除本次资产，无法安全清理的残留保留在数据根目录供排查，不会杀死未验证归属的进程。

#### 单资产快速诊断

保持 normal 栈在第一个服务器终端运行，在第二个服务器终端执行：

```bash
conda run --no-capture-output -n vsa-agent python scripts/recorded-video-validate.py \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000 \
  --config .runtime/es-stack/latest/config.yaml \
  --data-root /data/project/lyk/vsa-data \
  --video /data/project/lyk/validation/forklift-worker.mp4 \
  --query 'forklift near worker' \
  --minimum-similarity 0.20 \
  --report docs/recorded-video-validation.md
```

单资产验证器按 `runtime → job_stages → provider → es → search → media → delete` 执行，适合快速定位 provider、索引或媒体问题；它不证明三并发、Worker 中断恢复或选中片段问答，因此不能替代上面的最终 gate：

1. 检查 API、UI、同源代理，并从本次 run 的 active config 读取 profile、provider model/base host、ES endpoint/index 和 mock 开关；报告不读取或记录 key 值，且生产验收要求 mock 关闭。
2. 上传样例并等待任务完成，从同一数据根目录的 SQLite 读取完整阶段 checkpoint。
3. 验证 VLM/embedding 模型标识以及 indexing/publish checksum，并对 active ES endpoint/index 执行 refresh 与 asset/job identity 查询。
4. 要求语义搜索命中相同 video/asset/sensor/segment identity，时间为带时区 ISO 且 `start < end`，缩略图非空，单字节 Range 返回 HTTP 206。
5. 删除验证资产；refresh 后按 `asset_id` 直接确认 ES 无残留，按保存的 `job_id` 确认 SQLite 无 orphan steps，并确认媒体不可访问。

任何依赖或质量断言失败都会写出 `FAIL` 报告并返回 `1`；后续被阻断字段也明确记为失败，不会静默跳过。已创建资产无论主流程成功或失败都会进入清理尝试。`--video`、`--query`、`--data-root` 也可分别由 `VSA_VALIDATION_VIDEO`、`VSA_VALIDATION_QUERY`、`VSA_RECORDED_VIDEO_DATA_ROOT` 提供。

#### 无 sudo 的 Chromium E2E

服务器缺少 Chromium 系统库且不能使用管理员权限时，可以让宿主机继续运行 ES、API、Worker 和 UI，只把浏览器放进官方 Playwright 容器。该方式不修改项目依赖。镜像版本必须与 `@playwright/test` 一致：

```bash
cd /data/project/lyk/vsa-agent
docker image inspect mcr.microsoft.com/playwright:v1.61.1-noble >/dev/null

docker run -d --rm --init --network host --ipc=host \
  --name vsa-playwright-server \
  -v "$PWD:/work:ro" \
  -w /work/frontend/original-ui \
  mcr.microsoft.com/playwright:v1.61.1-noble \
  npx playwright run-server --port 9323 --host 127.0.0.1

PATH="$HOME/.conda/envs/vsa-agent/bin:/usr/local/dev/anaconda3/bin:/usr/bin:/bin"
export PATH
. .deps/node-env.sh
cd frontend/original-ui

PLAYWRIGHT_UI_PORT=3400 \
PLAYWRIGHT_API_PORT=8400 \
PLAYWRIGHT_CONDA_ENV=vsa-agent \
PW_TEST_CONNECT_WS_ENDPOINT=ws://127.0.0.1:9323/ \
npx playwright test \
  --config apps/nv-metropolis-bp-vss-ui/playwright.config.ts \
  --project chromium

docker rm -f vsa-playwright-server >/dev/null 2>&1 || true
```

Playwright 对栈 launcher 使用 15 秒 `SIGTERM` 优雅关闭窗口。成功后应在 `stack.log` 看到 `removed isolated validation namespace`，并确认测试端口 `3400/8400`、validation 进程和 `validation-*` 索引均无残留。

## 7. 故障诊断

| 现象 | 首查证据 | 处理方向 |
|---|---|---|
| doctor 在启动前失败 | `stack.log` 的首个错误码 | 补齐 conda/npm/Docker/ffmpeg，修正目录权限、磁盘、provider 环境变量或端口占用；不要用 sudo 绕过 |
| Elasticsearch readiness 失败 | `stack.log`、`es.log` | 核对 alias、显式 mapping 和 embedding dims；脚本不会动态改写不兼容索引 |
| API 未 ready | `api.log`、`processes.json` | 查看配置校验、SQLite 路径和 Python 依赖；确认 PID 是否已退出 |
| Worker heartbeat 失败 | `worker.log`、`processes.json` | 核对生产 composition、ffmpeg/ffprobe、provider 和数据目录写权限 |
| UI 或同源代理失败 | `ui.log`、`api.log` | 核对 npm 安装、UI 端口，以及相对 `/api/v1`、`/api/v1/vst` 配置 |
| 任务停在 retry_wait | `worker.log` 中的 job/stage/active_stage/attempt | 区分 provider 429/5xx/超时与永久媒体错误，等待退避或修复后显式重试；`MODEL_QUOTA` 需要恢复供应商额度 |
| 搜索没有目标资产 | 验证报告的 `provider`、`es`、`search` | 先确认 publish checkpoint，再查 query embedding、alias 和相似度阈值；禁止 mock fallback |
| 媒体不是 206 | 报告 `media`、API 日志 | 检查同一 asset 的 ready 状态、Range 转发及 `Content-Range`，不要让代理缓冲完整视频 |
| 删除未完成 | 报告 `delete`、Worker/API 日志 | 检查 running job 是否先取消，以及 ES、派生文件、源文件、SQLite 的可重试步骤 |

## 8. 服务器同步清单

服务器同步只使用显式文件白名单，不递归复制仓库：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1 -PreflightOnly
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1
```

`scripts/sync-server-files.ps1` 的 `IncludePaths` 逐项覆盖：

- API 与配置：录播 upload/job/delete、VST facade、原版 UI search、路由注册、生产配置。
- 领域与 Worker：asset store、SQLite repository、模型、ports、segmenter、media、providers、pipeline、ES projection、composition、Worker。
- 运行脚本：Bash/PowerShell 单入口、doctor、Worker CLI、验证器、日志泵和已有 ES smoke。
- 前端：Next 同源代理、公共上传/任务工具、Chat 状态轮询、Video Management 上传/任务/删除及其测试。
- Python 测试：录播 API、领域、Worker、ES、runtime/validator 脚本测试。
- 文档：本手册、开发状态和验收报告；不再同步技能工作流元数据。

脚本会拒绝绝对路径和逃逸目标根目录的相对路径，只创建白名单文件所需的父目录并覆盖对应文件；不要使用 `robocopy /E` 或其他全盘递归同步替代它。
