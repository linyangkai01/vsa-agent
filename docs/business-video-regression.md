# 真实业务视频回归运行手册

本文说明如何在无管理员权限的 Ubuntu 服务器上，使用固定的真实叉车、人员协同和 PPE 视频验证录播上传、Worker、真实 Provider、Elasticsearch、原版 UI 搜索、媒体播放和选中片段 Chat。

视频二进制只保存在服务器 `.runtime/business-video-baseline/`，不得提交 Git。来源、许可、归属、媒体规格、源文件和派生片段 SHA-256 固定在 `tests/fixtures/business_video_baseline/manifest.yaml`。

## 1. 前置条件

- 项目位于 `/data/project/lyk/vsa-agent`，代码通过 Git 与 `master` 同步。
- Conda 环境为 `vsa-agent`。
- Elasticsearch Docker 容器可以由当前用户启动，不需要 `sudo`。
- 真实 Provider 密钥保存在 `~/.config/vsa-agent/secrets.env`，权限为 `600`；不要把密钥放入命令行、日志或报告。
- 三个源视频已放入 `.runtime/business-video-baseline/sources/`。准备器也支持按 manifest 下载，但服务器网络较慢时优先使用已传入缓存。

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

该命令会重新校验三个源文件的大小、媒体规格和 SHA-256，复核或生成六个固定片段，并写出 `resolved-manifest.yaml`。任何哈希漂移都必须停止，不能自动接受新哈希。

## 3. 启动隔离生产栈

在第一个终端执行：

```bash
cd /data/project/lyk/vsa-agent

export PATH="/home/ykh/.conda/envs/vsa-agent/bin:/usr/local/dev/anaconda3/bin:$PATH"
stamp="$(date -u +%Y%m%d-%H%M%S)"
export VSA_BUSINESS_STAMP="$stamp"

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

## 4. 运行结构化业务门禁

在第二个终端先运行快速层：

```bash
cd /data/project/lyk/vsa-agent

conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --manifest tests/fixtures/business_video_baseline/manifest.yaml \
  --data-root .runtime/business-video-baseline \
  --profile quick \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000
```

快速层六个片段均通过后，再执行发布层和完整视频层：

```bash
conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --data-root .runtime/business-video-baseline \
  --profile release \
  --api-url http://127.0.0.1:8000 \
  --ui-url http://127.0.0.1:3000

conda run --no-capture-output -n vsa-agent python \
  scripts/run-business-video-regression.py \
  --data-root .runtime/business-video-baseline \
  --profile full \
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

退出码：`0` 通过，`2` 数据集或参数错误，`3` 流水线/Provider/基础设施错误，`4` 业务准确性失败，`5` 清理失败。HTTP 瞬时重试记录在当前 attempt 中，不会增加 Provider attempt 数。

## 5. 原版 UI 真实叉车验收

栈保持运行时，在第二个终端执行：

```bash
cd /data/project/lyk/vsa-agent/frontend/original-ui

RUNTIME_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_LIVE_PROVIDER=1 \
PLAYWRIGHT_REAL_VIDEO=/data/project/lyk/vsa-agent/.runtime/business-video-baseline/clips/forklift-person-proximity.mp4 \
PLAYWRIGHT_REAL_QUERY='forklift operating close to a pedestrian' \
PLAYWRIGHT_CHAT_TRACE_ROOT=/data/project/lyk/vsa-agent/.runtime/es-stack/latest/chat-traces \
npm run test:e2e --workspace nv-metropolis-bp-vss-ui -- \
  --grep 'validates a real forklift business video through the original UI'
```

该用例显式启用时才运行。默认 Playwright 仍使用合成 fixture，不会调用真实 Provider。真实用例完成上传、搜索、缩略图与 Range 播放、`+ Chat`、概念门禁和资产删除。

## 6. 失败排查

按以下顺序查看证据：

```bash
latest="$(find .runtime/business-video-regression -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
cat "$latest/report.json"
cat "$latest/runner.log"
find "$latest/cases" -name '*.json' -print

tail -n 200 .runtime/es-stack/latest/api.log
tail -n 200 .runtime/es-stack/latest/worker.log
tail -n 200 .runtime/es-stack/latest/ui.log
```

报告中的 `failure_category` 先区分数据集、流水线、准确性和清理问题，再查看具体 case/attempt。不要用重新运行掩盖哈希漂移、禁止结论或清理失败。
