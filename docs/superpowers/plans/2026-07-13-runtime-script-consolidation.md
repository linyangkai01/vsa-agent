---
change: consolidate-runtime-scripts
design-doc: docs/superpowers/specs/2026-07-13-runtime-script-consolidation-design.md
base-ref: 86c3ee51b3fa108310d04c5d1eb14225f1c33cbe
---

# 运行脚本整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留全部受支持脚本入口，同时消除两个 DashScope wrapper 的公共前置重复并建立可审计清单。

**Architecture:** 新增一个被 source 的 Bash helper，输出带前缀的统一运行时解析结果；两个用户 wrapper 显式映射旧变量并保留各自目标命令。ES、UI、smoke、安装和同步入口仅记录职责，不改动实现。

**Tech Stack:** Bash、PowerShell、Python 3.12、pytest 8、Ruff。

## Global Constraints

- 不修改 `frontend/original-ui` 内部源码。
- 保留现有 14 个用户入口、命令参数、错误码和目标流程。
- 不修改 `es-runtime-stack.*` 的实现或同步生命周期；允许修复 `sync-server-files.ps1` manifest 中的陈旧文件路径。
- 不使用 `eval`，不读取或写入 `.env`，不输出 API key。
- 删除脚本前必须迁移全部调用者并证明全仓引用数为零；本轮无删除候选。

---

### Task 1: 固化共享前置契约

**Files:**
- Modify: `tests/unit/test_dashscope_live_runner.py`
- Create: `docs/superpowers/reference/runtime-scripts.md`

**Interfaces:**
- Consumes: 两个现有 DashScope wrapper 和 14 个脚本入口。
- Produces: `scripts/lib/dashscope_runtime.sh` 的结构契约与脚本审计清单。

- [x] **Step 1: 添加失败测试**

测试必须断言：helper 文件存在；两个 wrapper source `lib/dashscope_runtime.sh`；`DASHSCOPE_API_KEY` 前置 guard 和 `config doctor` 只由 helper 持有；wrapper 仍包含各自的 pytest 或 `live_video_acceptance` 目标命令。

- [x] **Step 2: 验证 Red**

Run: `pytest -q tests/unit/test_dashscope_live_runner.py`

Expected: FAIL，因为 helper 尚不存在，wrapper 仍内联公共前置逻辑。

- [x] **Step 3: 写入脚本清单**

创建表格，列出 14 个入口的脚本名、平台、职责、调用依据、验证命令和结论；两个 DashScope wrapper 标记为“保留入口、合并内部前置”，其他入口标记为“保留”，删除候选写“无”。

- [x] **Step 4: 提交契约与清单**

Run: `git add tests/unit/test_dashscope_live_runner.py docs/superpowers/reference/runtime-scripts.md && git commit -m "test: define runtime script consolidation contract"`

### Task 2: 实现公共 helper 与薄 wrapper

**Files:**
- Create: `scripts/lib/dashscope_runtime.sh`
- Modify: `scripts/run_live_acceptance_dashscope.sh`
- Modify: `scripts/run_live_top_agent_video_dashscope.sh`
- Test: `tests/unit/test_dashscope_live_runner.py`

**Interfaces:**
- Produces: `vsa_dashscope_preflight() -> shell status`。
- Exports: `VSA_REPO_ROOT`、`VSA_CONFIG`、`VSA_CONDA_ENV`、`VSA_PROFILE`、`VSA_RESOLVED_LLM_API_KEY`、`VSA_RESOLVED_LLM_BASE_URL`、`VSA_RESOLVED_LLM_MODEL`。

- [x] **Step 1: 实现最小公共前置**

helper 使用自身 `BASH_SOURCE[0]` 解析仓库根目录，按 Conda、配置、环境 key 顺序失败；设置公共默认值，执行 `config doctor`/`config print`，通过现有 `resolve_runtime_config` 分别解析 key、base URL 和 model，空 key 返回状态 2。

- [x] **Step 2: 将 evaluator wrapper 变薄**

wrapper 只解析 `SCRIPT_DIR`、source helper、设置 trace 默认值、调用 `vsa_dashscope_preflight`、映射三个 `LIVE_API_*` 变量并运行 `tests/acceptance/test_evaluator_live_api.py`。

- [x] **Step 3: 将 TopAgent wrapper 变薄**

wrapper source helper 并调用公共前置，保留 `VSA_LIVE_VIDEO_MODE`、视频位置参数、配置默认视频、query 分支和 `--mode`；仅把公共 key 映射到 `OPENAI_API_KEY`。

- [x] **Step 4: 验证 Green 与 Bash 语法**

Run: `pytest -q tests/unit/test_dashscope_live_runner.py`

Run: `Get-ChildItem scripts -Recurse -Filter *.sh | ForEach-Object { bash -n $_.FullName }`

Expected: tests PASS；所有 Bash 文件语法检查退出 0。

- [x] **Step 5: 提交实现**

Run: `git add scripts/lib/dashscope_runtime.sh scripts/run_live_acceptance_dashscope.sh scripts/run_live_top_agent_video_dashscope.sh tests/unit/test_dashscope_live_runner.py && git commit -m "refactor: share DashScope runtime preflight"`

### Task 3: 完整脚本与仓库门禁

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `openspec/changes/consolidate-runtime-scripts/tasks.md`

**Interfaces:**
- Consumes: 清单、helper 和两个薄 wrapper。
- Produces: 脚本解析、定向测试、全量测试和同步 preflight 证据。

- [x] **Step 1: 验证全部脚本语法**

Run: `Get-ChildItem scripts -Recurse -Filter *.sh | ForEach-Object { bash -n $_.FullName }`

Run: `Get-ChildItem scripts -Recurse -Filter *.ps1 | ForEach-Object { [void][scriptblock]::Create((Get-Content -Raw $_.FullName)) }`

Expected: 所有解析命令退出 0。

- [x] **Step 2: 运行脚本定向测试**

Run: `pytest -q tests/unit/test_dashscope_live_runner.py tests/unit/scripts`

Expected: all selected tests pass。

- [x] **Step 3: 运行 Python 质量与全量测试**

Run: `ruff check src tests`

Run: `ruff format --check src tests`

Run: `pytest -q`

Expected: Ruff 零问题、格式一致、全量测试无失败。

- [x] **Step 4: 运行同步前检查**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-server-files.ps1 -PreflightOnly`

Expected: preflight 成功；若映射服务器不可写，记录环境阻塞，不修改同步脚本或伪造 smoke 结果。

- [x] **Step 5: 更新状态并提交**

记录清单结论、命令与计数，勾选 OpenSpec 和本计划任务。

Run: `git add docs/DEVELOPMENT_STATUS.md openspec/changes/consolidate-runtime-scripts docs/superpowers/plans/2026-07-13-runtime-script-consolidation.md && git commit -m "docs: record runtime script consolidation"`
