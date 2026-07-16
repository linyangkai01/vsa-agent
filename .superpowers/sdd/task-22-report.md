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
