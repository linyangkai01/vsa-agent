# 真实业务视频回归运行手册

本文说明如何在无管理员权限的 Ubuntu 服务器上，使用 manifest schema v2、dataset `1.1.0` 的固定真实叉车、人员协同和 PPE 视频验证录播上传、Worker、真实 Provider、Elasticsearch、原版 UI 搜索、媒体播放和选中片段 Chat。

视频二进制只保存在服务器 `.runtime/business-video-baseline/`，不得提交 Git。来源、许可、归属、媒体规格、源文件和派生片段 SHA-256 固定在 `tests/fixtures/business_video_baseline/manifest.yaml`。

## 1. 前置条件

- 项目位于 `/data/project/lyk/vsa-agent`，代码通过 Git 与 `master` 同步。
- Conda 环境为 `vsa-agent`。
- Elasticsearch Docker 容器可以由当前用户启动，不需要 `sudo`。
- 真实 Provider 密钥保存在 `~/.config/vsa-agent/secrets.env`，权限为 `600`；不要把密钥放入命令行、日志或报告。
- 三个源视频已放入 `.runtime/business-video-baseline/sources/`。准备器也支持按 manifest 下载，但服务器网络较慢时优先使用已传入缓存。
- `.deps/node-env.sh` 应存在并由当前用户读取；若不存在，先在仓库根目录运行 `bash scripts/bootstrap_node.sh`。原版 UI 依赖应通过 `bash scripts/install_original_ui_deps.sh` 安装，不引入项目外的前端依赖。
- 服务器若缺少 Chromium 系统库，使用已经存在的 `mcr.microsoft.com/playwright:v1.61.1-noble` 镜像运行 browser server，不安装系统包。镜像版本必须与仓库锁定的 `playwright-core 1.61.1` 一致。
- Playwright test runner 在宿主用户下运行，输出必须显式写入 `.runtime/playwright/<run-id>`。不要复用默认 `test-results`，该目录可能由旧容器以 root 身份创建而不可写。

## 2. 固定数据复核

```bash
cd /data/project/lyk/vsa-agent

export PATH="/home/ykh/.conda/envs/vsa-agent/bin:/usr/local/dev/anaconda3/bin:$PATH"

conda run --no-capture-output -n vsa-agent python \
  scripts/prepare-business-video-baseline.py \
  --manifest tests/fixtures/business_video_baseline/manifest.yaml \
  --data-root .runtime/business-video-baseline \
  --no-download \
  --ffmpeg /home/ykh/.conda/envs/vsa-agent/bin/ffmpeg \
  --ffprobe /home/ykh/.conda/envs/vsa-agent/bin/ffprobe
```

该命令会严格加载 manifest schema v2 / dataset `1.1.0`，重新校验三个源文件的大小、媒体规格和 SHA-256，复核或生成六个固定片段，并写出 `resolved-manifest.yaml`。任何哈希漂移都必须停止，不能自动接受新哈希。

准备器的下载总 deadline 默认为 30 分钟，每次 ffprobe 或 FFmpeg 调用的 deadline 默认为 10 分钟。下载只写同目录临时文件，完成身份校验后原子替换；媒体工具超时会终止其进程组，未完成的派生片段会删除。`--no-download` 模式缺少源文件时直接失败，不会访问网络。

schema v2 将 required concepts 写成带 `negated_alternatives` 的概念组，并将 forbidden conclusions 写成带稳定 `group_id` 的概念组。正向词与其否定词出现在同一 clause 时不得算作 required 命中。原 `ppe-compliant` 场景已经更名为 `ppe-respiratory-controls`，只验证画面中可见的呼吸防护与粉尘控制设备，不推断整体 PPE 合规。

## 3. 启动隔离生产栈

在第一个终端执行：

```bash
cd /data/project/lyk/vsa-agent

export PATH="/home/ykh/.conda/envs/vsa-agent/bin:/usr/local/dev/anaconda3/bin:$PATH"
stamp="$(date -u +%Y%m%d-%H%M%S)"
export VSA_BUSINESS_STAMP="$stamp"
printf '%s\n' "$stamp" > .runtime/business-video-baseline/acceptance-stamp

./scripts/es-runtime-stack.sh \
  --api-port 8000 \
  --es-port 9200 \
  --ui-port 3000 \
  --index "vsa-business-video-${stamp}" \
  --data-root "/data/project/lyk/vsa-validation-data/business-video-${stamp}" \
  --conda-env vsa-agent \
  --config config.yaml \
  --secrets-file "$HOME/.config/vsa-agent/secrets.env"
```

保持该终端运行。启动日志位于 `.runtime/es-stack/latest/`。不要使用长期生产 data-root 运行确定性验收，避免历史任务和本次基线相互干扰。

记录本次 `stamp`、隔离 data-root、Elasticsearch index、stack run directory 和 Git commit，并把同一个 `VSA_BUSINESS_STAMP` 值带到后续终端。启动完成后可查看不含密钥的运行证据：

```bash
curl -fsS http://127.0.0.1:8000/api/v1/runtime/evidence
```

后续 runner 和真实 Playwright 都会再次执行该硬门禁。在上传任何视频前，证据必须同时满足：

- `recorded_video_enabled=true`、`real_provider_ready=true`；
- `llm`、`vlm`、`embedding` 三个角色均存在，`backend/provider/model` 非空且 `is_mock=false`；
- 需要密钥的角色满足 `api_key_configured=true`；
- `allow_mock_fallback=false`、`force_mock_embedding=false`；
- `config_fingerprint` 是稳定的 64 位 SHA-256，但响应和报告中不包含密钥值。

任一条件不满足均为 `pipeline_error`，必须在首个资产创建前停止，不能把 mock 或 fallback 结果记为真实业务准确性证据。

## 4. 运行结构化业务门禁

在第二个终端先运行快速层：

```bash
cd /data/project/lyk/vsa-agent

export VSA_BUSINESS_STAMP="$(cat .runtime/business-video-baseline/acceptance-stamp)"

conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --manifest tests/fixtures/business_video_baseline/manifest.yaml \
  --data-root .runtime/business-video-baseline \
  --profile quick \
  --run-id "quick-v110-${VSA_BUSINESS_STAMP}" \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000
```

快速层六个片段均通过后，再执行发布层和完整视频层：

```bash
conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --manifest tests/fixtures/business_video_baseline/manifest.yaml \
  --data-root .runtime/business-video-baseline \
  --profile release \
  --run-id "release-v110-${VSA_BUSINESS_STAMP}" \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000

conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --manifest tests/fixtures/business_video_baseline/manifest.yaml \
  --data-root .runtime/business-video-baseline \
  --profile full \
  --run-id "full-v110-${VSA_BUSINESS_STAMP}" \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000
```

输出位于：

```text
.runtime/business-video-regression/<run-id>/
  runner.log
  report.json
  junit.xml
  cases/<case-id>/<attempt>.json
```

报告顶层保存 redacted `provider_evidence`，每次成功 Chat 保存相同 `config_fingerprint`。搜索结果必须同时匹配本次运行的 `asset_id`、`job_id` 和 `segment_id`；仅文件名、相似内容或历史资产命中都不能通过。缩略图必须是非空同源响应，媒体必须返回合法 HTTP 206 单字节 Range。

每次 Chat 成功响应必须携带由 API 生成并经原版 UI proxy 透传的 `X-VSA-Trace-ID`。runner 随后访问 `/api/v1/runtime/chat-traces/<trace-id>/evidence`，要求 conversation/message/asset/segment 与当前 attempt 完全一致，且 trace 同时包含 `original_ui.chat.request`、`top_agent.tool.call`、`video_understanding.result`、`top_agent.tool.result` 和 `top_agent.final`。实际 `video_understanding.result` 和非空 final 都必须恰好一次，不能存在 error 事件。模型若重复发起工具调用，额外调用的参数必须与首次完全相同，并逐一对应 `top_agent.tool.cached_result`；任何第二次实际视频理解、不同参数调用或无缓存对应的重复调用都为 `pipeline_error`。端点只返回脱敏字段和安全的 Provider request ID，不返回提示词、回答正文、路径或密钥。

退出码：`0` 通过，`2` 数据集或参数错误，`3` 流水线/Provider/基础设施错误，`4` 业务准确性失败，`5` 清理失败。搜索、缩略图、媒体和 runtime-evidence 的瞬时 HTTP 重试记录在当前 attempt 中，不会增加 Provider attempt 数。每个 Provider attempt 的选中片段 Chat 固定只发送一次，不使用 HTTP 重试；Chat 超时、非 200、空回答或错误回答立即成为 `pipeline_error`，防止一次 attempt 实际消耗多次模型输出。

资产在 create 返回 `asset_id` 时立即登记为清理候选，不等待 complete 或 Job 成功。因此 upload/complete/Job/搜索/媒体/Chat 任一阶段失败仍会进入删除流程。`report.json` 分别保留 `primary_failure` 和 `cleanup_failures`；若清理也失败，最终退出码为 `5`，但原始失败不会丢失。JUnit 会把主失败和清理失败分别写成可定位的 testcase。

## 5. 原版 UI 真实叉车验收

栈保持运行时，在第二个终端执行。Node 和 test runner 在宿主运行；官方容器只运行 Chromium browser server。仓库在容器中只读挂载，测试产物写入宿主当前用户拥有的独立目录：

```bash
cd /data/project/lyk/vsa-agent
set -Eeuo pipefail

export VSA_BUSINESS_STAMP="$(cat .runtime/business-video-baseline/acceptance-stamp)"
test -f .deps/node-env.sh || bash scripts/bootstrap_node.sh
. .deps/node-env.sh
test -x frontend/original-ui/node_modules/.bin/playwright || \
  bash scripts/install_original_ui_deps.sh

image='mcr.microsoft.com/playwright:v1.61.1-noble'
container="vsa-playwright-${VSA_BUSINESS_STAMP}"
run_id="ui-v110-${VSA_BUSINESS_STAMP}"
output_dir="$PWD/.runtime/playwright/${run_id}"

docker image inspect "$image" >/dev/null
test ! -e "$output_dir"
mkdir -p "$output_dir"
test -w "$output_dir"

docker run -d --rm --init --network host --ipc=host \
  --name "$container" \
  -v "$PWD:/work:ro" \
  -w /work/frontend/original-ui \
  "$image" \
  npx playwright run-server --port 9323 --host 127.0.0.1
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT INT TERM

cd frontend/original-ui

RUNTIME_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_LIVE_PROVIDER=1 \
PLAYWRIGHT_REAL_VIDEO=/data/project/lyk/vsa-agent/.runtime/business-video-baseline/clips/forklift-person-proximity.mp4 \
PLAYWRIGHT_REAL_QUERY='forklift operating close to a pedestrian' \
PLAYWRIGHT_CHAT_TRACE_ROOT=/data/project/lyk/vsa-agent/.runtime/es-stack/latest/chat-traces \
PW_TEST_CONNECT_WS_ENDPOINT=ws://127.0.0.1:9323/ \
npx playwright test \
  --config apps/nv-metropolis-bp-vss-ui/playwright.config.ts \
  --project chromium \
  --output "$output_dir" \
  --grep 'validates a real forklift business video through the original UI'
```

不要使用 `sudo` 启动容器或宿主 test runner。`docker image inspect` 失败时说明已批准镜像不在本机；不要在正式验收中静默换版本。`output_dir` 必须是不存在的新目录，失败后重跑应使用新 run-id，不能覆盖旧证据。shell 的 trap 会在测试成功、失败或中断时删除 browser-server 容器。

该用例显式启用时才运行。默认 Playwright 仍使用合成 fixture，不会调用真实 Provider。真实用例在上传前执行 runtime-evidence 硬门禁，然后完成上传、Job publish、精确资产搜索、缩略图、HTTP 206 Range 播放、`+ Chat`、响应头精确 trace 关联、clause-level 概念门禁和资产删除。删除最终返回 204 后，媒体 Range 必须为 404/410，搜索必须不再返回该 asset。页面 console error、page error、非媒体网络失败、HTTP 5xx 和无法由任一成功 200/206 解释的媒体 abort 必须全部为空。

测试无论成功或失败都会在 `finally` 中删除已获得 `asset_id` 的视频，并释放页面诊断监听器。测试进程被强制杀死时无法保证 `finally` 运行，因此最终审计仍必须独立确认资产、媒体、ES 文档、容器、端口和进程无残留。Playwright trace、截图和其他失败证据只允许写入本次 `$output_dir`；旧 `test-results` 不属于本次验收证据。

## 6. 失败排查

按以下顺序查看证据：

```bash
cd /data/project/lyk/vsa-agent
export VSA_BUSINESS_STAMP="$(cat .runtime/business-video-baseline/acceptance-stamp)"

for profile in quick release full; do
  run_dir=".runtime/business-video-regression/${profile}-v110-${VSA_BUSINESS_STAMP}"
  cat "$run_dir/report.json"
  cat "$run_dir/runner.log"
  cat "$run_dir/junit.xml"
  find "$run_dir/cases" -name '*.json' -print
done

tail -n 200 .runtime/es-stack/latest/api.log
tail -n 200 .runtime/es-stack/latest/worker.log
tail -n 200 .runtime/es-stack/latest/ui.log
```

先查看 `primary_failure.category` 区分数据集、流水线和准确性问题，再检查 `cleanup_failures`。最终 `failure_category=cleanup_error` 可能表示主流程失败后清理又失败，不能只看最终分类而忽略原始故障。runtime evidence 不 ready、Chat 单次调用失败、精确 asset/job/segment 身份不一致、deadline 超时、哈希漂移、禁止结论和清理失败都必须保留原报告；不要用重新运行覆盖或掩盖第一次失败证据。

## 7. 最终审计与清理

dataset `1.1.0` 的 quick、release、full 和 UI 都完成后，按以下清单逐项审计。任何一项缺失都不能归档为 PASS：

1. 记录服务器 Git commit、manifest `schema_version=2`、dataset `version=1.1.0`、manifest 路径、三个源文件和六个片段的 SHA-256；`resolved-manifest.yaml` 必须与仓库 manifest 一致。
2. 记录隔离 stack run directory、data-root、ES index/alias、API/UI 地址和 redacted `config_fingerprint`。三种 profile 的报告必须引用同一 commit、dataset `1.1.0` 和同一真实 Provider 配置。
3. 三份 `report.json` 均须保持当前 report `schema_version=1`，并满足 `status=passed`、`failure_category=null`、`primary_failure=null`、`cleanup_failures=[]`；对应 JUnit 必须 `failures=0`、`errors=0`、`skipped=0`。
4. 六个 case 逐项检查 `asset_id`、`job_id`、matched `segment_id`、Top-5 rank、时间窗口、缩略图和 Range。quick/full 各一次通过；release 每 case 三次真实 Chat，至少 2/3 达到覆盖率，三个 attempt 均无 forbidden group。
5. 每份报告的 `provider_evidence` 必须 `real_provider_ready=true`，三种 role 均非 mock，两个 search mock 控制均为 false。每次成功 Chat 的 `config_fingerprint` 必须与顶层一致；不得出现第二次 Chat HTTP 调用来挽救同一 attempt。
6. `ppe-respiratory-controls` 必须命中人员、呼吸防护和粉尘控制设备，并且不出现 `no_respiratory_protection` 或 `no_dust_control`；不得再使用旧 `ppe-compliant` 名称或“整体 PPE 完全合规”结论。
7. UI 结果必须来自 `.runtime/playwright/ui-v110-<stamp>`，测试未跳过。上传 asset 与搜索 asset 相同，Chat context 的 asset/job/segment 精确一致，trace 含 `original_ui.chat.request`、`top_agent.tool.call`、`video_understanding.result`、`top_agent.tool.result`、唯一非空 `top_agent.final`，且页面/网络/5xx 诊断为空。
8. 三种 profile 和 UI 创建的资产均完成删除，删除后媒体返回 404/410；refresh 后隔离 ES namespace 文档数为 `0`，SQLite 不存在对应 orphan job/step。
9. 停止隔离栈并确认 API/UI/Worker、browser-server 容器、测试端口和 validation index 均无残留。保留本次 stack logs、runner JSON/JUnit/attempt、Playwright output 和 chat traces；不得归档密钥或把 `.runtime` 视频提交 Git。

最终归档必须明确写出四个 `1.1.0` run-id 及其结果。旧 dataset 的 quick/release/full/UI 只能作为历史排障参考，不能补齐当前版本的任何门禁。
