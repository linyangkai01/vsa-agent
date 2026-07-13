---
change: enforce-python-quality-baseline
design-doc: docs/superpowers/specs/2026-07-13-python-quality-baseline-design.md
base-ref: 17f221c1d21780492bbe32e8c1ecea1db83c9fef
archived-with: 2026-07-13-enforce-python-quality-baseline
---

# Python 质量基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `src/` 与 `tests/` 同时通过 Ruff lint、Ruff format 和全量 pytest 门禁。

**Architecture:** 保持现有规则集合和 120 列限制，按配置迁移、安全修复、格式化、人工语义审查四层推进。注册副作用和稳定字符串在人工层保护，结构重构留给后续 change。

**Tech Stack:** Python 3.12、Ruff 0.12、pytest 8、Pydantic/LangChain/FastAPI。

## Global Constraints

- 仅处理 `src/` 与 `tests/`，排除 `frontend/original-ui`。
- 不使用 Ruff unsafe fixes，不新增大范围 ignore。
- 不改变公开 API、数据模型、prompt 内容或工具/代理注册行为。
- 当前 Red：308 个 lint 问题，125 个文件需要格式化。

archived-with: 2026-07-13-enforce-python-quality-baseline
---

### Task 1: 迁移 Ruff 配置

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/unit/test_registry.py`
- Test: `tests/unit/test_prompt.py`

**Interfaces:**
- Consumes: `[tool.ruff] line-length = 120` and rules `E,F,I,N,W,UP`.
- Produces: `[tool.ruff.lint] select = ["E", "F", "I", "N", "W", "UP"]` with identical policy.

- [x] **Step 1: 运行配置 Red**

Run: `ruff check src tests --output-format concise`

Expected: FAIL and print the deprecated top-level `select` warning plus lint findings.

- [x] **Step 2: 迁移配置键**

Move only `select` from `[tool.ruff]` to a new `[tool.ruff.lint]` table. Keep `line-length = 120` under `[tool.ruff]`.

- [x] **Step 3: 验证配置警告消失**

Run: `ruff check src tests --output-format concise`

Expected: still FAIL for source findings, but no deprecated top-level linter settings warning.

### Task 2: 应用安全机械修复和格式化

**Files:**
- Modify: Python files reported by Ruff under `src/` and `tests/`.

**Interfaces:**
- Consumes: Ruff safe-fix metadata and formatter.
- Produces: sorted imports, modern annotations/imports and canonical formatting without unsafe rewrites.

- [x] **Step 1: 应用安全修复**

Run: `ruff check src tests --fix`

Expected: safe fixable findings are removed; no `--unsafe-fixes` is used.

- [x] **Step 2: 运行格式化**

Run: `ruff format src tests`

Expected: all controlled Python files are reformatted once.

- [x] **Step 3: 验证机械修改语法和核心契约**

Run: `python -m compileall -q src tests`

Run: `pytest -q tests/unit/test_registry.py tests/unit/test_prompt.py tests/unit/test_config.py tests/unit/tools/test_register.py`

Expected: compileall exits 0 and targeted tests pass. If `tests/unit/tools/test_register.py` is absent, run the existing registry tests only and record the actual command.

### Task 3: 人工清理剩余问题

**Files:**
- Modify: files still reported by `ruff check src tests` after Task 2.
- Test: nearest unit tests for every changed source module.

**Interfaces:**
- Consumes: remaining `E501`, `F401`, `F841`, `N802` or non-auto-fix findings.
- Produces: zero lint findings while preserving runtime strings and side effects.

- [x] **Step 1: 导出剩余问题清单**

Run: `ruff check src tests --output-format concise`

Expected: FAIL only for findings that require human review.

- [x] **Step 2: 修复未使用导入和变量**

For ordinary modules remove genuinely unused symbols. For registration modules preserve import side effects using explicit redundant aliases or narrow `# noqa: F401`. Remove the unused `normalized_output` local only after confirming no trace/artifact consumer uses it.

- [x] **Step 3: 修复命名与长行**

Wrap expressions and stable strings without changing runtime content. For test fakes that must implement OpenCV camelCase methods such as `isOpened`, add a narrow `# noqa: N802` on that method rather than renaming the protocol member.

- [x] **Step 4: 运行受影响模块测试**

Run the nearest unit test files named by each modified source path, with at minimum registry, config, prompt, video understanding, search, API and recorded-video tests.

Expected: all selected tests pass.

### Task 4: 完整门禁与提交

**Files:**
- Modify: `openspec/changes/enforce-python-quality-baseline/tasks.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: cleaned and formatted Python tree.
- Produces: durable zero-debt baseline and validation record.

- [x] **Step 1: 运行 lint 门禁**

Run: `ruff check src tests`

Expected: `All checks passed!` and exit 0.

- [x] **Step 2: 运行 format 门禁**

Run: `ruff format --check src tests`

Expected: all files already formatted and exit 0.

- [x] **Step 3: 运行全量测试**

Run: `pytest -q`

Expected: all non-conditional tests pass.

- [x] **Step 4: 更新状态并提交**

Record final Ruff counts, format counts, pytest counts and commands in `docs/DEVELOPMENT_STATUS.md`; check off OpenSpec and plan tasks.

Run: `git add pyproject.toml src tests docs/DEVELOPMENT_STATUS.md docs/superpowers/specs/2026-07-13-python-quality-baseline-design.md docs/superpowers/plans/2026-07-13-python-quality-baseline.md openspec/changes/enforce-python-quality-baseline`

Run: `git commit -m "style: enforce Python quality baseline"`

Expected: commit excludes the other active change directories.
