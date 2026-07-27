# 原版 UI 选中片段 Chat 双层验收设计

日期：2026-07-27

## 目标

在已有录播视频上传、处理、Elasticsearch 搜索和媒体播放浏览器回归之上，补齐用户实际可见的最后一段业务链路：从原版 UI 搜索结果点击 `+ Chat`，输入问题，通过同源 Chat API 调用 TopAgent 和 `video_understanding`，最终在页面看到非空回答。

本次不建设新的业务视频数据集，不替换原版 UI，不引入新的运行时或测试依赖。

## 验收分层

### 必跑的确定性 Playwright gate

现有 E2E 假 Provider 继续负责录播入库所需的 VLM 和 embedding 响应，同时增加 OpenAI-compatible tool-call 行为：

1. 录播 Worker 向 `playwright-vision` 发送帧分析请求时，返回固定的结构化视频描述。
2. TopAgent 向 `playwright-chat` 发送带 tools 的首轮请求时，Provider 从服务端注入的已验证视频上下文中提取 `video_path`、问题和时间范围，返回 `video_understanding` tool call。
3. `video_understanding` 再向 `playwright-vision` 请求片段分析，获得固定的结构化理解结果。
4. TopAgent 带 ToolMessage 进入下一轮时，Provider 返回固定、非空的最终回答。

Playwright 必须实际操作浏览器，不允许 route stub 或直接调用 Chat API 代替 UI 点击。用例复用已上传并搜索到的 MP4 结果，点击该结果内的 `+ Chat`，确认 context chip 后输入问题并发送。

### 服务器真实 Provider gate

确定性 gate 通过后，在 Ubuntu 服务器使用用户私有密钥文件 `~/.config/vsa-agent/secrets.env` 启动隔离 runtime，复用原版 UI 和同源代理执行真实模型验收。密钥只作为服务器进程环境变量读取，不进入命令参数、仓库、日志、trace 或报告。

真实 gate 至少证明：

- 浏览器可访问原版 UI；
- 搜索结果可加入 Chat context；
- 同源 Chat API 返回成功流；
- TopAgent 调用 `video_understanding`；
- 真实 VLM 返回有效结果；
- 页面显示唯一、非空的最终回答。

## 浏览器与后端契约

浏览器侧通过标准：

- 目标搜索卡片唯一且属于刚上传的资产；
- 点击 `+ Chat` 后按钮反馈为 `Added`，Chat 输入区显示对应文件名 context chip；
- 浏览器发出同源 Chat POST，请求体包含用户问题和选中片段 context；
- context 至少包含 `assetId`、`segmentId`、`jobId`、`videoName`、`startTime` 和 `endTime`；
- 请求不得接受或发送浏览器提供的本地 `video_path`；
- 页面显示预期的非空 assistant 最终回答；
- intermediate steps、loading 或 error 文本不能被误判为最终回答；
- 页面无 `Failed to fetch`、未处理异常、HTTP 5xx 或 console error。

后端日志和 trace 通过标准：

- API 日志包含 `original_ui.chat.context.resolved`；
- `original_ui.chat.request`；
- `top_agent.tool.call`，工具名为 `video_understanding`；
- `video_understanding.result`；
- 唯一且非空的 `top_agent.final`；
- 无 error/failed/Traceback 事件或文本。

## 安全边界

浏览器只提交资产、片段和任务身份。API 必须通过录播仓库重新解析资产和片段，生成服务器受控路径，并把该路径注入 TopAgent。假 Provider 的 tool call 只能使用这一服务端注入路径，不能从原始浏览器 context 构造本地文件路径。

测试日志和失败附件可以保留请求结构、状态码、事件名和脱敏后的上下文，但不得包含 API Key。真实 Provider 失败时报告 provider probe、HTTP 状态和 trace 事件，不打印请求认证头。

## 代码范围

- `scripts/es-runtime-stack.sh` 与 `scripts/es-runtime-stack.ps1`：向 UI 注入当前隔离 API 的 Chat URL
- `scripts/run_original_ui_vss.sh`：单脚本默认启用原版 UI Chat 侧栏
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/components/Home.tsx`：把搜索结果的标准 `contextType` 原样交给 Chat
- `frontend/original-ui/packages/nemo-agent-toolkit-ui/pages/api/home/home.tsx`
- `frontend/original-ui/packages/nemo-agent-toolkit-ui/pages/api/home/home.context.tsx`
- `frontend/original-ui/packages/nemo-agent-toolkit-ui/lib-src/index.d.ts`：统一 `QueryDataContext` 类型契约
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/fake-openai-provider.py`
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts`
- `frontend/original-ui/packages/nemo-agent-toolkit-ui/components/Markdown/CustomComponents.tsx`：保证真实回答中的 inline code 使用合法 DOM
- `frontend/original-ui/packages/nemo-agent-toolkit-ui/__tests__/components/Markdown/CustomComponents.test.tsx`
- `tests/unit/scripts/test_es_runtime_stack_script.py`
- `tests/unit/scripts/test_recorded_video_e2e_provider.py`
- `docs/DEVELOPMENT_STATUS.md`

## 验证顺序

1. 假 Provider focused unit tests。
2. 相关 Python/API/脚本单元测试、lint、format 和 `git diff --check`。
3. 同步至 Ubuntu。
4. Ubuntu 确定性 Playwright gate。
5. Ubuntu 真实 Provider probe。
6. Ubuntu 原版 UI 真实 Chat gate，并审计页面、HTTP 和 trace 证据。
7. 通过后合并本地 `master` 并推送；任何 gate 失败都不推送。
