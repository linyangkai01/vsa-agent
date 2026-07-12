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
- [ ] 4.4 Finish on the local development branch, merge locally to `master`, push only remote `master`, and archive the Comet change after verification passes.

## 5. Interactive Original-UI ES Validation

- [ ] 5.1 Add a tested `/api/v1/search` route that preserves the original VSS Search request and `{data: [...]}` response contract while reusing SearchAgent and registered `embed_search`.
- [ ] 5.2 Extend the Windows and Linux ES stack launchers with an interactive all-stack mode that reclaims only selected ES/API/UI ports, starts the original UI, and retains owned services until interruption.
- [ ] 5.3 Add focused tests and documentation for the search route, UI runtime environment, port-reclamation behavior, browser validation evidence, and mapped-server sync.

## 6. 运行时产物清理

- [x] 6.1 让 `/api/search/ingest` 以 `video_id` 覆盖写入 ES，并让 smoke 使用固定验证 ID，避免重复启动后重复展示 `runtime-validation.mp4`。
- [x] 6.2 删除 map、dashboard 和 alerts 声明文件中无对应文件的 `server.d.ts.map` 引用，保留源映射编译配置、运行时声明和现有依赖不变。
- [ ] 6.3 在 Ubuntu 重启运行栈，确认 UI 搜索只返回一个 smoke 记录，且 `ui.log` 不再包含 `failed to read input source map`。
