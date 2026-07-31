# Development Status

Last updated: 2026-07-31

## Current State

- Active development track: local vLLM video privacy, resource admission and full remote-provider egress control.
- Integration target: local and remote `master`; the accepted design is implemented on `codex/local-vllm-video-privacy` and is awaiting final Ubuntu bootstrap and runtime acceptance before merge.
- Phase: local implementation and automated verification are complete. The remaining gate is the real Ubuntu vLLM bootstrap, resource/warm-up validation, original-UI business flow and shutdown evidence.
- Goal: keep video pixels and identifying metadata on the Ubuntu server, reject unsafe startup when GPU/RAM/disk/process ownership is insufficient, and preserve the complete original-UI upload, processing, search, playback and Q&A flow.
- Confirmed first-stage runtime: one RTX 4090 D, `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` on local vLLM, single VLM concurrency, DashScope LLM/embedding, local ES/SQLite/files and one supervised stack launcher.
- Out of scope for this change: multi-GPU, remote visual fallback, automatic model downgrade, GPU process preemption, public-network serving and administrator-only installation.

## Latest Accepted Design

`local-vllm-video-privacy`

- Local visual understanding uses the official `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` revision `536a35794df8831aa814970ee8f89eff577e7718`; bootstrap and daily offline startup are separate.
- The RTX 4090 D admission floor is dynamic: with `gpu_memory_utilization=0.70`, the initial engine budget is 17,195 MiB and required free VRAM is 21,291 MiB including a 4 GiB reserve. Calibration may raise but never lower the floor.
- The launcher acquires a single-instance lock before any mutation, only reclaims processes proven by kernel start tick, boot ID and process-group identity, and rejects unknown GPU or port occupants.
- All DashScope LLM/embedding calls pass through one `RemoteProviderGateway` using closed `RemoteSafe*` DTOs. Raw VLM descriptions, paths, filenames, sensor IDs, absolute timestamps and local search results cannot cross the boundary.
- Privacy projection is persistent and versioned; segment-level checkpoints support safe recovery without promising impossible provider exactly-once semantics.
- Accepted Chinese specification: `docs/specs/local-vllm-video-privacy/spec.md`.

## Local vLLM Privacy Implementation

Implemented on the current feature branch:

- Added the fixed-revision, hash-verified user-level bootstrap and offline preflight for `Qwen/Qwen2.5-VL-7B-Instruct-AWQ`, including GPU, effective RAM, `/dev/shm`, per-filesystem disk and dependency-manifest checks.
- Integrated supervised local vLLM startup, health/model/single-frame probes, strong process identity, unknown-listener rejection, fan-out shutdown and selected-GPU release verification into the one-command runtime stack.
- Added the `local_vlm_hybrid` profile: local loopback VLM, DashScope `qwen-turbo` LLM and `text-embedding-v4` embedding.
- Added closed `RemoteSafe*` DTOs, canonical enum-only ingest embedding, query screening and the single `RemoteProviderGateway` used by production remote LLM/embedding calls.
- Kept selected video path, filename, sensor, absolute time, local evidence, tool results and history outside remote TopAgent messages. The original UI now carries server-validated video context in local agent state and the local tool node injects it only at execution time.
- Removed request, frame, raw VLM output and local tool-result trace artifacts; logs and traces retain hashes, lengths, counts, model identity and error types instead of sensitive values.
- Removed the arbitrary model-adapter hook from `vss_summarize`; video summaries remain local until a typed `RemoteSafeSearchContext` protocol is implemented.

Local verification on 2026-07-31:

- Effective Windows unit set: `1525 passed, 1 skipped` (Linux Bash lifecycle and two invalid local subprocess/encoding harnesses excluded).
- Local-vLLM bootstrap/preflight/launcher contracts: `65 passed`.
- Privacy/UI/TopAgent/video focused contracts: `86 passed`; full selected-video context focused contracts: `41 passed`.
- Ruff, `compileall`, `git diff --check` and Ubuntu `bash -n` for `es-runtime-stack.sh` pass.
- Server read-only resource snapshot: RTX 4090 D, 24,564 MiB total, 24,211 MiB free, 0% utilization, no compute process. Bootstrap is not yet installed.

## Previous Accepted Design

`real-business-video-regression-baseline`

- Use a manifest-driven external dataset: public network videos remain on the Ubuntu server, while Git stores source, license, attribution, SHA-256, clip lineage and expected business conclusions.
- Dataset `1.1.0` contains six positive/negative cases covering forklift proximity, safe separation, close worker collaboration, ordinary work, PPE respiratory/dust controls and PPE misuse. The former PPE-positive case is now `ppe-respiratory-controls` so the gate describes visible equipment instead of asserting broad compliance.
- Fast validation runs 20-60 second clips once; release validation runs each case three times and requires 2/3 concept coverage passes with no forbidden conclusion in any attempt. Full-source runs validate long-video segmentation and event retrieval.
- Every core search must hit the correct run-scoped asset in Top-5 within a five-second boundary tolerance. Required-concept coverage is at least 80%; output language is not a contract and LLM-as-judge is diagnostic only.
- A representative real forklift Playwright flow verifies original-UI upload, processing, search, playback, `+ Chat` context and final answer. Synthetic fixtures remain only for fast deterministic UI behavior tests.
- Schema v2 uses clause-level required and forbidden concept groups with explicit negated alternatives. A required concept does not match when its negation occurs in the same clause, and forbidden conclusions are reported by stable group ID.
- Real-provider acceptance is blocked unless `/api/v1/runtime/evidence` proves recorded video is enabled, resolved LLM/VLM/embedding roles are configured and non-mock, search mock controls are disabled, and a redacted configuration fingerprint is available.
- Accepted Chinese specification: `docs/specs/real-business-video-regression-baseline.md`.

## Git Policy

- Develop on local temporary branches or worktrees.
- Prefer branches for ordinary single-threaded work.
- Use worktrees only when parallel local runtimes, side-by-side comparison, or a long-running isolated experiment is genuinely useful.
- For small safe documentation/configuration tweaks on a clean `master`, avoid unnecessary branch/worktree churn.
- Merge completed work into local `master`.
- Push `master` to origin.
- Keep remote branches cleaned up; this project does not normally use PR branches.

## Parallel Development Policy

- Parallelize only genuinely independent work with clear ownership boundaries.
- The main session remains responsible for integration, verification, cleanup, and the final local merge to `master`.

## Current Business Baseline Hardening

`real-business-video-regression-baseline` manifest schema v2 / dataset `1.1.0`

Implemented locally; final `1.1.0` Ubuntu reruns are pending:

- 固定 manifest 升级为严格 schema v2、dataset `1.1.0`，继续固定三个 CC BY 3.0 来源、三个源文件和六个派生片段的身份、许可与哈希；required groups 新增同 clause 的 `negated_alternatives`，forbidden conclusions 改为稳定分组。
- 数据准备器对已有文件同时验证大小和 SHA-256；下载使用临时文件和原子替换，默认总 deadline 为 30 分钟；每次 ffprobe/FFmpeg 调用默认 deadline 为 10 分钟，超时会终止工具进程组并删除未完成片段。
- 业务 runner 在任何上传前执行 redacted runtime-evidence 硬门禁，并把角色、模型、mock 控制和配置指纹写入报告。搜索、缩略图和媒体请求可按瞬时 HTTP 策略重试；每个 Provider attempt 的 Chat 只发送一次，失败即 `pipeline_error`，不得用重试改变 2/3 统计。
- 每次成功 Chat 必须由 API 经原版 UI proxy 返回精确 `X-VSA-Trace-ID`；runner 再读取该 trace 的脱敏证据，强校验 conversation/message/asset/segment 身份、恰好一次实际 `video_understanding.result`、唯一非空 final、五类关键事件和无 error 事件。模型若重复发起完全相同的工具调用，只允许由 TopAgent 缓存命中，不能产生第二次实际视频理解结果。
- 搜索命中必须同时匹配本次运行的 `asset_id`、`job_id` 和 `segment_id`；缩略图必须同源且非空，媒体必须返回合法 HTTP 206 单字节 Range。
- 资产一创建就登记清理候选，因此上传/complete/Job/搜索/Chat 任一阶段失败仍会尝试删除。报告分别保留 `primary_failure` 与 `cleanup_failures`；清理失败使用退出码 `5`，不会覆盖丢失原始故障证据。
- 原版 UI 真实叉车门禁在上传前检查相同 runtime evidence，使用与 Python evaluator 对齐的 clause-level 门禁，并从响应头关联精确 Chat trace。所有路径都清理 create 后已登记的资产；204 后还必须验证媒体 404/410、搜索不再命中，并释放页面诊断。服务器若缺少 Chromium 系统库，浏览器使用版本匹配的官方 Playwright 容器，测试 runner 和输出仍由宿主用户管理。
- 本地验证：排除两个只能在 Ubuntu 运行的 launcher 环境文件后，Python 单元集 `1461 passed, 1 skipped`；原版 UI focused Jest `5 passed, 1 skipped`，Chat header Jest `1 passed`，应用 typecheck、相关 Prettier 检查和真实用例 Playwright discovery 均通过。
- Ubuntu dataset `1.1.0` 的首个隔离 quick run 已证明 VLM 和 embedding 正常，但默认 LLM `qwen3.7-plus` 返回 `403 AllocationQuota.FreeTierOnly`。随后 `qwen-plus` 的完整真实 API 探测通过；release 又暴露出旧 VLM `qwen3-vl-flash-2025-10-15` 无响应，当前真实 DashScope profile 已切换为 `qwen-plus` + 有额度的 `qwen-vl-plus`，并为 OpenAI-compatible 请求补上 180 秒 timeout。此前 quick/release 结果仍是历史排障证据，最终 quick/release/full/UI 必须在新 stamp 上从头重跑。
- `qwen-vl-plus` 隔离 quick run 的 6 个真实链路均完成且无 pipeline 错误，但 evaluator 未把 `woman` 视为 person、未把 `closely/closer` 视为 close，造成两个准确性假阴性。通用 clause 归一化已补充这些明确词形，同时保留 whole-word 与同 clause 否定规则；两条真实回答离线重评均为 100% coverage 且无 forbidden。最终报告仍需在包含该修复的新 commit 和新 stamp 上重新生成。
- evaluator 修复后的 quick 已 6/6 通过；release 的 18 次真实 Chat 中仅 `ppe-respiratory-controls` 为 1/3，其三次均正确识别 respirator 与 dust control，但两次回答未显式提到佩戴设备的人员。生产 TopAgent 提示现要求画面存在人员时先明确识别 people/workers 及其动作，再给出设备与安全结论；固定 dataset manifest 和 80% 门禁保持不变，仍需新 commit/stamp 全量重跑。
- 主体明确化提示使 `ppe-respiratory-controls` quick 通过，但 `ppe-noncompliant` 回答使用 `absent/not worn/complete absence`，旧 evaluator 只识别 `missing/not wearing`。通用归一化现统一这些明确词形，并同步归一化 `properly worn` 等否定/合规短语，避免错误放行；manifest 与门禁仍不变。
- evaluator 修复后的最终候选 quick 6/6 通过，release 前 17 个 attempt 均正常，但最后一次文本 LLM 调用使 `qwen-plus` 返回 `403 AllocationQuota.FreeTierOnly`；所有 6 个资产仍完成 `204/404` 清理。`qwen-vl-plus` 不会生成 TopAgent 所需工具调用，不能兼任 LLM；`qwen-turbo` 已分别通过恰好一次 function-calling 探测和完整真实 API `6 passed`，因此生产 profile 改为 `qwen-turbo` + `qwen-vl-plus`。

Pending final verification:

- 对 dataset `1.1.0` 重新执行无下载固定身份复核；旧 dataset 的 quick/release/full/UI 结果不得作为本版本验收结果。
- 在全新隔离 data-root 和 Elasticsearch namespace 上依次执行 quick、release 和 full，检查 JSON、JUnit、逐 attempt、provider evidence、精确身份以及成功/失败路径清理。
- 使用真实叉车片段执行原版 UI Playwright，归档宿主机可写的独立 output directory、chat traces、页面/网络诊断和删除证据。
- 完成上述验证后才能把设计状态改为已验收并形成正式归档；目前不得记录 `1.1.0` PASS。

## Previous Verified Runtime Baseline

The following results predate dataset `1.1.0` and prove the underlying production path, not the current business baseline release:

- 原版 UI 真实业务链已覆盖：上传 MP4/MKV、Worker 真实 VLM/embedding 入库、Elasticsearch 搜索、缩略图与 HTTP 206 播放、`+ Chat` 上下文选择、同源 Chat API、TopAgent、`video_understanding` 和最终页面回答。
- 修复隔离端口下 Chat 仍回退到 `127.0.0.1:8000` 的问题；Linux/Windows 单脚本现在把当前 API URL 注入 `NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL`。真实 Provider 模式为流式最终回答保留 180 秒窗口，确定性模式仍保持 30 秒快速失败。
- 修复真实模型 Markdown 回答中的 inline code 被块级 `CodeBlock` 渲染而产生 `<div>/<pre>` 嵌套于 `<p>` 的 React 警告，并增加 DOM 回归测试。
- 确定性隔离 run `362c35d3-9563-404a-8ea0-546c754530a4` 完整通过 `3 passed (2.3m)`；trace 中 `original_ui.chat.request`、`top_agent.tool.call`、`video_understanding.result`、`top_agent.tool.result`、`top_agent.final` 均存在且最终回答唯一非空。
- 真实 Provider probe run `33ab793c-6b99-449d-bafe-cdbd0f7944a3` 通过，DashScope VLM/embedding 均返回 HTTP 200。最终真实原版 UI run `bb060cac-4981-4bbe-bcca-c0d0ec9edfe3` 通过 `1 passed (1.6m)`，实际使用 `qwen3.7-plus`、`qwen3-vl-flash-2025-10-15` 和 `text-embedding-v4`，页面、console、网络、5xx 与 trace 检查全部通过。
- 所有 canary runtime、validation namespace 和 8300/3300/8399 端口均已清理；生产 Elasticsearch 未停止或清空，密钥只从 `~/.config/vsa-agent/secrets.env` 加载且未输出。

Verification:

- 本地启动器契约：`45 passed`；Provider/E2E 契约：`12 passed`；Markdown DOM Jest：`1 passed`；相关 Prettier 与 `git diff --check` 通过。
- Ubuntu `@nemo-agent-toolkit/ui` build：`107 files compiled`；Markdown DOM Jest：`1 passed`；确定性浏览器 E2E：`3 passed`；真实 Provider 浏览器 E2E：`1 passed`。

Previous production acceptance baseline:

- 新密钥通过服务器用户私有文件 `~/.config/vsa-agent/secrets.env` 注入，文件 owner/mode/单条目契约均已验证；密钥未进入命令参数、仓库、报告或日志。
- 真实 provider probe run `56606c54-ebe1-4020-b78c-a997932b30c2` 通过：`text-embedding-v4` 与 `qwen3-vl-flash-2025-10-15` 均返回 HTTP 200，整体退出码为 `0`。
- 最终三视频生产验收 `b9932665-3f18-4d16-ba09-da0877e40653` 在隔离 data-root `/data/project/lyk/vsa-validation-data/final-20260724-01` 和独立 alias `vsa-recorded-video-production-final-20260724-01` 上通过。
- 两次 launcher run 为 `df73b078-9ff7-4db9-8f8b-aaa1fa092788` 与 `0a0387d8-be6e-4562-88b4-44042f271c42`。验收覆盖三并发上传、Worker TERM/租约恢复、七阶段 publish、真实 VLM/embedding、9 个确定性 segment、三次原版 UI 搜索/缩略图/HTTP 206/选中片段问答和三资产双重幂等删除。
- 三份 chat trace 逐项审计通过：每份都有 `video_understanding.result`、成功 tool message、唯一非空 `top_agent.final`，且没有 error/failed/Traceback 标记。验收结束后 alias 文档数为 `0`，无验收进程残留，secret scan PASS。

Verification:

- 本地全量（显式 projection fallback）：`1590 passed, 6 skipped, 1 warning`；未配置本地 ES 的首次运行另有 `1580 passed`，10 个 integration fixture 按契约拒绝启动，不是断言失败。
- Bash/PowerShell 启动器生命周期：`121 passed`；其中实际 probe 成功/额度失败路径确认退出码 `0/3` 且没有 Docker、端口、UI、数据目录或业务写入副作用。
- Ruff 全仓、format、compileall、Bash/PowerShell 语法、diff check 和 `Z:\vsa-agent` 同步预检均通过。
- Ubuntu focused：`74 passed, 5 skipped`，Bash syntax 通过。最终真实 probe 与三视频生产验收均 PASS；正式报告为 `docs/recorded-video-validation.md`，结构化 cases 为 `docs/recorded-video-validation.cases.json`。

## Completed Production Validation

- `production-recorded-video-ingest` Task 1-24 已完成。原版 UI 已接入任务状态轮询、流式同源代理、录播上传、搜索、媒体读取和选中片段理解问答。
- Task 20/20A 的启动器生命周期与进程归属加固、本地和 Ubuntu focused tests、脚本语法、Ruff、compileall 与 diff check 均已通过；候选进程绑定失败不写 reason-code 仍作为非阻塞可观测性改进项保留。
- Task 23 的单资产诊断器与 Task 24 的三视频恢复验收器均已落地。正式验收报告和 cases 已回传仓库，真实 provider gate 不再有外部 quota blocker。
- 2026-07-23 原版 UI Chromium E2E 连续两次通过 `3 passed (2.9m)`；2026-07-24 最终真实验收进一步证明真实 provider、Worker 恢复、ES/SQLite 一致性和选中片段问答。
- 第一次使用共享 `/data/project/lyk/vsa-data` 验收时，Worker 会认领其中历史 backlog，导致本次任务与旧任务相互干扰。最终 gate 必须使用全新、专用、空的 data-root 与独立 ES alias；长期生产目录仅用于 normal 业务运行，不得作为确定性验收环境。

## Python Quality Program

The repository-wide Python quality work was split into five ordered workstreams. `frontend/original-ui` is excluded from code-quality refactoring.

- `stabilize-test-contracts`: implementation and verification complete. The current branch already contains `tests/unit/recorded_video/__init__.py`, which gives `recorded_video/test_models.py` a package-qualified module name while `archive/test_models.py` remains distinct.
- `enforce-python-quality-baseline`: implementation complete; Ruff lint and format debt is cleared in `src/` and `tests/`.
- `consolidate-runtime-scripts`: implementation complete; all 14 user entries remain, the DashScope wrappers share one preflight helper, and stale archived-change paths no longer block server sync preflight.
- `refactor-video-understanding-pipeline`: implementation complete; pure normalization is isolated from the stable I/O facade while public contracts and monkeypatch paths remain intact.
- `refactor-search-orchestration`: implementation complete; routing, normalization, deduplication, confidence fallback, critic filtering and trimming now use one pure rule module.

Test collection verification on 2026-07-13:

```powershell
pytest --collect-only -q
pytest -q
```

Result: `763 tests collected`; `759 passed, 4 skipped, 1 warning`.

Python quality baseline verification on 2026-07-13:

```powershell
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: compileall passed; Ruff reported zero lint issues; all 235 files were already formatted; `759 passed, 4 skipped, 1 warning`. The warning is the existing Starlette `httpx` deprecation from the installed environment.

Runtime script consolidation verification on 2026-07-13:

```powershell
Get-ChildItem scripts -Recurse -Filter *.sh | ForEach-Object { bash -n $_.FullName }
Get-ChildItem scripts -Recurse -Filter *.ps1 | ForEach-Object { [void][scriptblock]::Create((Get-Content -Raw $_.FullName)) }
pytest -q tests/unit/test_dashscope_live_runner.py tests/unit/scripts
ruff check src tests
ruff format --check src tests
pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-server-files.ps1 -PreflightOnly
```

Result: all scripts parsed; `58` script tests passed; Ruff reported zero issues and 235 formatted files; `760 passed, 4 skipped, 1 warning`; mapped target preflight passed for 36 files. The 14 user script entries remain supported, while the two DashScope entries now share `scripts/lib/dashscope_runtime.sh`.

Video-understanding pipeline verification on 2026-07-13:

```powershell
pytest -q tests/unit/tools/test_video_understanding_normalization.py tests/unit/tools/test_video_understanding.py tests/unit/tools/test_video_understanding_live_trace.py tests/unit/tools/test_lvs_video_understanding.py tests/unit/data_models/test_understanding_models.py tests/acceptance/test_video_understanding_flow.py
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: the video path matrix passed 96 tests; Ruff reported zero issues and 237 formatted files; the current full tree passed `782 passed, 4 skipped, 1 warning`. `video_understanding_normalization.py` owns pure time, reasoning, evidence, event and result conversion; `video_understanding.py` keeps stable frame/VLM/source/tool boundaries and compatibility imports; LVS directly consumes the pure timestamp helper.

Search-orchestration verification on 2026-07-13:

```powershell
pytest -q tests/unit/tools/test_search_pipeline.py tests/unit/tools/test_search.py tests/unit/tools/test_embed_search.py tests/unit/tools/test_attribute_search.py tests/unit/agents/test_search_agent.py tests/unit/api/test_original_ui_search_route.py tests/acceptance/test_search_flow.py
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: the search path matrix passed 75 tests; Ruff reported zero issues and 239 formatted files; the current full tree passed `792 passed, 4 skipped, 1 warning`. `search_pipeline.py` owns pure routing and result-selection rules; `search.py` retains models, external dependency boundaries, stage logs, critic calls, progress order and registration.

## Active Runtime Validation

Current command for normal production interaction:

```bash
./scripts/es-runtime-stack.sh \
  --api-port 8000 \
  --es-port 9200 \
  --ui-port 3000 \
  --index vsa-recorded-video-production \
  --data-root /data/project/lyk/vsa-data \
  --conda-env vsa-agent
```

Production operational guide: `docs/recorded-video-runtime.md`. The earlier ES-only smoke guide remains at `docs/es-video-search-runtime.md` for focused diagnostics.

Server validation status: Ubuntu fake-provider browser E2E and the 2026-07-24 real-provider three-video production acceptance both passed. The final gate used an isolated data-root and ES alias, completed cleanup, left the acceptance alias at zero documents, and left no acceptance process running. Current code synchronization policy is Git: merge completed local work to `master`, push `master`, then fast-forward the server checkout. Do not copy `.runtime` video binaries through Git.

## Next Recommended Work

提交并合并当前 local-vLLM 隐私实现，推送 `master` 后在 Ubuntu 执行首次 bootstrap 与幂等复跑。随后运行单脚本启动、单帧和 24 帧压力、真实 DashScope LLM/embedding、原版 UI 上传/搜索/播放/问答、全链路 canary、未知资源拒绝与退出后 60 秒显存恢复验证。全部通过后再把规格标记为已验收，并恢复 dataset `1.1.0` 的 quick/release/full 业务基线。
