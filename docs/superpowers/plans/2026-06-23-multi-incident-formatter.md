# Multi Incident Formatter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `multi_incident_formatter.py`，把多事件列表统一格式化成稳定的 markdown 文本块，供报告链和后续闭环复用。

**Architecture:** 这一轮不重构现有报告主链，只新增一个小而纯的格式化模块。格式化器接收 `ReportIncident` 或兼容字典，按时间窗口、类别、描述输出稳定 markdown；工具层只做最小包装，保证未来 `report_gen`、`template_report_gen` 或搜索摘要链可以直接调用。

**Tech Stack:** Python 3.12, pytest, Pydantic v2, existing `ReportIncident` / `Incident` models, existing tool registration pattern

## Global Constraints

- 只新增一个独立纯格式化模块，不改现有主编排
- 先写失败测试，再补最小实现
- 格式化输出必须稳定、可预测，便于后续报告模板直接消费
- 所有验证都在 `vsa-agent` conda 环境中完成

---

### Task 1: 实现多事件 markdown 格式化核心

**Files:**
- Create: `src/vsa_agent/tools/multi_incident_formatter.py`
- Test: `tests/unit/tools/test_multi_incident_formatter.py`

**Interfaces:**
- Consumes: `ReportIncident`, plain `dict` incidents
- Produces: `format_multi_incidents(incidents: list[ReportIncident | dict], heading: str = "事件列表") -> str`

- [ ] **Step 1: 写失败测试**

```python
def test_format_multi_incidents_renders_markdown_sections():
    from vsa_agent.data_models.report import ReportIncident
    from vsa_agent.tools.multi_incident_formatter import format_multi_incidents

    result = format_multi_incidents(
        [
            ReportIncident(
                incident_id="inc-1",
                category="intrusion",
                description="person enters restricted area",
                severity="high",
                confidence=0.91,
                start_timestamp="2026-06-23T10:00:00",
                end_timestamp="2026-06-23T10:00:08",
            )
        ]
    )

    assert "## 事件列表" in result
    assert "intrusion" in result
    assert "person enters restricted area" in result
```

- [ ] **Step 2: 跑测试确认红灯**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_multi_incident_formatter.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
def format_multi_incidents(...):
    ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_multi_incident_formatter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/multi_incident_formatter.py tests/unit/tools/test_multi_incident_formatter.py
git commit -m "feat: add multi incident formatter"
```

### Task 2: 增加工具包装与空输入语义

**Files:**
- Modify: `src/vsa_agent/tools/multi_incident_formatter.py`
- Test: `tests/unit/tools/test_multi_incident_formatter.py`

**Interfaces:**
- Consumes: `format_multi_incidents(...)`
- Produces: `multi_incident_formatter_tool(incidents: list[dict] | None = None, heading: str = "事件列表") -> str`

- [ ] **Step 1: 写失败测试**

```python
def test_multi_incident_formatter_tool_returns_fallback_for_empty_input():
    from vsa_agent.tools.multi_incident_formatter import multi_incident_formatter_tool

    result = asyncio.run(multi_incident_formatter_tool())

    assert result == "## 事件列表\n\n- 无事件"
```

- [ ] **Step 2: 跑测试确认红灯**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_multi_incident_formatter.py -q`
Expected: FAIL because tool wrapper does not exist yet

- [ ] **Step 3: 写最小实现**

```python
@register_tool("multi_incident_formatter", ...)
async def multi_incident_formatter_tool(...):
    ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_multi_incident_formatter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/multi_incident_formatter.py tests/unit/tools/test_multi_incident_formatter.py
git commit -m "feat: add multi incident formatter tool wrapper"
```

### Task 3: 同步 Gap 文档并跑定向回归

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

**Interfaces:**
- Consumes: 当前仓库文件状态、formatter 测试结果
- Produces: 更新后的 Gap 列表

- [ ] **Step 1: 从 Gap 中移除 `tools/multi_incident_formatter.py`**

```markdown
| tools/multi_incident_formatter.py | multi_incident_formatter.py | 多事件格式化 | P2 |
```

- [ ] **Step 2: 跑定向回归**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_multi_incident_formatter.py tests/unit/tools/test_report_gen.py tests/unit/tools/test_template_report_gen.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: sync multi incident formatter progress"
```
