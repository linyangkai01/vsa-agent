# Development Status

Last updated: 2026-07-23

## Current State

- Active development track: recorded-video production acceptance.
- Integration target: local and remote `master`; the feature implementation is complete.
- Phase: validation; only the external real-provider acceptance gate remains open.
- Goal: deliver original-UI recorded-video upload, durable analysis, Elasticsearch search, selected-video understanding Q&A, thumbnail and time-range playback without NVIDIA runtime services.
- Confirmed first-stage runtime: single Ubuntu server, local file storage, SQLite WAL jobs, independent Worker, OpenAI-compatible VLM/embedding, fixed-duration replaceable segmentation, and one stack launcher.
- Out of scope for this change: RTSP, alerts, Kafka/MDX, multi-node deployment, MinIO/S3, Redis/Celery and full VST emulation.

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

## Latest Verified Change

`provider-readiness-probe`

- 现有单栈启动器新增显式 `--probe-providers` / `-ProbeProviders`，按生产配置顺序检查真实 embedding 与 VLM，并以稳定退出码区分配置、认证/额度、暂态网络和接口契约问题。
- 探针默认关闭；显式运行时加载同一私密密钥文件，但不安装完整栈依赖、不启动或停止 Docker/ES/API/Worker/UI、不回收端口、不创建数据目录、索引或任务。
- 结构化日志只保留安全 provider identity、HTTP status、耗时、白名单错误码与 request ID；canary 测试覆盖响应、异常、JSON、stdout/stderr 和启动器日志脱敏。

Verification:

- 本地全量（显式 projection fallback）：`1590 passed, 6 skipped, 1 warning`；未配置本地 ES 的首次运行另有 `1580 passed`，10 个 integration fixture 按契约拒绝启动，不是断言失败。
- Bash/PowerShell 启动器生命周期：`121 passed`；其中实际 probe 成功/额度失败路径确认退出码 `0/3` 且没有 Docker、端口、UI、数据目录或业务写入副作用。
- Ruff 全仓、format、compileall、Bash/PowerShell 语法、diff check 和 `Z:\vsa-agent` 同步预检均通过。
- Ubuntu focused：`74 passed, 5 skipped`，Bash syntax 通过。真实 probe 两次稳定得到 embedding `200/ok`（最终 239 ms）、VLM `403/AllocationQuota.FreeTierOnly`（最终 62 ms）并退出 `3`；精确密钥扫描、Docker 状态不变和 Conda 噪声检查均 PASS。

## Outstanding Validation

- `production-recorded-video-ingest`: Task 1-23、Ubuntu fake-provider 浏览器验收和 Git 集成均已完成；原版 UI 已接入任务状态轮询、流式同源代理和录播业务链路。当前仅剩 Task 24 真实 provider PASS 证据。
- Task 20 运行时实现与加固提交为 `473a001`、`71d5d71`、`a7f6f71`、`5252ddb`。启动器 focused tests、脚本语法与生命周期验证由对应任务记录。
- Task 20A 最终本地证据：三文件串行 aggregate `185 passed, 1 conditional skip`，PowerShell lifecycle `45 passed`，TERM/PASS-lock 高风险 Bash probe 连续三轮通过；PowerShell AST、Bash syntax、compileall、Ruff check/format 和 diff check 全绿。v5 thorough review 为 Critical `0`、Important `0`。候选进程绑定失败仍不写 reason-code 日志，暂作为非阻塞可观测性 Minor 保留，避免 250ms tracker 轮询产生重复日志噪声。
- Task 23 新增 `scripts/recorded-video-validate.py`：按 `runtime/job_stages/provider/es/search/media/delete` 记录证据，任何依赖或质量失败均写失败报告并返回非零，且在中途失败后仍尝试清理验证资产。中文手册为 `docs/recorded-video-runtime.md`；Task 24 已到达真实 DashScope，额度恢复前报告保持 FAIL。
- 2026-07-21 已补齐搜索结果到视频问答的身份链路：Search API 保留 `asset_id/segment_id/job_id`，原版 UI `+ Chat` 发送片段 context，后端只通过 SQLite 和受控资产目录解析真实路径与相对时间范围，再交给 `video_understanding`。本地证据：相关 Python `136 passed`，Search Jest `165 passed`，Search typecheck 通过。
- 2026-07-21 新增 `scripts/recorded-video-production-acceptance.py`：一次命令启动两次完整栈，三并发上传真实视频，在持久化 checkpoint 后校验本次 run 的 Worker manifest/UID/cmdline 并中断，随后验证 attempt 恢复、七阶段 checksum、真实 provider identity、ES/SQLite segment、原版 UI 同源搜索/缩略图/Range/选中片段问答和三资产幂等删除。Ubuntu 已通过三视频上传、checkpoint、Worker TERM、第二次启动与 attempt 恢复，最终 PASS 仍受真实 provider 额度阻断。
- 2026-07-23 原版 UI Chromium E2E 连续两次通过 `3 passed (2.9m)`：MP4/MKV 上传、索引、搜索、缩略图、HTTP Range 播放、失败任务重试和运行中取消均通过；第二次优雅关闭删除隔离 namespace，旁路确认无 validation 进程、索引、测试端口或容器残留。
- 2026-07-23 Ubuntu 前端补充验证：Video Management Jest `99 passed`，Video Management 与原版应用 typecheck 通过；同步白名单已覆盖新增 mock 和声明契约文件。
- 2026-07-23 Ubuntu 真实生产验收使用 `vsa-recorded-video-production` alias，避开并保留 legacy 具体索引 `vsa-video-embeddings`。三条真实视频并发上传、checkpoint、Worker TERM、第二次启动和 attempt 恢复均通过；服务器无管理员权限时复用了当前用户 `vss` Conda 环境中的 ffmpeg 8.0.1，并在 `vsa-agent` 环境提供用户态符号链接，探测到 `libopenh264`。
- 真实 provider gate 仍未通过：三条恢复任务的 VLM 调用达到 `MODEL_TIMEOUT`，随后最小独立 DashScope VLM 请求在约 1 秒内明确返回 `403 AllocationQuota.FreeTierOnly`。这证明密钥文件读取、DNS、TCP/TLS 和兼容 API 路径正常，当前阻塞是供应商额度而非项目代码；报告保持 FAIL，待额度恢复后原命令重跑 Task 24。
- 2026-07-23 新增单入口真实 provider readiness probe；Ubuntu 证据 run `03ad4833-0b6c-4c4b-929d-5e796e7ba923` 确认 embedding 可用、VLM quota，返回稳定退出码 `3`，且未改变 Docker 状态、未泄露密钥。额度恢复后先重跑同一 probe，只有两项均 `ok` 才进入三视频最终生产验收。

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

Current command for the next validation pass:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
```

Operational guide: `docs/es-video-search-runtime.md`.

Server validation status: Ubuntu fake-provider browser E2E has passed, including upload, recovery, search, thumbnail, Range playback, retry and cancellation. The 2026-07-23 real-provider run reached DashScope after the Worker restart recovery gate, but remains FAIL because the configured account returns `403 AllocationQuota.FreeTierOnly`. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`.

## Next Recommended Work

DashScope 额度恢复后直接重跑 Task 24 生产验收，并归档真实 provider PASS 报告。
