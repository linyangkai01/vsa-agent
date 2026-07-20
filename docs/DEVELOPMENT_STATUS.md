# Development Status

Last updated: 2026-07-21

## Current State

- Active development track: `production-recorded-video-ingest`.
- Active branch: `codex/production-recorded-video-ingest`.
- Phase: build; implementation progress is tracked in this document and Git history.
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

`wire-es-ingest`

- Added real `/api/search/ingest` behavior.
- Uses `SearchBackendConfig`.
- Returns `skipped` when search indexing is disabled or not configured.
- Indexes one normalized metadata document to `search.embed_index` when enabled.
- Returns HTTP 502 for Elasticsearch indexing failures.
- Registers the ingest route in the FastAPI app.

Verification:

```powershell
python -m pytest tests\unit\api\test_video_search_ingest.py tests\unit\api\test_original_ui_chat.py tests\unit\api\test_original_ui_chat_route.py tests\unit\test_config_search.py tests\unit\tools\test_embed_search.py tests\unit\tools\test_attribute_search.py tests\unit\tools\test_search.py tests\unit\agents\test_search_agent.py -q
```

Result: `79 passed, 1 warning`.

## Active Change

- `production-recorded-video-ingest`: Task 1-21 和 Task 23 已完成；Task 20A 已完成单进程日志 supervisor、真实 workload sidecar、PASS 线性化、Windows retained-handle 身份跟踪、确定性中断清理与共享 CIM snapshot。原版 UI 已接入任务状态轮询和流式同源代理；当前剩余 Task 22 Playwright 原版 UI 验收与 Task 24 全量质量门/Ubuntu 真实 provider 证据。
- 当前分支：`codex/production-recorded-video-ingest`；Task 20 运行时实现与加固提交为 `473a001`、`71d5d71`、`a7f6f71`、`5252ddb`。启动器 focused tests、脚本语法与生命周期验证由对应任务记录。
- Task 20A 最终本地证据：三文件串行 aggregate `185 passed, 1 conditional skip`，PowerShell lifecycle `45 passed`，TERM/PASS-lock 高风险 Bash probe 连续三轮通过；PowerShell AST、Bash syntax、compileall、Ruff check/format 和 diff check 全绿。v5 thorough review 为 Critical `0`、Important `0`。候选进程绑定失败仍不写 reason-code 日志，暂作为非阻塞可观测性 Minor 保留，避免 250ms tracker 轮询产生重复日志噪声。
- Task 23 新增 `scripts/recorded-video-validate.py`：按 `runtime/job_stages/provider/es/search/media/delete` 记录证据，任何依赖或质量失败均写失败报告并返回非零，且在中途失败后仍尝试清理验证资产。中文手册为 `docs/recorded-video-runtime.md`；Ubuntu 真实模型证据仍须由 Task 24 采集，当前报告不得视为服务器通过。
- 2026-07-21 已补齐搜索结果到视频问答的身份链路：Search API 保留 `asset_id/segment_id/job_id`，原版 UI `+ Chat` 发送片段 context，后端只通过 SQLite 和受控资产目录解析真实路径与相对时间范围，再交给 `video_understanding`。本地证据：相关 Python `136 passed`，Search Jest `165 passed`，Search typecheck 通过。

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

Server validation status: Ubuntu browser validation has passed. Through the SSH UI tunnel, the original Search UI returned one `runtime-validation.mp4` result for `forklift near worker`; API logs recorded both `original_ui.search.request` and `search_agent.embed_search`, and UI logs contained no stale declaration source-map errors. The runtime remains a deterministic mock-embedding validation environment, not a production semantic-quality evaluation. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`.

## Next Recommended Work

完成 Task 22 原版 UI Playwright 上传、搜索、缩略图和 Range 播放验收后进入 Task 24：运行全量 Python、前端和 lint 检查，定向同步到 Ubuntu，并采集真实 provider、三并发、Worker 重启恢复、搜索、Range 媒体和生命周期清理证据。
