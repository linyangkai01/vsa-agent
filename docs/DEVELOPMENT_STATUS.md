# Development Status

Last updated: 2026-07-25

## Current State

- Active development track: recorded-video production acceptance completed; operational hardening is the next track.
- Integration target: local and remote `master`; the feature implementation is complete.
- Phase: accepted on the approved Ubuntu server with real DashScope VLM/embedding and the original UI business flow.
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

`production-recorded-video-acceptance`

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

Server validation status: Ubuntu fake-provider browser E2E and the 2026-07-24 real-provider three-video production acceptance both passed. The final gate used an isolated data-root and ES alias, completed cleanup, left the acceptance alias at zero documents, and left no acceptance process running. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`.

## Next Recommended Work

进入生产化后续：补充长期运行监控、容量与保留策略、真实业务视频基线集，并定期用全新隔离 data-root/alias 重跑三视频恢复 gate，避免生产 backlog 污染验收结论。
