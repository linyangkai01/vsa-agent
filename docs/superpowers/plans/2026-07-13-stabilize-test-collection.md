---
change: stabilize-test-contracts
design-doc: docs/superpowers/specs/2026-07-13-stabilize-test-collection-design.md
base-ref: 981007bf0a371f6e1385d3cae171af22db41db18
---

# 测试收集稳定化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除同名测试文件的 pytest 模块身份冲突，并恢复全量测试收集门禁。

**Architecture:** 沿用现有 `tests` 与 `tests.unit` 包结构，只为发生同名冲突的叶级测试目录增加包边界。生产代码、pytest 全局导入模式和测试文件名保持不变。

**Tech Stack:** Python 3.12、pytest 8、PowerShell、Git。

## Global Constraints

- 不修改 `src/` 运行时行为。
- 不跳过、排除或重命名现有测试。
- 保留未归属本 change 的 `recorded_video` 工作区修改。

---

### Task 1: 证明并定位模块身份冲突

**Files:**
- Inspect: `tests/unit/archive/test_models.py`
- Inspect: `tests/unit/recorded_video/test_models.py`

**Interfaces:**
- Consumes: pytest 默认测试收集规则。
- Produces: 需要包边界的目录清单。

- [ ] **Step 1: 运行组合收集并验证 RED**

Run: `pytest --collect-only -q tests/unit/archive/test_models.py tests/unit/recorded_video/test_models.py`

Expected: FAIL with `import file mismatch` and both paths in the diagnostic.

- [ ] **Step 2: 扫描重复 basename**

Run a PowerShell grouping over tracked `tests/**/*.py` files and list names whose count is greater than one. For each duplicate, record whether its parent contains `__init__.py`.

Expected: `test_models.py` includes the archive and recorded-video directories, and the two directories lack package markers.

### Task 2: 增加最小测试包边界

**Files:**
- Create: `tests/unit/archive/__init__.py`
- Create: `tests/unit/recorded_video/__init__.py`

**Interfaces:**
- Consumes: existing parent packages `tests` and `tests.unit`.
- Produces: module names `tests.unit.archive.test_models` and `tests.unit.recorded_video.test_models`.

- [ ] **Step 1: 创建空包初始化文件**

Create both files as empty Python package markers. Do not add runtime imports or comments.

- [ ] **Step 2: 运行组合收集并验证 GREEN**

Run: `pytest --collect-only -q tests/unit/archive/test_models.py tests/unit/recorded_video/test_models.py`

Expected: PASS and collect all tests from both files without mismatch.

- [ ] **Step 3: 运行组合测试**

Run: `pytest -q tests/unit/archive/test_models.py tests/unit/recorded_video/test_models.py`

Expected: PASS with all tests from both files executed.

### Task 3: 全量验证与状态更新

**Files:**
- Modify: `openspec/changes/stabilize-test-contracts/tasks.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: stable package identities from Task 2.
- Produces: verified repository test baseline and durable status record.

- [ ] **Step 1: 运行全量收集**

Run: `pytest --collect-only -q`

Expected: PASS without import mismatch.

- [ ] **Step 2: 运行全量测试**

Run: `pytest -q`

Expected: PASS; conditional skips remain skips rather than failures.

- [ ] **Step 3: 更新状态和任务**

Record the root cause, package-boundary fix, exact commands, counts and date in `docs/DEVELOPMENT_STATUS.md`. Mark each verified OpenSpec task complete only after its command passes.

- [ ] **Step 4: 提交 change 文件**

Run: `git add tests/unit/archive/__init__.py tests/unit/recorded_video/__init__.py openspec/changes/stabilize-test-contracts docs/superpowers/specs/2026-07-13-stabilize-test-collection-design.md docs/superpowers/plans/2026-07-13-stabilize-test-collection.md docs/DEVELOPMENT_STATUS.md`

Run: `git commit -m "test: stabilize pytest module collection"`

Expected: commit contains only this change and its planning/status artifacts.
