## 1. Runtime Stack Design

- [x] 1.1 Confirm the stack wrapper boundaries around existing ES lifecycle scripts, FastAPI startup, temporary config, smoke validation, and cleanup.
- [x] 1.2 Identify the minimal testable units for stack behavior without requiring Docker or a live API in normal unit tests.

## 2. Stack Script Implementation

- [x] 2.1 Add Windows/Linux stack validation scripts that start ES, write a temporary search-enabled config, start FastAPI, wait for health, run `scripts/es_ingest_smoke.py`, and print PASS/FAIL.
- [x] 2.2 Add a companion stop or cleanup path that stops only owned API processes and uses the existing ES stop behavior.
- [x] 2.3 Add focused tests or static checks for config generation, health probing, command construction, and failure messages where practical.

## 3. Documentation And Server Sync

- [x] 3.1 Update ES runtime documentation with one-command local validation, mapped-server `Z:\vsa-agent` usage, expected output, and troubleshooting.
- [x] 3.2 Update development status or verification notes so the project state clearly shows this change is in progress.
- [x] 3.3 Sync completed scripts and docs to `Z:\vsa-agent` after local implementation.

## 4. Verification And Closeout

- [x] 4.1 Run focused unit/static validation for the new scripts.
- [x] 4.2 Run OpenSpec validation for `script-es-runtime-stack`.
- [x] 4.3 Attempt real stack validation if Docker and the runtime environment are available; otherwise record the exact blocker.
- [x] 4.4 Finish on the local development branch, merge locally to `master`, push only remote `master`, and archive the Comet change after verification passes.

## 8. Verification Edge Cases

- [x] 6.4 Make smoke cleanup skip stale-record deletion when the configured Elasticsearch index does not yet exist.

## 5. Interactive Original-UI ES Validation

- [x] 5.1 Add a tested `/api/v1/search` route that preserves the original VSS Search request and `{data: [...]}` response contract while reusing SearchAgent and registered `embed_search`.
- [x] 5.2 Extend the Windows and Linux ES stack launchers with an interactive all-stack mode that reclaims only selected ES/API/UI ports, starts the original UI, and retains owned services until interruption.
- [x] 5.3 Add focused tests and documentation for the search route, UI runtime environment, port-reclamation behavior, browser validation evidence, and mapped-server sync.
- [x] 5.4 Make the Windows interactive launcher wait for an HTTP-ready original UI and fail on early or non-zero UI exit while retaining UI log paths.

## 6. 运行时产物清理

- [x] 6.1 让 `/api/search/ingest` 以 `video_id` 覆盖写入 ES；smoke 先删除仅匹配固定视频名、传感器和 `runtime-yard` 元数据的历史验证记录，再写入固定验证 ID，避免重复启动后重复展示 `runtime-validation.mp4`。
- [x] 6.2 删除 map、dashboard 和 alerts 声明文件中无对应文件的 `server.d.ts.map` 引用，保留源映射编译配置、运行时声明和现有依赖不变。
- [x] 6.3 在 Ubuntu 重启运行栈，确认 UI 搜索只返回一个 smoke 记录，且 `ui.log` 不再包含 `failed to read input source map`。

## 7. API 日志可观测性

- [x] 7.1 在 Windows/Linux 启动器的 Conda API 命令中启用 `--no-capture-output`，并为 `vsa_agent` 配置幂等 stdout INFO handler，保留 Uvicorn 和应用日志到 `api.log`。
- [x] 7.2 在 Ubuntu 重启运行栈并确认 `api.log` 包含 `original_ui.search.request` 和 `search_agent.embed_search`。
