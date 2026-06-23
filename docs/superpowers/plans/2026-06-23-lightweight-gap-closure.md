# Lightweight Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐当前剩余的轻量缺口模块，并把计划文档与验证状态同步到最新仓库实现。

**Architecture:** 这次只处理彼此独立、对主链低风险的轻量模块，不改现有搜索/报告主编排。每个任务都走最小 TDD 闭环：先锁测试，再补实现，最后做定向回归与文档同步。

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, Pydantic, OpenAI-compatible client, existing `vsa_agent` registry/tools/embed patterns

## Global Constraints

- 保持现有公开接口风格，优先复用 `register_tool`、`EmbedClient`、`format_timestamp`、`frames_to_seconds`
- 只补最小可信实现，不引入新的重量级依赖
- 新增模块必须带对应单测，并在 `vsa-agent` conda 环境里验证
- 文档只同步本轮确实完成并验证过的内容

---

### Task 1: 补齐 `RTVICVEmbedClient`

**Files:**
- Create: `src/vsa_agent/embed/rtvi_cv_embed.py`
- Modify: `src/vsa_agent/embed/__init__.py`
- Test: `tests/unit/embed/test_rtvi_cv_embed.py`

**Interfaces:**
- Consumes: `EmbedClient`, `get_config()`, `httpx.AsyncClient`, `openai.AsyncOpenAI`
- Produces: `RTVICVEmbedClient.embed(inputs: Sequence[str]) -> list[list[float]]`, `RTVICVEmbedClient.embed_query(query: str) -> list[float]`

- [ ] **Step 1: 写失败测试**

```python
def test_initialization():
    from vsa_agent.embed.rtvi_cv_embed import RTVICVEmbedClient

    client = RTVICVEmbedClient(
        model="text-embedding-3-small",
        base_url="https://example.com/v1",
        api_key="test-key",
    )

    assert client.dimension == 1536
```

- [ ] **Step 2: 跑测试确认红灯**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/embed/test_rtvi_cv_embed.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
class RTVICVEmbedClient(EmbedClient):
    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        ...

    async def embed_query(self, query: str) -> list[float]:
        ...
```

- [ ] **Step 4: 跑 embed 层回归**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/embed -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/embed/rtvi_cv_embed.py src/vsa_agent/embed/__init__.py tests/unit/embed/test_rtvi_cv_embed.py
git commit -m "feat: add rtvi cv embed client"
```

### Task 2: 补齐 `video_frame_timestamp` 工具

**Files:**
- Create: `src/vsa_agent/tools/video_frame_timestamp.py`
- Test: `tests/unit/tools/test_video_frame_timestamp.py`

**Interfaces:**
- Consumes: `register_tool`, `format_timestamp(seconds, fmt="hh:mm:ss")`, `frames_to_seconds(frame_index, fps)`
- Produces: `frame_indices_to_timestamps(frame_indices: list[int], fps: float, start_seconds: float = 0.0, fmt: str = "hh:mm:ss") -> list[dict[str, float | int | str]]`

- [ ] **Step 1: 写失败测试**

```python
def test_frame_indices_to_timestamps_formats_offsets():
    from vsa_agent.tools.video_frame_timestamp import frame_indices_to_timestamps

    result = frame_indices_to_timestamps([0, 15, 30], fps=30.0, start_seconds=10.0)

    assert result[0]["timestamp"] == "00:00:10"
```

- [ ] **Step 2: 跑测试确认红灯**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_frame_timestamp.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
def frame_indices_to_timestamps(...):
    ...

@register_tool("video_frame_timestamp", ...)
async def video_frame_timestamp_tool(...):
    return frame_indices_to_timestamps(...)
```

- [ ] **Step 4: 跑相关回归**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_frame_timestamp.py tests/unit/tools/test_frame_extract.py tests/unit/utils/test_time_convert.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_frame_timestamp.py tests/unit/tools/test_video_frame_timestamp.py
git commit -m "feat: add video frame timestamp helper"
```

### Task 3: 同步计划文档与定向验证结果

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

**Interfaces:**
- Consumes: 当前仓库实际文件状态与定向测试结果
- Produces: 更新后的 Gap 列表与 Phase 0 状态项

- [ ] **Step 1: 更新 Gap 与 Phase 0.3 状态**

```markdown
- [x] 实现 embed/rtvi_cv_embed.py (OpenAI 替代 RTVI CV)
```

- [ ] **Step 2: 跑本轮定向验证**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/embed tests/unit/tools/test_video_frame_timestamp.py tests/unit/tools/test_frame_extract.py tests/unit/utils/test_time_convert.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: sync lightweight gap closure progress"
```
