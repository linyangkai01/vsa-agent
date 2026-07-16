# Task 22 实施报告：Original UI Playwright 端到端验收

## 状态

READY_WITH_CONCERNS

## 实现

- 新增 Playwright Chromium 配置，默认消费 Task 20 隔离长驻契约 `scripts/es-runtime-stack.sh --validate --keep-running`，也支持显式 `RUNTIME_BASE_URL`。
- 固定单 worker 串行运行，失败时保留 trace 和 screenshot；不保留成功 trace。
- fixture 在每个 `testInfo.outputDir` 内调用 ffmpeg 生成 4 秒 MP4/MKV，并从 ffmpeg 产物生成取消用副本和截断的 corrupt MKV；仓库不提交媒体二进制。
- runtime fixture 在测试前验证 UI 首页和 same-origin `/api/v1/search` 代理，缺失 runtime 或 ffmpeg 时抛出带修复提示的错误，不 skip。
- 成功流通过真实 UI 上传 MP4/MKV，观察 Processing/Completed，搜索 `forklift`，验证缩略图真实加载，打开 VST URL，并对媒体 URL 发起 Range 请求断言 HTTP 206、Content-Range 和 10 字节响应。
- 错误流上传真实 corrupt MKV，观察安全 Failed 文案，点击 Retry 并再次观察 Processing/Failed；取消流在真实 `/complete` 202 后点击 Cancel All，并断言真实 `/jobs/{id}/cancel` 返回 200 和 Cancelled UI。
- 未使用 `page.route()` 或 request route mock 伪造后端业务。

## TDD 证据

RED：

```text
npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts
Exit 1: Cannot find module './fixtures' at recorded-video.spec.ts:4
```

GREEN / 可执行门禁：

```text
npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts --list
3 tests in 1 file (PASS)

npm --prefix frontend/original-ui run test --workspace nv-metropolis-bp-vss-ui
85 passed, 1 Playwright-only placeholder skipped (PASS)

npx --yes --package typescript@5.9.3 tsc ... playwright.config.ts e2e/fixtures.ts e2e/recorded-video.spec.ts
PASS
```

## 未通过/不可执行项

- 完整 Playwright 命令当前真实失败，launcher 返回 exit 2：`unknown option: --keep-running`。主会话已决定由独立 Task 20 扩展实现该 flag；本任务只消费契约，不越界修改 launcher。
- 本机 `docker` 与 `ffmpeg` 均不在 PATH；Chromium executable 也尚未安装。因此当前不能声称真实 E2E 通过，测试没有 skip 或假 pass。
- app `typecheck` 在读取新增文件前即被既有 TypeScript 4.9 与仓库根 `zod/v4` 声明语法不兼容阻断；新增文件另用 TypeScript 5.9 精确检查通过。
- app `lint` 被既有 ESLint 9 配置问题阻断：仓库没有 `eslint.config.js`；未越界迁移 lint 配置。
- `npm install` 在本机 Node 24.17.0 下提示仓库要求 Node 22.22.3，并报告既有依赖树 15 个 audit 项；未执行越界依赖升级。

## 文件

- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/playwright.config.ts`
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/fixtures.ts`
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts`
- `frontend/original-ui/apps/nv-metropolis-bp-vss-ui/package.json`
- `frontend/original-ui/package-lock.json`
- `.superpowers/sdd/task-22-report.md`

`frontend/original-ui/apps/nv-metropolis-bp-vss-ui/test-results/` 是本次运行产物，已清理且不会提交；未修改或删除 `.runtime/`。

## Playwright review repair round 1 (2026-07-16)

### Repaired behavior

- The success flow no longer selects the first search result. It locates the MP4 and MKV cards independently by their exact uploaded filenames.
- Each named card now proves its own thumbnail loaded, extracts the card's asset identity from the thumbnail URL, and waits for the VST resolver request for that same asset.
- Each card also proves the modal title retains the filename identity, the rendered source matches the real resolver response (including the media fragment), and its own `Range: bytes=0-9` request returns HTTP 206, a valid `Content-Range`, and 10 bytes.
- The cancellation flow parses and validates the non-empty `job_id` and `status_url` from the real `/complete` 202 response. It then waits for the progress-dialog `Processing` state committed together with that job id, installs the response waiter before clicking, and asserts the exact `/jobs/{job_id}/cancel` request plus the successful response body.
- No Playwright route or API mocks were added.

### RED and GREEN evidence

RED static review failed with five expected findings:

```text
search result still selects .first()
MP4/MKV are not validated independently by identity
complete response body is not parsed
cancel is not bound to returned job_id
cancel response body is not asserted
```

After the repair, the same static review contract passed.

```text
static review contract passed

npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts --list
Total: 3 tests in 1 file (PASS)

npx --yes --package typescript@5.9.3 tsc ... playwright.config.ts e2e/fixtures.ts e2e/recorded-video.spec.ts
PASS

npm --prefix frontend/original-ui run test --workspace nv-metropolis-bp-vss-ui
85 passed, 1 Playwright-only placeholder skipped (PASS)

npx prettier --check apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts
PASS

git diff --check
PASS
```

### Gates not executable

- Full E2E was not run because all three local prerequisites are absent: `docker` is not on PATH, `ffmpeg` is not on PATH, and the configured Playwright Chromium executable does not exist.
- The app TypeScript 4.9 `typecheck` remains blocked before reaching the E2E files by the existing `zod/v4` declaration syntax incompatibility. The targeted TypeScript 5.9 check passed.
- The app lint gate remains blocked by the existing ESLint 9 setup because no `eslint.config.js`, `.mjs`, or `.cjs` exists.
- `.runtime/` was not read, modified, deleted, staged, or committed.

## Playwright review repair round 2 (2026-07-16)

### Repaired behavior

- The MP4/MKV success flow captures both real `POST /api/v1/videos/{asset_id}/complete` 202 responses and identifies each response by the filename in its real request body.
- Each completion validates non-empty `asset_id`, `job_id`, and `status_url`, the concrete `queued` status, the asset identity in the request path, and the exact `/api/v1/jobs/{job_id}` status URL.
- The search-card media helper now returns its thumbnail-derived asset ID. The test binds the MP4 card to the MP4 completion, binds the MKV card to the MKV completion, and proves the two assets and jobs are distinct.
- The cancellation flow no longer treats UI text as job binding. After parsing the real completion, it waits for a real GET 200 response at that exact `status_url`, then asserts the poll body belongs to the same asset/job and is in `queued`, `running`, or `retry_wait`.
- Only after the matching non-terminal poll is observed does the test install the exact cancel response waiter and click `Cancel All`. It asserts the POST path, absent request body, HTTP 200, matching asset/job, and `running` or `cancelled` response status.
- No Playwright route or API mocks were added.

### RED and GREEN evidence

The read-only static review contract failed against the round-1 implementation with all five expected findings:

```text
MISSING: captures two accepted completion responses
MISSING: validates complete asset_id/job_id/status/status_url
MISSING: returns the card-derived asset identity
MISSING: binds MP4 and MKV cards to distinct completion assets
MISSING: poll-binds exact job before installing cancel waiter
Exit 1
```

After the minimal spec repair and formatting, the same five behavioral constraints passed:

```text
static review contract passed

npm --prefix frontend/original-ui run test:e2e --workspace nv-metropolis-bp-vss-ui -- recorded-video.spec.ts --list
Total: 3 tests in 1 file (PASS)

npx --yes --package typescript@5.9.3 tsc --noEmit --target ES2022 --module commonjs --moduleResolution node --esModuleInterop --skipLibCheck --types node,jest --typeRoots "node_modules/@types,apps/nv-metropolis-bp-vss-ui/node_modules/@types" apps/nv-metropolis-bp-vss-ui/playwright.config.ts apps/nv-metropolis-bp-vss-ui/e2e/fixtures.ts apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts
PASS

npm --prefix frontend/original-ui run test --workspace nv-metropolis-bp-vss-ui
85 passed, 1 Playwright-only placeholder skipped (PASS)

npx prettier --check apps/nv-metropolis-bp-vss-ui/e2e/recorded-video.spec.ts
PASS

git diff --check
PASS (Windows LF-to-CRLF working-copy warning only)
```

### Full E2E dependency gate

- Full Playwright E2E was not run and is not reported as passing: `docker` and `ffmpeg` are absent from PATH, and the local Playwright browser cache is absent.
- The existing launcher/backend/validator/OpenSpec/plan/runtime files were not modified as part of this repair.
