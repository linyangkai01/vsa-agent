---
change: refactor-search-orchestration
design-doc: docs/superpowers/specs/2026-07-13-search-orchestration-design.md
base-ref: 45f2bf7a03d741a728ac5d1149e99896e93e8b3e
---

# 搜索编排重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将搜索路由、结果归一化、去重、回退、critic 过滤和裁剪提取为纯规则，同时保持异步消息与公开搜索契约。

**Architecture:** `search_pipeline.py` 不导入 facade 模型，只消费结构化属性并返回新列表；`search.py` 保留模型、外部 I/O、日志、进度消息、融合公式和注册入口。core、fusion 和工具路径复用统一 helper。

**Tech Stack:** Python 3.12、Pydantic 2、pytest 8、Ruff。

## Global Constraints

- 不改变 `SearchInput`、`SearchOutput`、`SearchResult`、`execute_core_search`、`search_tool` 或 agent/API 签名。
- 不改变排序公式、阈值、top_k、critic 启用条件、进度消息顺序或错误降级。
- 不改变 Elasticsearch schema、embed/attribute 后端协议或工具注册名称。
- 纯模块不得执行外部 I/O，不得反向导入 `search.py`。
- `frontend/original-ui` 不在范围内。

---

### Task 1: 锁定纯搜索规则

**Files:**
- Create: `tests/unit/tools/test_search_pipeline.py`

**Interfaces:**
- Produces: 路由、归一化、去重、回退、过滤和裁剪的表驱动契约。

- [x] **Step 1: 写失败测试**

从 `vsa_agent.tools.search_pipeline` 导入 `select_search_route`、`normalize_search_results`、`rank_unique_results`、`select_fusion_results`、`filter_rejected_sensors`、`trim_search_results` 和 `should_apply_critic`。

- [x] **Step 2: 覆盖规则矩阵**

使用 `SearchOutput`、`SimpleNamespace(data=...)`、列表和 `None`；覆盖四种路由结果、同视频高分保留、降序、低置信度属性回退、critic sensor 过滤、top_k 和输入列表不变。

- [x] **Step 3: 验证 Red**

Run: `pytest -q tests/unit/tools/test_search_pipeline.py`

Expected: collection FAIL with `ModuleNotFoundError`。

- [x] **Step 4: 提交测试**

Run: `git add tests/unit/tools/test_search_pipeline.py && git commit -m "test: characterize search pipeline rules"`

### Task 2: 实现纯规则并接入搜索 facade

**Files:**
- Create: `src/vsa_agent/tools/search_pipeline.py`
- Modify: `src/vsa_agent/tools/search.py`
- Test: `tests/unit/tools/test_search_pipeline.py`
- Test: `tests/unit/tools/test_search.py`

**Interfaces:**
- Produces: 设计文档列出的七个 helper 和 `should_apply_critic`。
- Facade: 重导出 `should_apply_critic`，保留其他公开/测试 import。

- [x] **Step 1: 实现纯模块**

helper 仅读取 `.data`、`video_name`、`similarity`、`sensor_id`，总是复制列表；不支持形状返回空列表，空结果不计算最大分数。

- [x] **Step 2: 收敛 `execute_core_search`**

用 route helper 选择阶段，用统一归一化消费 attribute/embed 返回，用 fusion helper 合并或回退，用 critic filter 移除拒绝项，用 trim helper 构造最终输出。保留原 try/except、日志和 yield 文本。

- [x] **Step 3: 复用到其他 facade 路径**

`fusion_search_rerank` 和 `_run_attribute_only_search` 用统一归一化；注册 `search_tool` 的 fusion 分支用统一归一化和 `rank_unique_results`，不改变 weighted/RRF 公式函数。

- [x] **Step 4: 验证 Green**

Run: `pytest -q tests/unit/tools/test_search_pipeline.py tests/unit/tools/test_search.py`

Expected: all selected tests pass。

- [x] **Step 5: 静态检查并提交**

Run: `ruff check src/vsa_agent/tools/search.py src/vsa_agent/tools/search_pipeline.py tests/unit/tools/test_search_pipeline.py`

Run: `ruff format --check src/vsa_agent/tools/search.py src/vsa_agent/tools/search_pipeline.py tests/unit/tools/test_search_pipeline.py`

Run: `git add src/vsa_agent/tools/search.py src/vsa_agent/tools/search_pipeline.py tests/unit/tools/test_search_pipeline.py && git commit -m "refactor: isolate search pipeline rules"`

### Task 3: 搜索路径矩阵与完整门禁

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `openspec/changes/refactor-search-orchestration/tasks.md`

**Interfaces:**
- Consumes: 新纯规则模块与稳定 facade。
- Produces: 工具、agent、API、acceptance 与全仓证据。

- [ ] **Step 1: 运行搜索路径矩阵**

Run: `pytest -q tests/unit/tools/test_search_pipeline.py tests/unit/tools/test_search.py tests/unit/tools/test_embed_search.py tests/unit/tools/test_attribute_search.py tests/unit/agents/test_search_agent.py tests/unit/api/test_original_ui_search_route.py tests/acceptance/test_search_flow.py`

Expected: attribute-only、embed-only、fusion、critic、低置信度、空结果与异常降级全部通过。

- [ ] **Step 2: 运行仓库门禁**

Run: `python -m compileall -q src tests`

Run: `ruff check src tests`

Run: `ruff format --check src tests`

Run: `pytest -q`

Expected: compileall 与 Ruff 通过，全量 pytest 无失败。

- [ ] **Step 3: 更新状态并提交**

记录纯规则边界、保留的 facade/critic/日志行为和测试计数；勾选 OpenSpec 与计划任务，记录未授权多代理 reviewer。

Run: `git add docs/DEVELOPMENT_STATUS.md openspec/changes/refactor-search-orchestration docs/superpowers/plans/2026-07-13-search-orchestration.md && git commit -m "docs: record search orchestration refactor"`
