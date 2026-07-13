---
change: refactor-video-understanding-pipeline
design-doc: docs/superpowers/specs/2026-07-13-video-understanding-pipeline-design.md
base-ref: e06300d2a99dc790de4203d4e2d5de561e773bb1
---

# 视频理解管线重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将视频理解纯转换从 I/O facade 中提取出来，同时保持所有入口、结果和 monkeypatch 路径兼容。

**Architecture:** 新模块拥有时间、reasoning、证据、事件和模型结果转换；原 facade 显式重导出相同 helper 对象并继续承载帧、VLM、source 和工具编排。LVS 直接依赖纯时间 helper，避免反向导入整个 facade。

**Tech Stack:** Python 3.12、Pydantic 2、pytest 8、Ruff。

## Global Constraints

- 不改变 `video_understanding_tool`、`analyze_video`、`analyze_video_segment` 或 LVS 公共签名。
- 不改变共享数据模型、prompt、长视频阈值、帧选择、trace/artifact 事件或错误类别。
- 保留 `vsa_agent.tools.video_understanding` 下现有私有 helper import 路径。
- 纯模块不得依赖 cv2、网络、全局配置或 trace/artifact I/O。
- `frontend/original-ui` 不在范围内。

---

### Task 1: 锁定纯规范化模块契约

**Files:**
- Create: `tests/unit/tools/test_video_understanding_normalization.py`

**Interfaces:**
- Consumes: 现有 facade helper 行为。
- Produces: 新模块 import、纯依赖和 facade identity 契约。

- [x] **Step 1: 写失败测试**

测试从 `vsa_agent.tools.video_understanding_normalization` 导入 `_normalize_timestamp`、`_timestamp_to_seconds`、`_parse_thinking_from_content` 和 `_normalize_model_response`；断言模块没有 `cv2`、`get_config`、`write_live_trace_event`；断言 facade 对应 helper 与新模块对象相同。

- [x] **Step 2: 增加结构 characterization**

覆盖：数值时间；PT duration；`<thinking>/<answer>`；既有 `UnderstandingResult` identity；字典默认 query/source；字符串生成文件 `video_path` 证据和 RTSP `sensor_id` 证据。

- [x] **Step 3: 验证 Red**

Run: `pytest -q tests/unit/tools/test_video_understanding_normalization.py`

Expected: collection FAIL with `ModuleNotFoundError`，因为纯模块尚不存在。

- [x] **Step 4: 提交测试**

Run: `git add tests/unit/tools/test_video_understanding_normalization.py && git commit -m "test: characterize video understanding normalization"`

### Task 2: 提取规范化实现并保留 facade

**Files:**
- Create: `src/vsa_agent/tools/video_understanding_normalization.py`
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `src/vsa_agent/tools/lvs_video_understanding.py`
- Test: `tests/unit/tools/test_video_understanding_normalization.py`
- Test: `tests/unit/tools/test_video_understanding.py`
- Test: `tests/unit/tools/test_lvs_video_understanding.py`

**Interfaces:**
- Produces: 原 helper 签名和新 `_build_evidence(...) -> EvidenceRef`。
- Facade: 从纯模块导入原 helper 名称，不定义第二份实现。

- [x] **Step 1: 移动纯函数**

将时间转换、reasoning 分离、事件提取和模型响应转换移动到新模块。新增 `_build_evidence` 统一 source-specific 字段，保留原默认值、事件 ID、metadata 和字典/既有结果分支。

- [x] **Step 2: 建立 facade 兼容导入**

从新模块显式导入 `_normalize_model_response`、`_normalize_timestamp`、`_parse_thinking_from_content`、`_timestamp_to_seconds`；删除 facade 中重复实现和不再使用的数据模型/时间转换导入。

- [x] **Step 3: 解除 LVS 反向依赖**

将 LVS 的 `_timestamp_to_seconds` import 改为 `video_understanding_normalization`，`analyze_video_segment` 仍从 facade 导入以保留动态调用路径。

- [x] **Step 4: 验证 Green**

Run: `pytest -q tests/unit/tools/test_video_understanding_normalization.py tests/unit/tools/test_video_understanding.py tests/unit/tools/test_lvs_video_understanding.py`

Expected: all selected tests pass。

- [x] **Step 5: 运行静态门禁并提交**

Run: `ruff check src/vsa_agent/tools/video_understanding.py src/vsa_agent/tools/video_understanding_normalization.py src/vsa_agent/tools/lvs_video_understanding.py tests/unit/tools/test_video_understanding_normalization.py`

Run: `ruff format --check src/vsa_agent/tools/video_understanding.py src/vsa_agent/tools/video_understanding_normalization.py src/vsa_agent/tools/lvs_video_understanding.py tests/unit/tools/test_video_understanding_normalization.py`

Run: `git add src/vsa_agent/tools/video_understanding.py src/vsa_agent/tools/video_understanding_normalization.py src/vsa_agent/tools/lvs_video_understanding.py tests/unit/tools/test_video_understanding_normalization.py && git commit -m "refactor: isolate video understanding normalization"`

### Task 3: 路径矩阵与完整门禁

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `openspec/changes/refactor-video-understanding-pipeline/tasks.md`

**Interfaces:**
- Consumes: 新纯模块与稳定 facade。
- Produces: 路径矩阵、静态门禁和全量测试证据。

- [x] **Step 1: 运行视频路径矩阵**

Run: `pytest -q tests/unit/tools/test_video_understanding_normalization.py tests/unit/tools/test_video_understanding.py tests/unit/tools/test_video_understanding_live_trace.py tests/unit/tools/test_lvs_video_understanding.py tests/unit/data_models/test_understanding_models.py tests/acceptance/test_video_understanding_flow.py`

Expected: 文件、帧输入、RTSP、短视频、长视频、LVS、trace 和共享模型测试全部通过。

- [x] **Step 2: 运行仓库门禁**

Run: `python -m compileall -q src tests`

Run: `ruff check src tests`

Run: `ruff format --check src tests`

Run: `pytest -q`

Expected: compileall 与 Ruff 通过，全量 pytest 无失败。

- [x] **Step 3: 更新状态与任务**

记录新模块边界、保留 facade/LVS 路径和测试计数；勾选 OpenSpec 与本计划任务，并记录未授权多代理 reviewer。

- [x] **Step 4: 提交收尾**

Run: `git add docs/DEVELOPMENT_STATUS.md openspec/changes/refactor-video-understanding-pipeline docs/superpowers/plans/2026-07-13-video-understanding-pipeline.md && git commit -m "docs: record video understanding refactor"`
