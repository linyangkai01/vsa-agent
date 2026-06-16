# Phase 3 Single Video Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 `report_agent + video_report_gen` 的单视频报告主链，输出固定模板的 Markdown 报告和可扩展下载元数据。

**Architecture:** 这一版只覆盖“单视频/上传视频报告”路径，不引入 incident 查询和多事件聚合。`report_agent` 负责输入整形和模式路由，`video_report_gen` 负责调用现有 `Phase 2` 视频理解链路并生成固定模板 Markdown，最终统一返回 `AgentOutput`，其中 `side_effects` 里保留可扩展下载元数据结构。

**Tech Stack:** Python 3.12, Pydantic v2, existing `UnderstandingResult` / `SummaryResult`, pytest, pytest-asyncio, markdown text generation

---

## 文件结构

**新增文件**
- `src/vsa_agent/agents/report_agent.py`
  单视频报告 Agent，第一版只支持 video-based path
- `src/vsa_agent/tools/video_report_gen.py`
  固定模板 Markdown 报告生成工具
- `tests/unit/agents/test_report_agent.py`
  单视频报告 Agent 测试
- `tests/unit/tools/test_video_report_gen.py`
  报告生成工具测试
- `tests/acceptance/test_report_flow.py`
  单视频报告主链验收测试

**修改文件**
- `src/vsa_agent/agents/register.py`
  注册 `report_agent`
- `src/vsa_agent/tools/register.py`
  注册 `video_report_gen`
- `src/vsa_agent/config.py`
  如需要，增加报告输出配置
- `config_test.yaml`
  如需要，增加测试配置

---

### Task 1: 定义 `video_report_gen` 的最小输出契约

**Files:**
- Create: `src/vsa_agent/tools/video_report_gen.py`
- Test: `tests/unit/tools/test_video_report_gen.py`

- [ ] **Step 1: 写失败测试，定义工具输出结构**

```python
import pytest

from vsa_agent.tools.video_report_gen import VideoReportGenOutput
from vsa_agent.tools.video_report_gen import generate_video_report


@pytest.mark.anyio
async def test_generate_video_report_returns_markdown_and_download_metadata():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "query": "生成详细报告",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )
    assert isinstance(result, VideoReportGenOutput)
    assert result.markdown_content.startswith("# ")
    assert result.downloads["markdown"]["filename"].endswith(".md")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py -v`
Expected: FAIL with import error

- [ ] **Step 3: 写最小实现**

```python
from pydantic import BaseModel, Field


class VideoReportGenOutput(BaseModel):
    markdown_content: str
    downloads: dict = Field(default_factory=dict)
    summary: str = ""


async def generate_video_report(sensor_id: str, user_query: str, understanding_result) -> VideoReportGenOutput:
    summary_text = understanding_result["summary_text"] if isinstance(understanding_result, dict) else understanding_result.summary_text
    markdown_content = (
        "# 单视频分析报告\n\n"
        f"## 视频源\n- sensor_id: {sensor_id}\n\n"
        f"## 用户问题\n{user_query}\n\n"
        f"## 摘要\n{summary_text}\n"
    )
    return VideoReportGenOutput(
        markdown_content=markdown_content,
        downloads={
            "markdown": {
                "filename": f"{sensor_id}-report.md",
                "content_type": "text/markdown",
            }
        },
        summary=summary_text,
    )
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_report_gen.py tests/unit/tools/test_video_report_gen.py
git commit -m "feat: add single video report generator"
```

### Task 2: 固定模板内容落地

**Files:**
- Modify: `src/vsa_agent/tools/video_report_gen.py`
- Test: `tests/unit/tools/test_video_report_gen.py`

- [ ] **Step 1: 写失败测试，要求报告使用固定章节**

```python
import pytest

from vsa_agent.tools.video_report_gen import generate_video_report


@pytest.mark.anyio
async def test_generate_video_report_uses_fixed_sections():
    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "query": "生成详细报告",
            "source_type": "rtsp",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        },
    )
    assert "## 视频源" in result.markdown_content
    assert "## 用户问题" in result.markdown_content
    assert "## 摘要" in result.markdown_content
    assert "## 事件时间线" in result.markdown_content
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py -v`
Expected: FAIL because timeline section is missing

- [ ] **Step 3: 扩展最小实现，加入固定模板章节**

```python
def _format_timeline(understanding_result) -> str:
    events = understanding_result["events"] if isinstance(understanding_result, dict) else understanding_result.events
    if not events:
        return "- 无结构化事件"
    lines = []
    for event in events:
        if isinstance(event, dict):
            lines.append(f"- [{event['start_timestamp']} - {event['end_timestamp']}] {event['description']}")
        else:
            lines.append(f"- [{event.start_timestamp} - {event.end_timestamp}] {event.description}")
    return "\n".join(lines)
```

并将 `markdown_content` 调整为：

```python
markdown_content = (
    "# 单视频分析报告\n\n"
    f"## 视频源\n- sensor_id: {sensor_id}\n\n"
    f"## 用户问题\n{user_query}\n\n"
    f"## 摘要\n{summary_text}\n\n"
    f"## 事件时间线\n{_format_timeline(understanding_result)}\n"
)
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_report_gen.py tests/unit/tools/test_video_report_gen.py
git commit -m "feat: add fixed markdown template for video reports"
```

### Task 3: 实现 `report_agent` 的单视频路径

**Files:**
- Create: `src/vsa_agent/agents/report_agent.py`
- Modify: `src/vsa_agent/agents/register.py`
- Modify: `src/vsa_agent/tools/register.py`
- Test: `tests/unit/agents/test_report_agent.py`

- [ ] **Step 1: 写失败测试，定义单视频路径输入输出**

```python
import pytest

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.report_agent import ReportAgentInput
from vsa_agent.agents.report_agent import execute_report_agent


@pytest.mark.anyio
async def test_execute_report_agent_for_video_path():
    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": "video_file",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        }

    async def fake_video_report_gen(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "person walking near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
    )
    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert "markdown_content" in result.side_effects
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_report_agent.py -v`
Expected: FAIL with import error

- [ ] **Step 3: 写最小实现**

```python
from pydantic import BaseModel, Field

from vsa_agent.agents.data_models import AgentOutput


class ReportAgentInput(BaseModel):
    video_path: str | None = None
    sensor_id: str | None = None
    query: str = "Generate a detailed report of the video."


async def execute_report_agent(
    report_input: ReportAgentInput,
    video_understanding_fn,
    video_report_gen_fn,
) -> AgentOutput:
    understanding_result = await video_understanding_fn(
        video_path=report_input.video_path or "",
        query=report_input.query,
        source_type="rtsp" if report_input.sensor_id else "video_file",
        sensor_id=report_input.sensor_id,
    )
    report_result = await video_report_gen_fn(
        sensor_id=report_input.sensor_id or "uploaded-video",
        user_query=report_input.query,
        understanding_result=understanding_result,
    )
    return AgentOutput(
        messages=[report_result["summary"] if isinstance(report_result, dict) else report_result.summary],
        side_effects={
            "markdown_content": report_result["markdown_content"] if isinstance(report_result, dict) else report_result.markdown_content,
            "downloads": report_result["downloads"] if isinstance(report_result, dict) else report_result.downloads,
        },
        metadata={"report_type": "single_video"},
        status="success",
    )
```

- [ ] **Step 4: 注册导入并跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_report_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/report_agent.py src/vsa_agent/agents/register.py src/vsa_agent/tools/register.py tests/unit/agents/test_report_agent.py
git commit -m "feat: add single video report agent"
```

### Task 4: 补一条单视频报告主链验收测试

**Files:**
- Create: `tests/acceptance/test_report_flow.py`

- [ ] **Step 1: 写失败测试，验证 `report_agent -> video_report_gen` 主链**

```python
import pytest

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.report_agent import ReportAgentInput
from vsa_agent.agents.report_agent import execute_report_agent


@pytest.mark.anyio
async def test_single_video_report_flow_returns_markdown_side_effect():
    async def fake_video_understanding_fn(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [],
        }

    async def fake_video_report_gen_fn(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "person walking near forklift",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding_fn,
        video_report_gen_fn=fake_video_report_gen_fn,
    )
    assert isinstance(result, AgentOutput)
    assert result.side_effects["markdown_content"].startswith("# 单视频分析报告")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_report_flow.py -v`
Expected: FAIL until `report_agent` is wired

- [ ] **Step 3: 回跑验收与全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_report_flow.py -v`
Expected: PASS

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/ -q`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/test_report_flow.py
git commit -m "test: add single video report acceptance flow"
```

---

## 自检

### 覆盖性检查
- `video_report_gen` 输出契约：Task 1 覆盖
- 固定模板报告结构：Task 2 覆盖
- `report_agent` 单视频路径：Task 3 覆盖
- 单视频报告主链验收：Task 4 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都有精确文件路径、测试命令、最小代码骨架

### 命名一致性检查
- 统一使用 `ReportAgentInput`
- 统一使用 `execute_report_agent`
- 统一使用 `VideoReportGenOutput`
- 统一使用 `generate_video_report`

### 执行说明
- 第一版只做单视频/上传视频报告，不实现 incident 查询模式
- Markdown 是必选产物，下载元数据保留扩展位，PDF 先不实现
- 严格按 TDD：先红灯，再最小实现，再全量回归

---

## 当前执行状态（2026-06-16）

### 已完成
- [x] `src/vsa_agent/tools/video_report_gen.py`
  - 已实现 `VideoReportGenOutput`
  - 已实现固定 Markdown 模板：`视频源 / 用户问题 / 摘要 / 事件时间线`
  - 已支持空事件兜底 `- 无结构化事件`
  - 已注册为工具：`video_report_gen`
- [x] `src/vsa_agent/agents/report_agent.py`
  - 已实现 `ReportAgentInput`
  - 已实现 `execute_report_agent`
  - 已实现 `report_agent_tool`
  - 已支持 `video_file` 与 `rtsp` 两种单视频入口
- [x] 注册链与运行时入口
  - 已更新 `src/vsa_agent/agents/register.py`
  - 已更新 `src/vsa_agent/tools/register.py`
  - 已更新 `config.yaml -> tools.enabled_modules`
  - 已更新默认 prompt，使系统知道 `report_agent`
- [x] 测试
  - 已新增 `tests/unit/tools/test_video_report_gen.py`
  - 已新增 `tests/unit/agents/test_report_agent.py`
  - 已新增 `tests/acceptance/test_report_flow.py`

### 验证结果
- 定向测试：`21 passed`
- 全量回归：`261 passed`

### 当前结论
- Phase 3 第一子目标“单视频 Markdown 报告主链”已打通。
- 后续可在此基础上继续进入：
  1. `multi_report_agent`
  2. `report_gen / template_report_gen`
  3. `chart_generator / fov_counts_with_chart`
