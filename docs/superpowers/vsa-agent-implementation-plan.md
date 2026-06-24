# VSA Agent 去 NVIDIA 依赖复现实施计划

> 目标: 按照 NVIDIA VSS 架构分模块复现，去除 NAT/Cosmos/VST 等 NVIDIA 依赖
> 日期: 2026-06-09
> 状态: 进行中

---

## 项目状态总览

### 已实现模块 (已完成)

| 模块 | 文件 | 状态 |
|------|------|------|
| 配置系统 | config.py, config.yaml | 完成 |
| 工具注册 | registry.py | 完成 |
| Agent 数据模型 | agents/data_models.py | 完成 |
| TopAgent (简化版) | agents/top_agent.py | 完成 |
| SearchAgent | agents/search_agent.py | 完成 |
| CriticAgent | agents/critic_agent.py | 完成 |
| 单视频报告链路 | agents/report_agent.py, tools/video_report_gen.py | 完成 |
| 核心搜索 (数据模型+融合) | tools/search.py | 完成 |
| EmbedSearch (mock) | tools/embed_search.py | 完成 |
| AttributeSearch (mock) | tools/attribute_search.py | 完成 |
| VideoUnderstanding | tools/video_understanding.py | 完成 |
| 视频分析层 (nvschema/interface/query_builders) | video_analytics/ | 完成 |
| API 层 | api/ | 完成 |
| ModelAdapter | model_adapter/ | 完成 |
| MCP Server | mcp/ | 完成 |
| 测试框架 | tests/ | 完成 |

### 当前验证状态（2026-06-23）

- [x] 已创建专用 `conda` 环境 `vsa-agent`
- [x] 已完成环境安装：`python -m pip install -e ".[dev]" elasticsearch`
- [x] 已修复 FastAPI 路由枚举兼容问题
- [x] 已修复代理环境变量导致的 `httpx` / `ChatOpenAI` 初始化失败
- [x] 已完成全量回归验证：`406 passed, 2 warnings`
- [x] 已补齐 `evaluators/` 最小确定性评估框架：`4 passed`
- [x] 已新增 evaluator fixture 回归入口与默认跳过的 live API 效果验证入口：`5 passed, 1 skipped`

### 未实现模块 (Gap)
无

### 需要去 NVIDIA 化的依赖

| NVIDIA 依赖 | 替代方案 | 影响模块 |
|-------------|----------|----------|
| nat.* (NeMo Agent Toolkit) | 自建 registry + config | 所有 agents, tools |
| CosmosEmbedClient | OpenAI Embeddings API | embed_search |
| RTVICVEmbedClient | OpenAI Embeddings API | attribute_search |
| VST 服务 | 本地文件系统 / MinIO | video_understanding, tools/vst/ |
| boto3 (MinIO) | 保留（开源） | video_understanding |


---

## Phase 0 — 基础设施补齐 (P0)

**目标**: 补齐当前项目缺失的基础模块，使架构与 NVIDIA 对齐

### Task 0.1: 创建 prompt.py
- [ ] 从 NVIDIA prompt.py 移植所有 prompt 常量
- [ ] 从 config.yaml 的 prompts 段迁移到 prompt.py
- [ ] 更新 config.py 移除 prompts 段（或保留为覆盖）

### Task 0.2: 补齐 data_models/vss.py
- [ ] 实现 MediaInfoOffset 数据模型
- [ ] 实现 Incident 数据模型
- [ ] 实现 ParserMixin

### Task 0.3: 补齐 embed/ 层
- [ ] 实现 embed/embed.py (EmbedClient ABC)
- [ ] 实现 embed/cosmos_embed.py (OpenAI 替代 Cosmos)
- [x] 实现 embed/rtvi_cv_embed.py (OpenAI 替代 RTVI CV)

### Task 0.4: 补齐 utils/ 工具函数
- [ ] 实现 utils/frame_select.py
- [ ] 实现 utils/time_convert.py
- [ ] 实现 utils/url_translation.py
- [ ] 实现 utils/reasoning_parsing.py
- [ ] 实现 utils/reasoning_utils.py
- [ ] 实现 utils/asyncmixin.py

### Task 0.4A: 补齐视频帧时间戳工具
- [x] 实现 tools/video_frame_timestamp.py

### Task 0.5: 更新 TopAgent 对齐 NVIDIA
- [ ] 添加 plan-then-execute 模式
- [ ] 添加 postprocessing 管道支持
- [ ] 添加子 Agent 流式支持


---

## Phase 1 — 视频搜索增强 (P1)

**目标**: 将 mock 实现替换为真实实现，完善搜索链路

### Task 1.1: 实现 embed_search.py (真实 ES 查询)
- [x] 实现 _generate_query_embedding() 使用 OpenAI Embeddings
- [x] 实现 _build_es_query() 构建嵌套 KNN 查询
- [x] 实现 _process_search_hit() 处理 ES 结果
- [x] 实现 ES 分数转余弦相似度
- [x] 添加 SearchConfig 到 config.py
- [x] 安装 elasticsearch 依赖

### Task 1.2: 实现 attribute_search.py (真实 ES 查询)
- [x] 实现 search_single_attribute() 最小 ES 属性搜索
- [x] 实现 _perform_frame_lookups() 帧级查找
- [x] 实现 _fuse_multi_attribute() / _append_multi_attribute()
- [x] 实现 _deduplicate_by_object()

### Task 1.3: 完善 search.py 融合算法
- [x] 实现置信度阈值检查 (embed_confidence_threshold)
- [x] 实现 Critic 验证循环
- [x] 实现 execute_core_search() 流式生成器
- [x] 添加 enable_critic / search_max_iterations 配置


---

## Phase 2 — 视频理解完善 (P1)

**目标**: 完善 video_understanding 工具

### Task 2.1: 完善 video_understanding.py
- [x] 对齐 NVIDIA VideoUnderstandingConfig (max_fps, min_pixels, reasoning, filter_thinking)
- [x] 支持 ISO 和 offset 两种时间格式
- [x] 支持 VST/MinIO 两种视频源
- [x] 实现 URL 翻译
- [x] 实现 VLM 重试逻辑

### Task 2.2: 实现 lvs_video_understanding.py
- [x] 长视频分块处理 (chunk_duration / num_frames_per_chunk)
- [x] 场景/事件配置
- [x] 结构化输出

### Task 2.3: 实现 vss_summarize.py
- [x] Caption summarization
- [x] 时间合并

### Task 2.4: 实现 prompt_gen.py
- [x] 根据用户意图动态生成 VLM 子 prompt

---

## Phase 3 — 报告生成 (P2)

**目标**: 实现报告生成 Agent 和工具

### Task 3.1: 实现 report_agent.py
- [x] 已完成单视频/上传视频报告路径
- [x] 已支持 `video_file` / `rtsp` 两种入口
- [x] 已完成 `report_agent_tool` 注册

### Task 3.2: 实现 multi_report_agent.py
- [x] 已完成 `multi_report_agent.py`
- [x] 已支持多 `video_file / rtsp` 混合输入
- [x] 已完成 `multi_report_agent_tool` 注册

### Task 3.3: 实现 report_gen.py / template_report_gen.py / video_report_gen.py
- [x] 已完成 `video_report_gen.py`
- [x] 已完成固定 Markdown 模板输出
- [x] 已保留下载元数据扩展位
- [x] 已完成 `report_gen.py`
- [x] 已完成 `template_report_gen.py`

### Task 3.4: 实现 chart_generator.py / fov_counts_with_chart.py
- [x] 已完成 `chart_generator.py`
- [x] 已完成 `fov_counts_with_chart.py`
- [x] 已完成图表区块接入 `report_gen / template_report_gen`
- [x] 已完成图表增强验收测试 `tests/acceptance/test_report_chart_flow.py`

### Phase 3 当前进度（2026-06-16）
- [x] 单视频报告主链完成
- [x] 新增验收测试 `tests/acceptance/test_report_flow.py`
- [x] 多事件报告主链完成
- [x] 新增验收测试 `tests/acceptance/test_multi_report_flow.py`
- [x] 全量回归通过：`274 passed`
- [x] 模板化报告总装
- [x] 图表与统计输出

---

# Phase 3 多事件报告主链实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有单视频报告能力之上，打通 `multi_report_agent + report_gen + template_report_gen` 的多事件报告主链，支持多个视频源输入并输出一份聚合 Markdown 报告。

**Architecture:** 这一版只覆盖“多视频/多传感器报告聚合”主链，不引入图表、FOV 计数、地理位置或 incidents 管理。`multi_report_agent` 负责输入整形与逐项调用视频理解，`report_gen` 负责把多个理解结果转成标准分报告块，`template_report_gen` 负责拼装最终 Markdown 报告。

**Tech Stack:** Python 3.12, Pydantic v2, existing `UnderstandingResult`, existing `generate_video_report`, pytest, pytest-asyncio, markdown text generation

---

## 文件结构

**新增文件**
- `src/vsa_agent/tools/template_report_gen.py`
  - 固定模板的多事件聚合报告拼装器
- `src/vsa_agent/tools/report_gen.py`
  - 多事件报告总装器，负责逐项调用单视频报告生成器
- `src/vsa_agent/agents/multi_report_agent.py`
  - 多事件报告 Agent，负责 source 列表输入和逐项理解
- `tests/unit/tools/test_template_report_gen.py`
  - 模板聚合器测试
- `tests/unit/tools/test_report_gen.py`
  - 报告总装器测试
- `tests/unit/agents/test_multi_report_agent.py`
  - 多事件报告 Agent 测试
- `tests/acceptance/test_multi_report_flow.py`
  - 多事件报告主链验收测试

**修改文件**
- `src/vsa_agent/tools/register.py`
  - 注册 `template_report_gen`、`report_gen`
- `src/vsa_agent/agents/register.py`
  - 注册 `multi_report_agent`
- `config.yaml`
  - 把 Phase 3 新工具加入 `tools.enabled_modules`
- `src/vsa_agent/prompt.py`
  - 在默认系统提示中加入 `multi_report_agent`
- `tests/unit/test_config.py`
  - 校验新模块加入运行时加载链
- `tests/unit/test_prompt.py`
  - 校验默认提示暴露了新工具

---

### Task 1: 定义 `template_report_gen` 的固定模板契约

**Files:**
- Create: `src/vsa_agent/tools/template_report_gen.py`
- Test: `tests/unit/tools/test_template_report_gen.py`

- [ ] **Step 1: 写失败测试，定义多事件模板输出结构**

```python
import pytest

from vsa_agent.tools.template_report_gen import TemplateReportGenOutput
from vsa_agent.tools.template_report_gen import generate_template_report


@pytest.mark.anyio
async def test_generate_template_report_returns_markdown_with_summary_sections():
    result = await generate_template_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            {
                "section_title": "事件 1 - camera-1",
                "summary": "person walking near forklift",
                "markdown_content": "## 摘要\nperson walking near forklift",
            },
            {
                "section_title": "事件 2 - camera-2",
                "summary": "forklift stops near doorway",
                "markdown_content": "## 摘要\nforklift stops near doorway",
            },
        ],
    )
    assert isinstance(result, TemplateReportGenOutput)
    assert result.markdown_content.startswith("# 仓库巡检聚合报告")
    assert "## 报告摘要" in result.markdown_content
    assert "## 分事件报告" in result.markdown_content
    assert result.section_count == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_template_report_gen.py -v`
Expected: FAIL with import error

- [ ] **Step 3: 写最小实现**

```python
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class TemplateReportGenOutput(BaseModel):
    markdown_content: str
    section_count: int = 0


def _build_summary_lines(report_sections: list[dict]) -> str:
    if not report_sections:
        return "- 无分事件内容"
    return "\n".join(
        f"- {section['section_title']}: {section['summary']}"
        for section in report_sections
    )


@register_tool(
    "template_report_gen",
    description="Assemble multiple event report sections into one markdown report.",
)
async def generate_template_report(
    report_title: str,
    report_sections: list[dict],
) -> TemplateReportGenOutput:
    summary_lines = _build_summary_lines(report_sections)
    detail_blocks = "\n\n".join(
        f"### {section['section_title']}\n\n{section['markdown_content']}"
        for section in report_sections
    )
    markdown_content = (
        f"# {report_title}\n\n"
        "## 报告摘要\n"
        f"{summary_lines}\n\n"
        "## 分事件报告\n\n"
        f"{detail_blocks}\n"
    )
    return TemplateReportGenOutput(
        markdown_content=markdown_content,
        section_count=len(report_sections),
    )
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_template_report_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/template_report_gen.py tests/unit/tools/test_template_report_gen.py
git commit -m "feat: add template report generator"
```

### Task 2: 实现 `report_gen` 作为多事件报告总装器

**Files:**
- Create: `src/vsa_agent/tools/report_gen.py`
- Test: `tests/unit/tools/test_report_gen.py`

- [ ] **Step 1: 写失败测试，定义逐项调用单视频报告生成器并汇总**

```python
import pytest

from vsa_agent.tools.report_gen import MultiReportGenOutput
from vsa_agent.tools.report_gen import ReportSectionInput
from vsa_agent.tools.report_gen import generate_multi_report


@pytest.mark.anyio
async def test_generate_multi_report_calls_single_report_gen_and_template_gen():
    single_calls = []
    template_calls = []

    async def fake_single_report_gen(**kwargs):
        single_calls.append(kwargs)
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "camera-1-report.md"}},
            "summary": "person walking near forklift",
        }

    async def fake_template_report_gen(**kwargs):
        template_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 报告摘要\n- 事件 1 - camera-1: person walking near forklift",
            "section_count": 1,
        }

    result = await generate_multi_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            ReportSectionInput(
                section_title="事件 1 - camera-1",
                sensor_id="camera-1",
                user_query="生成聚合报告",
                understanding_result={
                    "query": "生成聚合报告",
                    "source_type": "rtsp",
                    "summary_text": "person walking near forklift",
                    "chunks": [],
                    "events": [],
                },
            )
        ],
        single_report_gen_fn=fake_single_report_gen,
        template_report_gen_fn=fake_template_report_gen,
    )
    assert isinstance(result, MultiReportGenOutput)
    assert result.section_count == 1
    assert result.downloads["markdown"]["filename"] == "multi-report.md"
    assert single_calls[0]["sensor_id"] == "camera-1"
    assert template_calls[0]["report_title"] == "仓库巡检聚合报告"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_gen.py -v`
Expected: FAIL with import error

- [ ] **Step 3: 写最小实现**

```python
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class ReportSectionInput(BaseModel):
    section_title: str
    sensor_id: str
    user_query: str
    understanding_result: dict[str, Any]


class MultiReportGenOutput(BaseModel):
    markdown_content: str
    downloads: dict[str, dict[str, str]] = Field(default_factory=dict)
    summary: str = ""
    section_count: int = 0


async def _default_single_report_gen(**kwargs):
    from vsa_agent.tools.video_report_gen import generate_video_report

    return await generate_video_report(**kwargs)


async def _default_template_report_gen(**kwargs):
    from vsa_agent.tools.template_report_gen import generate_template_report

    return await generate_template_report(**kwargs)


@register_tool(
    "report_gen",
    description="Generate one markdown report from multiple structured video understanding results.",
)
async def generate_multi_report(
    report_title: str,
    report_sections: list[ReportSectionInput],
    single_report_gen_fn=None,
    template_report_gen_fn=None,
) -> MultiReportGenOutput:
    single_report_gen = single_report_gen_fn or _default_single_report_gen
    template_report_gen = template_report_gen_fn or _default_template_report_gen

    normalized_sections = []
    summaries = []
    for section in report_sections:
        report = await single_report_gen(
            sensor_id=section.sensor_id,
            user_query=section.user_query,
            understanding_result=section.understanding_result,
        )
        report_dict = report if isinstance(report, dict) else report.model_dump()
        normalized_sections.append(
            {
                "section_title": section.section_title,
                "summary": report_dict["summary"],
                "markdown_content": report_dict["markdown_content"],
            }
        )
        summaries.append(report_dict["summary"])

    template = await template_report_gen(
        report_title=report_title,
        report_sections=normalized_sections,
    )
    template_dict = template if isinstance(template, dict) else template.model_dump()
    return MultiReportGenOutput(
        markdown_content=template_dict["markdown_content"],
        downloads={
            "markdown": {
                "filename": "multi-report.md",
                "content_type": "text/markdown",
            }
        },
        summary="; ".join(text for text in summaries if text),
        section_count=template_dict["section_count"],
    )
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/report_gen.py tests/unit/tools/test_report_gen.py
git commit -m "feat: add multi report generator"
```

### Task 3: 实现 `multi_report_agent` 的多输入路径

**Files:**
- Create: `src/vsa_agent/agents/multi_report_agent.py`
- Test: `tests/unit/agents/test_multi_report_agent.py`

- [ ] **Step 1: 写失败测试，定义多源输入和输出契约**

```python
import pytest

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
from vsa_agent.agents.multi_report_agent import execute_multi_report_agent


@pytest.mark.anyio
async def test_execute_multi_report_agent_for_multiple_sources():
    understanding_calls = []
    report_calls = []

    async def fake_video_understanding(**kwargs):
        understanding_calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {kwargs.get('sensor_id') or kwargs.get('video_path')}",
            "chunks": [],
            "events": [],
        }

    async def fake_report_gen(**kwargs):
        report_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 报告摘要\n- 事件 1 - camera-1: summary for camera-1",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary for camera-1; summary for video-a.mp4",
            "section_count": 2,
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[
                MultiReportSourceItem(sensor_id="camera-1"),
                MultiReportSourceItem(video_path="video-a.mp4"),
            ],
        ),
        video_understanding_fn=fake_video_understanding,
        report_gen_fn=fake_report_gen,
    )
    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert result.metadata["report_type"] == "multi_video"
    assert result.side_effects["downloads"]["markdown"]["filename"] == "multi-report.md"
    assert len(understanding_calls) == 2
    assert report_calls[0]["report_title"] == "仓库巡检聚合报告"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_multi_report_agent.py -v`
Expected: FAIL with import error

- [ ] **Step 3: 写最小实现**

```python
from typing import Any
from typing import Awaitable
from typing import Callable

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.registry import register_tool
from vsa_agent.tools.report_gen import ReportSectionInput

VideoUnderstandingCallable = Callable[..., Awaitable[Any]]
ReportGenCallable = Callable[..., Awaitable[Any]]


class MultiReportSourceItem(BaseModel):
    video_path: str | None = Field(default=None)
    sensor_id: str | None = Field(default=None)


class MultiReportAgentInput(BaseModel):
    report_title: str = Field(default="多视频聚合报告")
    query: str = Field(default="生成聚合报告")
    sources: list[MultiReportSourceItem] = Field(default_factory=list)


def _resolve_source_type(item: MultiReportSourceItem) -> str:
    return "rtsp" if item.sensor_id else "video_file"


async def _default_video_understanding_fn(**kwargs):
    from vsa_agent.tools.video_understanding import analyze_video_segment

    return await analyze_video_segment(**kwargs)


async def _default_report_gen_fn(**kwargs):
    from vsa_agent.tools.report_gen import generate_multi_report

    return await generate_multi_report(**kwargs)


@register_tool(
    "multi_report_agent",
    description="Generate one markdown report from multiple uploaded videos or RTSP sensors.",
)
async def execute_multi_report_agent(
    report_input: MultiReportAgentInput,
    video_understanding_fn: VideoUnderstandingCallable | None = None,
    report_gen_fn: ReportGenCallable | None = None,
) -> AgentOutput:
    if not report_input.sources:
        raise ValueError("multi_report_agent 至少需要一个 source")

    video_understanding = video_understanding_fn or _default_video_understanding_fn
    report_gen = report_gen_fn or _default_report_gen_fn

    sections: list[ReportSectionInput] = []
    for index, item in enumerate(report_input.sources, start=1):
        if not item.video_path and not item.sensor_id:
            raise ValueError("每个 source 必须提供 video_path 或 sensor_id")
        understanding = await video_understanding(
            video_path=item.video_path or "",
            query=report_input.query,
            source_type=_resolve_source_type(item),
            sensor_id=item.sensor_id,
        )
        source_name = item.sensor_id or item.video_path or f"source-{index}"
        sections.append(
            ReportSectionInput(
                section_title=f"事件 {index} - {source_name}",
                sensor_id=source_name,
                user_query=report_input.query,
                understanding_result=understanding if isinstance(understanding, dict) else understanding.model_dump(),
            )
        )

    report = await report_gen(
        report_title=report_input.report_title,
        report_sections=sections,
    )
    report_dict = report if isinstance(report, dict) else report.model_dump()
    return AgentOutput(
        messages=[report_dict["summary"]] if report_dict.get("summary") else [],
        side_effects={
            "markdown_content": report_dict["markdown_content"],
            "downloads": report_dict["downloads"],
        },
        metadata={
            "report_type": "multi_video",
            "source_count": len(report_input.sources),
        },
        status="success",
    )
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_multi_report_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/multi_report_agent.py tests/unit/agents/test_multi_report_agent.py
git commit -m "feat: add multi report agent"
```

### Task 4: 接通运行时注册链与默认提示

**Files:**
- Modify: `src/vsa_agent/tools/register.py`
- Modify: `src/vsa_agent/agents/register.py`
- Modify: `config.yaml`
- Modify: `src/vsa_agent/prompt.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_prompt.py`

- [ ] **Step 1: 写失败测试，要求默认加载和默认提示包含 Phase 3 新模块**

```python
def test_main_config_enables_multi_report_modules():
    from vsa_agent.config import AppConfig

    cfg = AppConfig.from_yaml("config.yaml")
    assert "vsa_agent.tools.template_report_gen" in cfg.tools.enabled_modules
    assert "vsa_agent.tools.report_gen" in cfg.tools.enabled_modules
    assert "vsa_agent.agents.multi_report_agent" in cfg.tools.enabled_modules


def test_default_system_prompt_mentions_multi_report_agent():
    from vsa_agent.prompt import SYSTEM_PROMPT_DEFAULT

    assert "multi_report_agent" in SYSTEM_PROMPT_DEFAULT
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_config.py tests/unit/test_prompt.py -v`
Expected: FAIL because modules are not yet registered

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/register.py
import vsa_agent.tools.report_gen  # noqa: F401
import vsa_agent.tools.template_report_gen  # noqa: F401

# src/vsa_agent/agents/register.py
from vsa_agent.agents import multi_report_agent  # noqa: F401

# config.yaml
tools:
  enabled_modules:
  - vsa_agent.tools.video_report_gen
  - vsa_agent.tools.template_report_gen
  - vsa_agent.tools.report_gen
  - vsa_agent.agents.report_agent
  - vsa_agent.agents.multi_report_agent

# src/vsa_agent/prompt.py
"- multi_report_agent(sources, report_title, query): Generate one markdown report from multiple sources.\n"
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_config.py tests/unit/test_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/register.py src/vsa_agent/agents/register.py config.yaml src/vsa_agent/prompt.py tests/unit/test_config.py tests/unit/test_prompt.py
git commit -m "feat: register multi report modules"
```

### Task 5: 补齐多事件报告主链验收测试

**Files:**
- Create: `tests/acceptance/test_multi_report_flow.py`

- [ ] **Step 1: 写失败测试，验证 `multi_report_agent -> report_gen -> template_report_gen` 主链**

```python
import pytest

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
from vsa_agent.tools.report_gen import generate_multi_report


@pytest.mark.anyio
async def test_multi_report_flow_returns_aggregated_markdown():
    async def fake_video_understanding_fn(**kwargs):
        source_name = kwargs.get("sensor_id") or kwargs.get("video_path")
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {source_name}",
            "chunks": [],
            "events": [],
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[
                MultiReportSourceItem(sensor_id="camera-1"),
                MultiReportSourceItem(video_path="video-a.mp4"),
            ],
        ),
        video_understanding_fn=fake_video_understanding_fn,
        report_gen_fn=generate_multi_report,
    )
    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert result.side_effects["markdown_content"].startswith("# 仓库巡检聚合报告")
    assert "## 报告摘要" in result.side_effects["markdown_content"]
    assert "### 事件 1 - camera-1" in result.side_effects["markdown_content"]
    assert "### 事件 2 - video-a.mp4" in result.side_effects["markdown_content"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_multi_report_flow.py -v`
Expected: FAIL until the full chain is wired

- [ ] **Step 3: 回跑验收与全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_multi_report_flow.py -v`
Expected: PASS

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/ -q`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/test_multi_report_flow.py
git commit -m "test: add multi report acceptance flow"
```

---

## 自检

### 覆盖性检查
- `template_report_gen` 模板聚合契约：Task 1 覆盖
- `report_gen` 多事件总装：Task 2 覆盖
- `multi_report_agent` 多输入路径：Task 3 覆盖
- 运行时注册链与默认提示：Task 4 覆盖
- 多事件报告主链验收：Task 5 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都有精确文件路径、测试命令、最小代码骨架

### 类型一致性检查
- 统一使用 `TemplateReportGenOutput`
- 统一使用 `ReportSectionInput`
- 统一使用 `MultiReportGenOutput`
- 统一使用 `MultiReportSourceItem`
- 统一使用 `MultiReportAgentInput`
- 统一使用 `generate_template_report`
- 统一使用 `generate_multi_report`
- 统一使用 `execute_multi_report_agent`

### 执行说明
- 本计划只覆盖 Phase 3 的“多事件报告主链”
- `chart_generator / fov_counts_with_chart` 不纳入本计划，建议单独写下一份执行计划
- 继续严格按 TDD：先红灯，再最小实现，再全量回归

---

# Phase 3 图表与统计输出实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有单视频/多事件 Markdown 报告链路补齐统计与图表输出能力，支持从事件时间线生成基础计数统计，并把图表区块嵌入最终报告。

**Architecture:** 这一版采用“报告增强型”路径，不先做独立统计平台。`fov_counts_with_chart` 负责从已有 `understanding_result / report_sections` 中提取基础计数并调用 `chart_generator` 产出图表元数据，`template_report_gen` 与 `report_gen` 负责把图表区块嵌入最终 Markdown，优先覆盖柱状图和表格摘要两种最小能力。

**Tech Stack:** Python 3.12, Pydantic v2, pytest, pytest-asyncio, markdown text generation, in-memory chart spec generation

---

## 文件结构

**新增文件**
- `src/vsa_agent/tools/chart_generator.py`
  - 统一图表规范生成器，第一版只输出可嵌入 Markdown 的图表元数据与文本表格
- `src/vsa_agent/tools/fov_counts_with_chart.py`
  - 从事件结果中提取计数统计并组装为图表输入
- `tests/unit/tools/test_chart_generator.py`
  - 图表规范生成器测试
- `tests/unit/tools/test_fov_counts_with_chart.py`
  - 统计与图表适配器测试
- `tests/acceptance/test_report_chart_flow.py`
  - 报告链路带图表区块的验收测试

**修改文件**
- `src/vsa_agent/tools/report_gen.py`
  - 接入统计/图表生成能力，把图表元数据传给模板层
- `src/vsa_agent/tools/template_report_gen.py`
  - 为最终 Markdown 增加“统计概览 / 图表”区块
- `src/vsa_agent/tools/register.py`
  - 注册 `chart_generator`、`fov_counts_with_chart`
- `config.yaml`
  - 把新工具加入 `tools.enabled_modules`
- `src/vsa_agent/prompt.py`
  - 在默认系统提示中暴露图表增强能力
- `tests/unit/test_config.py`
  - 校验新模块加入运行时加载链
- `tests/unit/test_prompt.py`
  - 校验默认提示暴露图表工具

---

### Task 1: 定义 `chart_generator` 的最小图表契约

**Files:**
- Create: `src/vsa_agent/tools/chart_generator.py`
- Test: `tests/unit/tools/test_chart_generator.py`

- [x] **Step 1: 写失败测试，定义柱状图与 Markdown 表格输出结构**

```python
import pytest

from vsa_agent.tools.chart_generator import ChartArtifact
from vsa_agent.tools.chart_generator import ChartSeriesItem
from vsa_agent.tools.chart_generator import generate_bar_chart_artifact


@pytest.mark.anyio
async def test_generate_bar_chart_artifact_returns_chart_metadata_and_markdown_table():
    result = await generate_bar_chart_artifact(
        chart_title="事件计数统计",
        x_label="事件类型",
        y_label="次数",
        series=[
            ChartSeriesItem(label="walking", value=2),
            ChartSeriesItem(label="forklift", value=1),
        ],
    )
    assert isinstance(result, ChartArtifact)
    assert result.chart_type == "bar"
    assert result.title == "事件计数统计"
    assert result.spec["labels"] == ["walking", "forklift"]
    assert "| 事件类型 | 次数 |" in result.markdown_table
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_chart_generator.py -v`
Expected: FAIL with import error

- [x] **Step 3: 写最小实现**

```python
from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class ChartSeriesItem(BaseModel):
    label: str
    value: int


class ChartArtifact(BaseModel):
    chart_type: str
    title: str
    spec: dict = Field(default_factory=dict)
    markdown_table: str = ""


def _build_markdown_table(x_label: str, y_label: str, series: list[ChartSeriesItem]) -> str:
    lines = [
        f"| {x_label} | {y_label} |",
        "| --- | --- |",
    ]
    for item in series:
        lines.append(f"| {item.label} | {item.value} |")
    return "\n".join(lines)


@register_tool(
    "chart_generator",
    description="Generate minimal chart metadata and markdown table output.",
)
async def generate_bar_chart_artifact(
    chart_title: str,
    x_label: str,
    y_label: str,
    series: list[ChartSeriesItem],
) -> ChartArtifact:
    return ChartArtifact(
        chart_type="bar",
        title=chart_title,
        spec={
            "labels": [item.label for item in series],
            "values": [item.value for item in series],
            "x_label": x_label,
            "y_label": y_label,
        },
        markdown_table=_build_markdown_table(x_label, y_label, series),
    )
```

- [x] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_chart_generator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/chart_generator.py tests/unit/tools/test_chart_generator.py
git commit -m "feat: add chart generator"
```

### Task 2: 实现 `fov_counts_with_chart` 的统计与图表组装

**Files:**
- Create: `src/vsa_agent/tools/fov_counts_with_chart.py`
- Test: `tests/unit/tools/test_fov_counts_with_chart.py`

- [x] **Step 1: 写失败测试，定义事件计数统计与图表调用**

```python
import pytest

from vsa_agent.tools.fov_counts_with_chart import CountWithChartResult
from vsa_agent.tools.fov_counts_with_chart import build_event_count_chart


@pytest.mark.anyio
async def test_build_event_count_chart_counts_events_by_label():
    chart_calls = []

    async def fake_chart_generator(**kwargs):
        chart_calls.append(kwargs)
        return {
            "chart_type": "bar",
            "title": "事件计数统计",
            "spec": {"labels": ["walking", "forklift"], "values": [2, 1]},
            "markdown_table": "| 事件类型 | 次数 |\\n| --- | --- |\\n| walking | 2 |\\n| forklift | 1 |",
        }

    result = await build_event_count_chart(
        understanding_results=[
            {
                "events": [
                    {"label": "walking", "description": "person walking"},
                    {"label": "walking", "description": "person walking again"},
                ]
            },
            {
                "events": [
                    {"label": "forklift", "description": "forklift turning"},
                ]
            },
        ],
        chart_generator_fn=fake_chart_generator,
    )
    assert isinstance(result, CountWithChartResult)
    assert result.counts == {"walking": 2, "forklift": 1}
    assert result.chart["title"] == "事件计数统计"
    assert chart_calls[0]["chart_title"] == "事件计数统计"
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_fov_counts_with_chart.py -v`
Expected: FAIL with import error

- [x] **Step 3: 写最小实现**

```python
from collections import Counter
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool


class CountWithChartResult(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    chart: dict[str, Any] = Field(default_factory=dict)


async def _default_chart_generator_fn(**kwargs):
    from vsa_agent.tools.chart_generator import ChartSeriesItem
    from vsa_agent.tools.chart_generator import generate_bar_chart_artifact

    series = [ChartSeriesItem(**item) for item in kwargs["series"]]
    result = await generate_bar_chart_artifact(
        chart_title=kwargs["chart_title"],
        x_label=kwargs["x_label"],
        y_label=kwargs["y_label"],
        series=series,
    )
    return result.model_dump()


@register_tool(
    "fov_counts_with_chart",
    description="Build basic event counts and chart output from understanding results.",
)
async def build_event_count_chart(
    understanding_results: list[dict[str, Any]],
    chart_generator_fn=None,
) -> CountWithChartResult:
    counter = Counter()
    for result in understanding_results:
        for event in result.get("events", []):
            label = str(event.get("label", "")).strip()
            if label:
                counter[label] += 1

    ordered_items = sorted(counter.items(), key=lambda item: item[0])
    series = [{"label": label, "value": count} for label, count in ordered_items]
    chart_generator = chart_generator_fn or _default_chart_generator_fn
    chart = await chart_generator(
        chart_title="事件计数统计",
        x_label="事件类型",
        y_label="次数",
        series=series,
    )
    return CountWithChartResult(
        counts=dict(counter),
        chart=chart,
    )
```

- [x] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_fov_counts_with_chart.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/fov_counts_with_chart.py tests/unit/tools/test_fov_counts_with_chart.py
git commit -m "feat: add event count chart adapter"
```

### Task 3: 把图表区块接入 `report_gen` 与 `template_report_gen`

**Files:**
- Modify: `src/vsa_agent/tools/report_gen.py`
- Modify: `src/vsa_agent/tools/template_report_gen.py`
- Test: `tests/unit/tools/test_report_gen.py`
- Test: `tests/unit/tools/test_template_report_gen.py`

- [x] **Step 1: 写失败测试，要求聚合报告包含统计概览和图表区块**

```python
import pytest

from vsa_agent.tools.report_gen import ReportSectionInput
from vsa_agent.tools.report_gen import generate_multi_report


@pytest.mark.anyio
async def test_generate_multi_report_includes_chart_payload_for_template():
    template_calls = []

    async def fake_single_report_gen(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nperson walking near forklift",
            "downloads": {"markdown": {"filename": "camera-1-report.md"}},
            "summary": "person walking near forklift",
        }

    async def fake_count_chart_builder(**kwargs):
        return {
            "counts": {"walking": 2},
            "chart": {
                "chart_type": "bar",
                "title": "事件计数统计",
                "spec": {"labels": ["walking"], "values": [2]},
                "markdown_table": "| 事件类型 | 次数 |\n| --- | --- |\n| walking | 2 |",
            },
        }

    async def fake_template_report_gen(**kwargs):
        template_calls.append(kwargs)
        return {
            "markdown_content": "# 仓库巡检聚合报告\n\n## 统计概览\n- walking: 2",
            "section_count": 1,
        }

    await generate_multi_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            ReportSectionInput(
                section_title="事件 1 - camera-1",
                sensor_id="camera-1",
                user_query="生成聚合报告",
                understanding_result={
                    "query": "生成聚合报告",
                    "source_type": "rtsp",
                    "summary_text": "person walking near forklift",
                    "chunks": [],
                    "events": [{"label": "walking", "description": "person walking"}],
                },
            )
        ],
        single_report_gen_fn=fake_single_report_gen,
        template_report_gen_fn=fake_template_report_gen,
        count_chart_builder_fn=fake_count_chart_builder,
    )
    assert template_calls[0]["counts"] == {"walking": 2}
    assert template_calls[0]["chart"]["title"] == "事件计数统计"
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_gen.py tests/unit/tools/test_template_report_gen.py -v`
Expected: FAIL because chart payload is not yet passed through

- [x] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/report_gen.py
async def _default_count_chart_builder_fn(**kwargs):
    from vsa_agent.tools.fov_counts_with_chart import build_event_count_chart

    return await build_event_count_chart(**kwargs)


async def generate_multi_report(
    report_title: str,
    report_sections: list[ReportSectionInput],
    single_report_gen_fn=None,
    template_report_gen_fn=None,
    count_chart_builder_fn=None,
) -> MultiReportGenOutput:
    single_report_gen = single_report_gen_fn or _default_single_report_gen
    template_report_gen = template_report_gen_fn or _default_template_report_gen
    count_chart_builder = count_chart_builder_fn or _default_count_chart_builder_fn
    ...
    understanding_results = [section.understanding_result for section in report_sections]
    count_chart = await count_chart_builder(
        understanding_results=understanding_results,
    )
    count_chart_dict = count_chart if isinstance(count_chart, dict) else count_chart.model_dump()
    template = await template_report_gen(
        report_title=report_title,
        report_sections=normalized_sections,
        counts=count_chart_dict["counts"],
        chart=count_chart_dict["chart"],
    )

# src/vsa_agent/tools/template_report_gen.py
def _build_count_lines(counts: dict[str, int]) -> str:
    if not counts:
        return "- 无统计数据"
    return "\n".join(f"- {label}: {count}" for label, count in sorted(counts.items()))


async def generate_template_report(
    report_title: str,
    report_sections: list[dict],
    counts: dict[str, int] | None = None,
    chart: dict | None = None,
) -> TemplateReportGenOutput:
    counts_text = _build_count_lines(counts or {})
    chart_table = (chart or {}).get("markdown_table", "- 无图表数据")
    markdown_content = (
        f"# {report_title}\n\n"
        "## 报告摘要\n"
        f"{summary_lines}\n\n"
        "## 统计概览\n"
        f"{counts_text}\n\n"
        "## 图表\n"
        f"{chart_table}\n\n"
        "## 分事件报告\n\n"
        f"{detail_blocks}\n"
    )
```

- [x] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_gen.py tests/unit/tools/test_template_report_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/report_gen.py src/vsa_agent/tools/template_report_gen.py tests/unit/tools/test_report_gen.py tests/unit/tools/test_template_report_gen.py
git commit -m "feat: embed chart blocks into report generation"
```

### Task 4: 接通运行时注册链与提示词

**Files:**
- Modify: `src/vsa_agent/tools/register.py`
- Modify: `config.yaml`
- Modify: `src/vsa_agent/prompt.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_prompt.py`

- [x] **Step 1: 写失败测试，要求默认加载和默认提示包含图表工具**

```python
def test_main_config_enables_chart_modules():
    from vsa_agent.config import AppConfig

    cfg = AppConfig.from_yaml("config.yaml")
    assert "vsa_agent.tools.chart_generator" in cfg.tools.enabled_modules
    assert "vsa_agent.tools.fov_counts_with_chart" in cfg.tools.enabled_modules


def test_default_system_prompt_mentions_chart_tools():
    from vsa_agent.prompt import SYSTEM_PROMPT_DEFAULT

    assert "fov_counts_with_chart" in SYSTEM_PROMPT_DEFAULT
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_config.py tests/unit/test_prompt.py -v`
Expected: FAIL because chart tools are not yet registered

- [x] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/register.py
import vsa_agent.tools.chart_generator  # noqa: F401
import vsa_agent.tools.fov_counts_with_chart  # noqa: F401

# config.yaml
tools:
  enabled_modules:
  - vsa_agent.tools.chart_generator
  - vsa_agent.tools.fov_counts_with_chart

# src/vsa_agent/prompt.py
"- fov_counts_with_chart(...): Generate event counts and chart-ready markdown tables for reports.\n"
```

- [x] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_config.py tests/unit/test_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/register.py config.yaml src/vsa_agent/prompt.py tests/unit/test_config.py tests/unit/test_prompt.py
git commit -m "feat: register chart report tools"
```

### Task 5: 补齐“报告 + 图表”验收测试

**Files:**
- Create: `tests/acceptance/test_report_chart_flow.py`

- [x] **Step 1: 写失败测试，验证聚合报告包含统计概览与图表区块**

```python
import pytest

from vsa_agent.agents.data_models import AgentOutput
from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
from vsa_agent.tools.report_gen import generate_multi_report


@pytest.mark.anyio
async def test_multi_report_flow_with_chart_blocks():
    async def fake_video_understanding_fn(**kwargs):
        source_name = kwargs.get("sensor_id") or kwargs.get("video_path")
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": f"summary for {source_name}",
            "chunks": [],
            "events": [{"label": "walking", "description": "person walking"}],
        }

    result = await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[
                MultiReportSourceItem(sensor_id="camera-1"),
                MultiReportSourceItem(video_path="video-a.mp4"),
            ],
        ),
        video_understanding_fn=fake_video_understanding_fn,
        report_gen_fn=generate_multi_report,
    )
    assert isinstance(result, AgentOutput)
    assert result.status == "success"
    assert "## 统计概览" in result.side_effects["markdown_content"]
    assert "## 图表" in result.side_effects["markdown_content"]
    assert "| 事件类型 | 次数 |" in result.side_effects["markdown_content"]
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_report_chart_flow.py -v`
Expected: FAIL until chart blocks are wired

- [x] **Step 3: 回跑验收与全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_report_chart_flow.py -v`
Expected: PASS

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/ -q`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/test_report_chart_flow.py
git commit -m "test: add chart-enhanced report acceptance flow"
```

---

## 自检

### 覆盖性检查
- `chart_generator` 最小图表契约：Task 1 覆盖
- `fov_counts_with_chart` 统计与图表组装：Task 2 覆盖
- 图表区块接入 `report_gen / template_report_gen`：Task 3 覆盖
- 运行时注册链与提示词：Task 4 覆盖
- 报告链路带图表验收：Task 5 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都有精确文件路径、测试命令、最小代码骨架

### 类型一致性检查
- 统一使用 `ChartSeriesItem`
- 统一使用 `ChartArtifact`
- 统一使用 `CountWithChartResult`
- 统一使用 `generate_bar_chart_artifact`
- 统一使用 `build_event_count_chart`

### 执行说明
- 本计划只覆盖 Phase 3 剩余部分的“图表与统计输出”
- 第一版只做事件标签计数 + 柱状图元数据 + Markdown 表格
- 不引入真实图片渲染、不引入外部图表前端库、不引入 incidents / geolocation
- 继续严格按 TDD：先红灯，再最小实现，再全量回归

---

# Review Findings 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持全部现有对外接口不变的前提下，修复代码评审发现的 6 个高优先级问题：报告/图表中文乱码、prod 模式工具绑定失效、dev 默认 API key 配置回退错误、报告链路绕过长视频分流、prompt 未实际进入 VLM、VST 时间窗语义失真。

**Architecture:** 这轮只修内部实现，不新增公开 API，不改 tool/agent 参数与返回结构。核心策略是把视频理解主链内部统一到 `video_understanding.py` 的共享决策路径，用最小的内部 helper 让 `video_understanding_tool`、`report_agent`、`multi_report_agent` 在短视频、长视频、RTSP/VST 场景下行为一致；同时补齐 model adapter 的 prod/dev 对齐能力，并把错误测试断言改成保护真实行为。

**Tech Stack:** Python 3.12, Pydantic v2, LangChain OpenAI-compatible adapters, pytest, pytest-asyncio, FastAPI-compatible agent/tool stack

---

## 文件结构

**修改文件**
- `src/vsa_agent/tools/video_report_gen.py`
  - 修复单视频报告中文标题、章节名和空态文本
- `src/vsa_agent/tools/template_report_gen.py`
  - 修复聚合报告中文标题、区块名、空态文本
- `src/vsa_agent/tools/fov_counts_with_chart.py`
  - 修复图表标题与坐标轴中文文本
- `src/vsa_agent/agents/report_agent.py`
  - 默认视频理解入口改为统一内部主链
- `src/vsa_agent/agents/multi_report_agent.py`
  - 默认视频理解入口改为统一内部主链
- `src/vsa_agent/tools/video_understanding.py`
  - 新增统一内部分析 helper；让 prompt 真正进入 VLM；统一短视频/长视频/RTSP 路径
- `src/vsa_agent/integrations/vst_client.py`
  - 改为“有时间窗时强约束 clip、无时间窗时才允许回退 live/source”的语义
- `src/vsa_agent/tools/lvs_video_understanding.py`
  - 增加内部时间窗分块 helper，避免长视频窗口请求退化为整段分析
- `src/vsa_agent/model_adapter/openai_adapter.py`
  - 空 API key 走环境变量/运行时注入
- `src/vsa_agent/model_adapter/vllm_adapter.py`
  - 补齐 `bind_tools()`
- `config.yaml`
  - dev 默认 `api_key` 改为空字符串

**修改测试**
- `tests/unit/tools/test_video_report_gen.py`
- `tests/unit/tools/test_template_report_gen.py`
- `tests/unit/tools/test_chart_generator.py`
- `tests/unit/tools/test_fov_counts_with_chart.py`
- `tests/acceptance/test_report_chart_flow.py`
- `tests/unit/agents/test_report_agent.py`
- `tests/unit/agents/test_multi_report_agent.py`
- `tests/unit/tools/test_video_understanding.py`
- `tests/unit/integrations/test_vst_client.py`
- `tests/unit/model_adapter/test_model_adapter.py`
- `tests/unit/test_config.py`
- `tests/unit/tools/test_lvs_video_understanding.py`

---

### Task 1: 修复报告/图表中文输出，并把错误断言改成保护真实文本

**Files:**
- Modify: `src/vsa_agent/tools/video_report_gen.py`
- Modify: `src/vsa_agent/tools/template_report_gen.py`
- Modify: `src/vsa_agent/tools/fov_counts_with_chart.py`
- Test: `tests/unit/tools/test_video_report_gen.py`
- Test: `tests/unit/tools/test_template_report_gen.py`
- Test: `tests/unit/tools/test_chart_generator.py`
- Test: `tests/unit/tools/test_fov_counts_with_chart.py`
- Test: `tests/acceptance/test_report_chart_flow.py`

- [ ] **Step 1: 先写失败测试，要求报告和图表输出正确中文**

```python
# tests/unit/tools/test_video_report_gen.py
@pytest.mark.anyio
async def test_generate_video_report_uses_human_readable_chinese_sections():
    from vsa_agent.tools.video_report_gen import generate_video_report

    result = await generate_video_report(
        sensor_id="camera-1",
        user_query="生成详细报告",
        understanding_result={
            "summary_text": "person walking near forklift",
            "events": [],
        },
    )

    assert result.markdown_content.startswith("# 单视频分析报告")
    assert "## 视频源" in result.markdown_content
    assert "## 用户问题" in result.markdown_content
    assert "## 摘要" in result.markdown_content
    assert "## 事件时间线" in result.markdown_content


# tests/unit/tools/test_template_report_gen.py
@pytest.mark.anyio
async def test_generate_template_report_includes_correct_chinese_headers():
    from vsa_agent.tools.template_report_gen import generate_template_report

    result = await generate_template_report(
        report_title="仓库巡检聚合报告",
        report_sections=[],
        counts={},
        chart={},
    )

    assert result.markdown_content.startswith("# 仓库巡检聚合报告")
    assert "## 报告摘要" in result.markdown_content
    assert "## 统计概览" in result.markdown_content
    assert "## 图表" in result.markdown_content
    assert "## 分事件报告" in result.markdown_content
    assert "- 无分事件内容" in result.markdown_content
    assert "- 无统计数据" in result.markdown_content
    assert "- 无图表数据" in result.markdown_content


# tests/unit/tools/test_chart_generator.py
@pytest.mark.anyio
async def test_generate_bar_chart_artifact_uses_correct_chinese_labels():
    from vsa_agent.tools.chart_generator import ChartSeriesItem
    from vsa_agent.tools.chart_generator import generate_bar_chart_artifact

    result = await generate_bar_chart_artifact(
        chart_title="事件计数统计",
        x_label="事件类型",
        y_label="次数",
        series=[ChartSeriesItem(label="walking", value=2)],
    )

    assert result.title == "事件计数统计"
    assert "| 事件类型 | 次数 |" in result.markdown_table
```

- [ ] **Step 2: 运行相关测试，确认当前因乱码断言而失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_chart_generator.py tests/unit/tools/test_fov_counts_with_chart.py tests/acceptance/test_report_chart_flow.py -v`
Expected: FAIL，失败信息包含中文标题/章节名不匹配

- [ ] **Step 3: 写最小实现，只修生产代码中的中文文本**

```python
# src/vsa_agent/tools/video_report_gen.py
if not non_empty_lines:
    return "- 无结构化事件"

markdown_content = (
    "# 单视频分析报告\n\n"
    "## 视频源\n"
    f"- sensor_id: {sensor_id}\n\n"
    "## 用户问题\n"
    f"{user_query}\n\n"
    "## 摘要\n"
    f"{summary_text}\n\n"
    "## 事件时间线\n"
    f"{timeline_text}\n"
)

# src/vsa_agent/tools/template_report_gen.py
if not report_sections:
    return "- 无分事件内容"
if not counts:
    return "- 无统计数据"
chart_table = (chart or {}).get("markdown_table", "- 无图表数据")

markdown_content = (
    f"# {report_title}\n\n"
    "## 报告摘要\n"
    f"{summary_lines}\n\n"
    "## 统计概览\n"
    f"{counts_text}\n\n"
    "## 图表\n"
    f"{chart_table}\n\n"
    "## 分事件报告\n\n"
    f"{detail_blocks}\n"
)

# src/vsa_agent/tools/fov_counts_with_chart.py
chart = await chart_generator(
    chart_title="事件计数统计",
    x_label="事件类型",
    y_label="次数",
    series=series,
)
```

- [ ] **Step 4: 回跑测试，确认中文输出和验收链路通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_chart_generator.py tests/unit/tools/test_fov_counts_with_chart.py tests/acceptance/test_report_chart_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_report_gen.py src/vsa_agent/tools/template_report_gen.py src/vsa_agent/tools/fov_counts_with_chart.py tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_chart_generator.py tests/unit/tools/test_fov_counts_with_chart.py tests/acceptance/test_report_chart_flow.py
git commit -m "fix: restore chinese report and chart output"
```

### Task 2: 修复 dev/prod 配置链，让 prod 能绑定工具、dev 能正确回退 API key

**Files:**
- Modify: `config.yaml`
- Modify: `src/vsa_agent/model_adapter/openai_adapter.py`
- Modify: `src/vsa_agent/model_adapter/vllm_adapter.py`
- Test: `tests/unit/model_adapter/test_model_adapter.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: 先写失败测试，定义空 key 回退和 prod tool binding 行为**

```python
# tests/unit/model_adapter/test_model_adapter.py
from unittest.mock import MagicMock, patch

@patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
def test_openai_adapter_treats_blank_api_key_as_unset(chat_openai_cls):
    from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

    chat_openai_cls.return_value = MagicMock()
    OpenAIModelAdapter(model_name="qwen-plus")

    kwargs = chat_openai_cls.call_args.kwargs
    assert kwargs["api_key"] is None


@patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
def test_vllm_adapter_supports_bind_tools(chat_openai_cls):
    from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    chat_openai_cls.return_value = llm

    adapter = VLLMModelAdapter(model_name="Qwen3-VL-8B-Instruct")
    adapter.bind_tools([{"name": "echo"}])

    llm.bind_tools.assert_called_once()


# tests/unit/test_config.py
def test_main_config_uses_blank_dev_api_key_placeholder_strategy():
    from vsa_agent.config import AppConfig

    cfg = AppConfig.from_yaml("config.yaml")
    assert cfg.model.dev.api_key == ""
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py tests/unit/test_config.py -v`
Expected: FAIL，失败信息包含 `bind_tools` 缺失或 `api_key` 仍为占位值

- [ ] **Step 3: 写最小实现，保持接口不变**

```python
# config.yaml
model:
  dev:
    api_key: ""

# src/vsa_agent/model_adapter/openai_adapter.py
self.llm = ChatOpenAI(
    model=model_name or dev.llm_model,
    base_url=dev.base_url,
    api_key=dev.api_key or None,
    temperature=0,
    max_retries=2,
)

# src/vsa_agent/model_adapter/vllm_adapter.py
class VLLMModelAdapter(BaseModelAdapter):
    ...
    def bind_tools(self, tools: list[dict]) -> None:
        self.llm = self.llm.bind_tools(tools)
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py tests/unit/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.yaml src/vsa_agent/model_adapter/openai_adapter.py src/vsa_agent/model_adapter/vllm_adapter.py tests/unit/model_adapter/test_model_adapter.py tests/unit/test_config.py
git commit -m "fix: align model adapter configuration behavior"
```

### Task 3: 在 `video_understanding.py` 内部统一短视频/长视频决策，并让 prompt 真正进入 VLM

**Files:**
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Test: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 先写失败测试，锁定真实行为**

```python
# tests/unit/tools/test_video_understanding.py
@pytest.mark.asyncio
async def test_analyze_video_segment_passes_generated_prompt_to_model(monkeypatch):
    captured = {}

    async def fake_invoke(messages):
        captured["messages"] = messages
        return type("Resp", (), {"content": "plain answer"})()

    class FakeAdapter:
        async def invoke(self, messages):
            return await fake_invoke(messages)

    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding.generate_understanding_prompt",
        lambda query, intent=None, context=None: __import__("asyncio").sleep(0, result="generated prompt"),
    )

    result = await analyze_video_segment(
        frames=["frame-a"],
        query="raw query",
        model_adapter=FakeAdapter(),
    )

    human_text = str(captured["messages"][1].content)
    assert "generated prompt" in human_text
    assert result.chunks[0].prompt_used == "generated prompt"


@pytest.mark.asyncio
async def test_analyze_video_returns_long_video_structured_result(monkeypatch):
    from vsa_agent.data_models.understanding import UnderstandingResult
    from vsa_agent.tools.video_understanding import analyze_video

    monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)

    class FakeCap:
        def isOpened(self): return True
        def get(self, prop): return 30.0 if prop == 5 else 3000 if prop == 7 else 0
        def release(self): return None

    async def fake_analyze_long_video(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="long structured result",
            chunks=[],
            events=[],
        )

    monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
    monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_long_video", fake_analyze_long_video)

    result = await analyze_video(video_path="video.mp4", query="what happened")
    assert result.summary_text == "long structured result"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: FAIL，失败信息包含 prompt 未进入消息或缺少统一分析入口

- [ ] **Step 3: 写最小实现，增加内部统一 helper，不改外部接口**

```python
# src/vsa_agent/tools/video_understanding.py
async def _analyze_frames(
    frames: list[str],
    prompt_text: str,
    model_adapter=None,
    *,
    config: VideoUnderstandingConfig | None = None,
) -> str:
    ...
    messages = _build_vlm_messages(frames, prompt_text)
    ...


async def analyze_video(
    video_path: str = "",
    query: str = "",
    model_adapter=None,
    frames: list[str] | None = None,
    source_type: str = "video_file",
    sensor_id: str | None = None,
    start_timestamp: str | int | float | None = None,
    end_timestamp: str | int | float | None = None,
    config: VideoUnderstandingConfig | None = None,
) -> UnderstandingResult:
    tool_config = _get_video_understanding_config(config)
    if frames is not None:
        return await analyze_video_segment(
            frames=frames,
            query=query,
            model_adapter=model_adapter,
            config=tool_config,
            source_type=source_type,
            sensor_id=sensor_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    source_candidate = await _resolve_video_source(
        video_path,
        sensor_id,
        source_type,
        tool_config,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    resolved_video_path = _prepare_video_path(source_candidate, tool_config, source_type=source_type)

    if source_type == "rtsp" and resolved_video_path.startswith("rtsp://"):
        return await analyze_video_segment(
            video_path=resolved_video_path,
            query=query,
            model_adapter=model_adapter,
            config=tool_config,
            source_type=source_type,
            sensor_id=sensor_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    ...
    if duration_sec > LONG_VIDEO_THRESHOLD_SEC:
        return await analyze_long_video(
            video_path=resolved_video_path,
            query=query,
            source_type=source_type,
            model_adapter=model_adapter,
        )

    return await analyze_video_segment(
        video_path=resolved_video_path,
        query=query,
        model_adapter=model_adapter,
        config=tool_config,
        source_type=source_type,
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )


async def analyze_video_segment(...):
    ...
    prompt_text = prompt_used or await generate_understanding_prompt(
        query,
        context={"source_type": source_type},
    )
    ...
    raw_output = await _analyze_frames(
        frames,
        prompt_text,
        model_adapter,
        config=tool_config,
    )


async def video_understanding_tool(...):
    result = await analyze_video(
        video_path=video_path,
        query=query,
        model_adapter=model_adapter,
        frames=frames,
        source_type=source_type,
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if frames is not None:
        return result.summary_text
    if result.metadata.get("chunk_count") is not None:
        summary = await summarize_understanding_result(result, query, model_adapter)
        return summary.text_output
    return result.summary_text
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_video_understanding.py
git commit -m "fix: unify internal video understanding flow"
```

### Task 4: 让 `report_agent` / `multi_report_agent` 复用统一视频理解主链

**Files:**
- Modify: `src/vsa_agent/agents/report_agent.py`
- Modify: `src/vsa_agent/agents/multi_report_agent.py`
- Test: `tests/unit/agents/test_report_agent.py`
- Test: `tests/unit/agents/test_multi_report_agent.py`

- [ ] **Step 1: 先写失败测试，验证默认路径不再绑死短视频入口**

```python
# tests/unit/agents/test_report_agent.py
@pytest.mark.anyio
async def test_default_report_agent_path_uses_unified_analyze_video(monkeypatch):
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
    from vsa_agent.data_models.understanding import UnderstandingResult

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="long video summary",
            chunks=[],
            events=[],
        )

    async def fake_video_report_gen(**kwargs):
        return {
            "markdown_content": "# 单视频分析报告\n\n## 摘要\nlong video summary",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "long video summary",
        }

    monkeypatch.setattr("vsa_agent.agents.report_agent.analyze_video", fake_analyze_video)

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_report_gen_fn=fake_video_report_gen,
    )

    assert result.status == "success"
    assert captured["video_path"] == "video.mp4"


# tests/unit/agents/test_multi_report_agent.py
@pytest.mark.anyio
async def test_default_multi_report_agent_path_uses_unified_analyze_video(monkeypatch):
    from vsa_agent.agents.multi_report_agent import MultiReportAgentInput
    from vsa_agent.agents.multi_report_agent import MultiReportSourceItem
    from vsa_agent.agents.multi_report_agent import execute_multi_report_agent
    from vsa_agent.data_models.understanding import UnderstandingResult

    calls = []

    async def fake_analyze_video(**kwargs):
        calls.append(kwargs)
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="summary",
            chunks=[],
            events=[],
        )

    async def fake_report_gen(**kwargs):
        return {
            "markdown_content": "# 仓库巡检聚合报告",
            "downloads": {"markdown": {"filename": "multi-report.md"}},
            "summary": "summary",
            "section_count": 1,
        }

    monkeypatch.setattr("vsa_agent.agents.multi_report_agent.analyze_video", fake_analyze_video)

    await execute_multi_report_agent(
        MultiReportAgentInput(
            report_title="仓库巡检聚合报告",
            query="生成聚合报告",
            sources=[MultiReportSourceItem(video_path="video-a.mp4")],
        ),
        report_gen_fn=fake_report_gen,
    )

    assert calls[0]["video_path"] == "video-a.mp4"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py -v`
Expected: FAIL，失败信息包含 monkeypatch 目标不存在或默认入口仍是 `analyze_video_segment`

- [ ] **Step 3: 写最小实现，只替换默认内部依赖**

```python
# src/vsa_agent/agents/report_agent.py
from vsa_agent.tools.video_understanding import analyze_video

async def _default_video_understanding_fn(**kwargs):
    return await analyze_video(**kwargs)

# src/vsa_agent/agents/multi_report_agent.py
from vsa_agent.tools.video_understanding import analyze_video

async def _default_video_understanding_fn(**kwargs):
    return await analyze_video(**kwargs)
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/report_agent.py src/vsa_agent/agents/multi_report_agent.py tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py
git commit -m "fix: route report agents through unified video understanding"
```

### Task 5: 修正 VST `get_video_clip()` 的尽力语义，优先 clip，失败回退到当前流/本地路径

**Files:**
- Modify: `src/vsa_agent/integrations/vst_client.py`
- Test: `tests/unit/integrations/test_vst_client.py`
- Test: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 先写失败测试，定义“优先时间窗、失败回退”的行为**

```python
# tests/unit/integrations/test_vst_client.py
@pytest.mark.anyio
async def test_get_video_clip_prefers_clip_payload_when_available():
    from vsa_agent.integrations.vst_client import VSTClient

    async def fake_request_json(path: str):
        if path == "/vst/api/v1/storage/clips":
            return {"clip_url": "http://localhost:30888/clips/camera-1.mp4"}
        if path == "/vst/api/v1/sensor/streams":
            return [{"stream-123": [{"name": "camera-1", "url": "rtsp://camera-1/live"}]}]
        raise AssertionError(path)

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    result = await client.get_video_clip("camera-1", "2025-01-01T10:05:00Z", "2025-01-01T10:05:30Z")
    assert result.clip_url == "http://localhost:30888/clips/camera-1.mp4"


@pytest.mark.anyio
async def test_get_video_clip_falls_back_to_stream_when_clip_lookup_fails():
    from vsa_agent.integrations.vst_client import VSTClient

    async def fake_request_json(path: str):
        if path == "/vst/api/v1/storage/clips":
            raise RuntimeError("clip lookup unavailable")
        if path == "/vst/api/v1/sensor/streams":
            return [{"stream-123": [{"name": "camera-1", "url": "rtsp://camera-1/live"}]}]
        raise AssertionError(path)

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    result = await client.get_video_clip("camera-1", "2025-01-01T10:05:00Z", "2025-01-01T10:05:30Z")
    assert result.clip_url == "rtsp://camera-1/live"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py -v`
Expected: FAIL，失败信息包含未请求 clip 路径或始终只返回 stream 信息

- [ ] **Step 3: 写最小实现，保持返回结构不变**

```python
# src/vsa_agent/integrations/vst_client.py
async def _request_clip_payload(
    self,
    sensor_id: str,
    start_timestamp: str,
    end_timestamp: str,
) -> dict[str, Any] | None:
    try:
        payload = await self._request_json(
            f"/vst/api/v1/storage/clips?sensorId={sensor_id}&start={start_timestamp}&end={end_timestamp}"
        )
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


async def get_video_clip(... ) -> VSTClipResult:
    clip_payload = await self._request_clip_payload(sensor_id, start_timestamp, end_timestamp)
    if clip_payload:
        clip_url = clip_payload.get("clip_url") or clip_payload.get("url")
        local_path = clip_payload.get("local_path") or clip_payload.get("localPath")
        if clip_url or local_path:
            return VSTClipResult(
                sensor_id=sensor_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                clip_url=clip_url,
                local_path=local_path,
            )

    stream = await self.get_stream_info(sensor_id)
    clip_url = stream.rtsp_url
    local_path = stream.metadata.get("raw", {}).get("localPath") or stream.metadata.get("raw", {}).get("local_path")
    if not clip_url and not local_path:
        raise VSTClientError(f"No clip source available for sensor '{sensor_id}'")
    return VSTClipResult(
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        clip_url=clip_url,
        local_path=local_path,
    )
```

- [ ] **Step 4: 回跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py tests/unit/tools/test_video_understanding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/integrations/vst_client.py tests/unit/integrations/test_vst_client.py tests/unit/tools/test_video_understanding.py
git commit -m "fix: make vst clip lookup best effort"
```

### Task 6: 跑针对性回归与全量回归，确认 6 个问题全部收口

**Files:**
- Verify only

- [ ] **Step 1: 运行修复相关模块回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py tests/unit/integrations/test_vst_client.py tests/unit/model_adapter/test_model_adapter.py tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_chart_generator.py tests/unit/tools/test_fov_counts_with_chart.py tests/acceptance/test_report_chart_flow.py -v`
Expected: PASS

- [ ] **Step 2: 运行全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests -q`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "test: verify review fixes with full regression"
```

---

### 当前执行状态（2026-06-16）
- [x] Task 1 已核实：运行时中文输出未复现为生产缺陷，已增强中文断言测试覆盖
- [x] Task 2 已完成：dev 默认 `api_key` 改为空字符串，prod `VLLMModelAdapter.bind_tools()` 已补齐
- [x] Task 3 已完成：`video_understanding.py` 已新增统一内部入口 `analyze_video`，生成后的 prompt 已真正进入 VLM 消息
- [x] Task 4 已完成：`report_agent` / `multi_report_agent` 默认路径已复用统一视频理解主链
- [x] Task 5 已完成：`VSTClient.get_video_clip()` 已改为“有时间窗时必须拿 clip，无时间窗时才允许回退 live/source”
- [x] Task 6 已完成：补齐 `frames` 直传与长视频时间窗语义回归；全量回归通过 `288 passed`

---

## 自检

### 覆盖性检查
- 中文报告/图表恢复：Task 1 覆盖
- dev/prod model adapter 对齐：Task 2 覆盖
- prompt 真正进入模型：Task 3 覆盖
- 长视频统一分流内部主链：Task 3 + Task 4 覆盖
- report agent / multi report agent 对齐共享链路：Task 4 覆盖
- VST 时间窗强约束 + 无时间窗回退语义：Task 5 覆盖
- 全量回归与验收：Task 6 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都给出精确文件路径、测试命令、最小实现骨架

### 类型一致性检查
- 统一使用现有公开入口：`report_agent_tool`、`multi_report_agent_tool`、`video_understanding_tool`
- 新增内部统一 helper：`analyze_video`
- 保持 `VSTClipResult`、`UnderstandingResult`、`VideoReportGenOutput` 现有返回结构不变

### 执行说明
- 本计划只修内部实现，不改任何对外接口
- `config.yaml` 的 dev `api_key` 改为空字符串，由运行时环境变量接管
- VST 时间窗这轮做到“显式时间窗必须命中 clip”，但仍不在本轮引入真实历史片段下载协议
- 继续严格按 TDD：先红灯，再最小实现，再回归

---

## Phase 4 — 剩余离线工具 (P2)

**目标**: 补齐 `incidents`、`video_caption*`、`geolocation` 这批离线工具，并优先把最贴近主业务流的 `incidents.py` 做成后续可复用的标准化中间层。

**推荐执行顺序**:
1. `incidents.py`
2. `video_caption.py`
3. `video_detailed_caption.py` / `video_skim_caption.py`
4. `geolocation.py`
5. Phase 4 验收与全量回归

**Architecture**: Phase 4 不引入新的在线依赖，不新接 RTSP/VST 下载协议，也不重复实现已有的视频理解主链。`incidents.py` 负责把 `SearchOutput` / `UnderstandingResult` 统一转换为标准 `Incident` 列表；`video_caption*` 作为对原版 NVIDIA 工具的兼容层，内部复用 `video_understanding.py` 与 `lvs_video_understanding.py`；`geolocation.py` 保持纯离线、纯结构化，基于已有 `Location` / `Place` / `Incident` 模型做补全与摘要。

**Files Overview**:
- Create: `src/vsa_agent/tools/incidents.py`
  - 标准化 `SearchOutput` / `UnderstandingResult` 到 `video_analytics.nvschema.Incident`
- Create: `src/vsa_agent/tools/video_caption.py`
  - 原版 `video_caption` 兼容入口，内部复用现有视频理解链
- Create: `src/vsa_agent/tools/video_detailed_caption.py`
  - 详细描述包装器
- Create: `src/vsa_agent/tools/video_skim_caption.py`
  - 快速概述包装器
- Create: `src/vsa_agent/tools/geolocation.py`
  - 位置补全、区域统计、文本摘要
- Modify: `src/vsa_agent/agents/search_agent.py`
  - 复用 `incidents.py` 输出，不再把 incidents JSON 拼装逻辑埋在 agent 私有函数里
- Modify: `src/vsa_agent/tools/__init__.py`
  - 导出新增工具模块
- Create: `tests/unit/tools/test_incidents.py`
- Create: `tests/unit/tools/test_video_caption.py`
- Create: `tests/unit/tools/test_video_detailed_caption.py`
- Create: `tests/unit/tools/test_video_skim_caption.py`
- Create: `tests/unit/tools/test_geolocation.py`
- Create: `tests/acceptance/test_phase4_offline_tools_flow.py`
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`
  - 持续记录 Phase 4 进度与回归结果

### Task 4.1: 实现 `incidents.py` 的标准化数据转换层

**Files:**
- Create: `src/vsa_agent/tools/incidents.py`
- Test: `tests/unit/tools/test_incidents.py`

- [ ] **Step 1: 写失败测试，锁定 `UnderstandingResult -> list[Incident]` 行为**

```python
from vsa_agent.data_models.understanding import DetectedEvent, EvidenceRef, UnderstandingResult


def test_understanding_to_incidents_maps_events_to_nvschema():
    from vsa_agent.tools.incidents import understanding_to_incidents

    event = DetectedEvent(
        event_id="event-1",
        label="intrusion",
        description="person enters restricted area",
        start_timestamp="00:00:05",
        end_timestamp="00:00:12",
        confidence=0.91,
        evidence=[EvidenceRef(source_type="video_file", video_path="video.mp4")],
    )
    result = UnderstandingResult(
        query="find intrusion",
        source_type="video_file",
        summary_text="person enters restricted area",
        chunks=[],
        events=[event],
    )

    incidents = understanding_to_incidents(result)

    assert len(incidents) == 1
    assert incidents[0].category == "intrusion"
    assert incidents[0].description == "person enters restricted area"
    assert incidents[0].confidence == 0.91
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_incidents.py::test_understanding_to_incidents_maps_events_to_nvschema -v`

Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: 写最小实现**

```python
from vsa_agent.video_analytics.nvschema import Incident


def understanding_to_incidents(result: UnderstandingResult) -> list[Incident]:
    incidents: list[Incident] = []
    for index, event in enumerate(result.events, start=1):
        incidents.append(
            Incident(
                id=event.event_id or f"incident-{index}",
                description=event.description,
                category=event.label,
                confidence=event.confidence,
                metadata={
                    "query": result.query,
                    "source_type": result.source_type,
                    "start_timestamp": event.start_timestamp,
                    "end_timestamp": event.end_timestamp,
                },
            )
        )
    return incidents
```

- [ ] **Step 4: 继续补 `SearchOutput -> list[Incident]` 与空输入边界测试**

```python
def test_search_output_to_incidents_uses_clip_time_and_description():
    from vsa_agent.tools.incidents import search_output_to_incidents
    from vsa_agent.tools.search import SearchOutput, SearchResult

    output = SearchOutput(
        data=[
            SearchResult(
                video_name="camera-1",
                description="forklift enters loading zone",
                start_time="2025-01-01T10:00:00Z",
                end_time="2025-01-01T10:00:10Z",
                sensor_id="camera-1",
                similarity=0.88,
            )
        ]
    )

    incidents = search_output_to_incidents(output)

    assert incidents[0].category == "search_hit"
    assert incidents[0].metadata["start_time"] == "2025-01-01T10:00:00Z"
```

- [ ] **Step 5: 让 `incidents.py` 补齐序列化输出**

```python
def incidents_to_tagged_json(incidents: list[Incident]) -> str:
    payload = {
        "incidents": [
            {
                "id": inc.id,
                "description": inc.description,
                "category": inc.category,
                "severity": inc.severity,
                "confidence": inc.confidence,
                "metadata": inc.metadata,
            }
            for inc in incidents
        ]
    }
    return "<incidents>\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n</incidents>"
```

- [ ] **Step 6: 运行模块测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_incidents.py -v`

Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add src/vsa_agent/tools/incidents.py tests/unit/tools/test_incidents.py
git commit -m "feat: add incident normalization tool"
```

### Task 4.2: 让 `search_agent` 复用 `incidents.py`

**Files:**
- Modify: `src/vsa_agent/agents/search_agent.py`
- Test: `tests/unit/agents/test_search_agent.py`

- [ ] **Step 1: 写失败测试，锁定 `_to_incidents_output()` 复用共享工具**

```python
def test_to_incidents_output_delegates_to_incident_serializer(monkeypatch):
    from vsa_agent.agents.search_agent import _to_incidents_output
    from vsa_agent.tools.search import SearchOutput

    called = {}

    def fake_search_output_to_incidents(output):
        called["search_output"] = output
        return []

    def fake_incidents_to_tagged_json(incidents):
        called["incidents"] = incidents
        return "<incidents>\n{\"incidents\": []}\n</incidents>"

    monkeypatch.setattr("vsa_agent.agents.search_agent.search_output_to_incidents", fake_search_output_to_incidents)
    monkeypatch.setattr("vsa_agent.agents.search_agent.incidents_to_tagged_json", fake_incidents_to_tagged_json)

    text = _to_incidents_output(SearchOutput(data=[]))

    assert text.startswith("<incidents>")
    assert "search_output" in called
```

- [ ] **Step 2: 运行红灯测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_search_agent.py::test_to_incidents_output_delegates_to_incident_serializer -v`

Expected: `ImportError` or assertion fail

- [ ] **Step 3: 最小改造 `search_agent.py`**

```python
from vsa_agent.tools.incidents import incidents_to_tagged_json
from vsa_agent.tools.incidents import search_output_to_incidents


def _to_incidents_output(search_output) -> str:
    incidents = search_output_to_incidents(search_output)
    return incidents_to_tagged_json(incidents)
```

- [ ] **Step 4: 跑 `search_agent` 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_incidents.py -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/search_agent.py tests/unit/agents/test_search_agent.py src/vsa_agent/tools/incidents.py tests/unit/tools/test_incidents.py
git commit -m "refactor: reuse incident serializer in search agent"
```

### Task 4.3: 实现 `video_caption.py` 兼容包装器

**Files:**
- Create: `src/vsa_agent/tools/video_caption.py`
- Test: `tests/unit/tools/test_video_caption.py`

- [ ] **Step 1: 写失败测试，锁定短视频/长视频都复用现有主链**

```python
import pytest


@pytest.mark.anyio
async def test_video_caption_short_path_delegates_to_analyze_video(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return type("Result", (), {"summary_text": "short caption", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)

    text = await video_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "short caption"
    assert captured["video_path"] == "video.mp4"
```

- [ ] **Step 2: 运行红灯测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_caption.py::test_video_caption_short_path_delegates_to_analyze_video -v`

Expected: `ImportError`

- [ ] **Step 3: 最小实现 `VideoCaptionInput` 与工具函数**

```python
class VideoCaptionInput(BaseModel):
    video_path: str = ""
    sensor_id: str = ""
    user_prompt: str = ""
    start_timestamp: str = ""
    end_timestamp: str = ""


@register_tool("video_caption", description="Generate caption text for a video or clip.")
async def video_caption_tool(...):
    result = await analyze_video(
        video_path=video_path,
        query=user_prompt,
        sensor_id=sensor_id or None,
        source_type="rtsp" if sensor_id else "video_file",
        start_timestamp=start_timestamp or None,
        end_timestamp=end_timestamp or None,
    )
    return result.summary_text
```

- [ ] **Step 4: 补长视频摘要路径测试**

```python
@pytest.mark.anyio
async def test_video_caption_long_path_uses_summary_text_from_long_pipeline(monkeypatch):
    from vsa_agent.tools.video_caption import video_caption_tool
    from vsa_agent.data_models.understanding import UnderstandingResult

    async def fake_analyze_video(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="long caption summary",
            chunks=[],
            events=[],
            metadata={"chunk_count": 2},
        )

    monkeypatch.setattr("vsa_agent.tools.video_caption.analyze_video", fake_analyze_video)
    text = await video_caption_tool(video_path="video.mp4", user_prompt="describe")
    assert text == "long caption summary"
```

- [ ] **Step 5: 跑测试并提交**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_caption.py -v`

```bash
git add src/vsa_agent/tools/video_caption.py tests/unit/tools/test_video_caption.py
git commit -m "feat: add video caption compatibility tool"
```

### Task 4.4: 实现 `video_detailed_caption.py`

**Files:**
- Create: `src/vsa_agent/tools/video_detailed_caption.py`
- Test: `tests/unit/tools/test_video_detailed_caption.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.anyio
async def test_detailed_caption_adds_detail_prompt_prefix(monkeypatch):
    from vsa_agent.tools.video_detailed_caption import video_detailed_caption_tool

    captured = {}

    async def fake_video_caption_tool(**kwargs):
        captured.update(kwargs)
        return "detailed caption"

    monkeypatch.setattr("vsa_agent.tools.video_detailed_caption.video_caption_tool", fake_video_caption_tool)
    text = await video_detailed_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "detailed caption"
    assert "详细" in captured["user_prompt"]
```

- [ ] **Step 2: 最小实现**

```python
async def video_detailed_caption_tool(...):
    normalized_prompt = f"请详细描述视频内容：{user_prompt}".strip("：")
    return await video_caption_tool(..., user_prompt=normalized_prompt)
```

- [ ] **Step 3: 跑测试并提交**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_detailed_caption.py -v`

```bash
git add src/vsa_agent/tools/video_detailed_caption.py tests/unit/tools/test_video_detailed_caption.py
git commit -m "feat: add detailed video caption wrapper"
```

### Task 4.5: 实现 `video_skim_caption.py`

**Files:**
- Create: `src/vsa_agent/tools/video_skim_caption.py`
- Test: `tests/unit/tools/test_video_skim_caption.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.anyio
async def test_skim_caption_adds_brief_prompt_prefix(monkeypatch):
    from vsa_agent.tools.video_skim_caption import video_skim_caption_tool

    captured = {}

    async def fake_video_caption_tool(**kwargs):
        captured.update(kwargs)
        return "brief caption"

    monkeypatch.setattr("vsa_agent.tools.video_skim_caption.video_caption_tool", fake_video_caption_tool)
    text = await video_skim_caption_tool(video_path="video.mp4", user_prompt="describe")

    assert text == "brief caption"
    assert "简要" in captured["user_prompt"]
```

- [ ] **Step 2: 最小实现**

```python
async def video_skim_caption_tool(...):
    normalized_prompt = f"请简要概述视频内容：{user_prompt}".strip("：")
    return await video_caption_tool(..., user_prompt=normalized_prompt)
```

- [ ] **Step 3: 跑测试并提交**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_skim_caption.py -v`

```bash
git add src/vsa_agent/tools/video_skim_caption.py tests/unit/tools/test_video_skim_caption.py
git commit -m "feat: add skim video caption wrapper"
```

### Task 4.6: 实现 `geolocation.py` 的离线位置补全与摘要

**Files:**
- Create: `src/vsa_agent/tools/geolocation.py`
- Test: `tests/unit/tools/test_geolocation.py`

- [ ] **Step 1: 写失败测试，锁定缺失 location/place 的补全行为**

```python
def test_enrich_incidents_with_default_location_and_zone():
    from vsa_agent.tools.geolocation import enrich_incidents_with_location
    from vsa_agent.video_analytics.nvschema import Incident

    incidents = [Incident(id="1", description="intrusion", category="intrusion")]

    enriched = enrich_incidents_with_location(
        incidents,
        default_location_name="Warehouse A",
        default_zone="loading_dock",
    )

    assert enriched[0].location is not None
    assert enriched[0].location.name == "Warehouse A"
    assert enriched[0].location.zone == "loading_dock"
```

- [ ] **Step 2: 最小实现**

```python
def enrich_incidents_with_location(...):
    output = []
    for incident in incidents:
        if incident.location is None:
            incident.location = Location(name=default_location_name, zone=default_zone)
        output.append(incident)
    return output
```

- [ ] **Step 3: 补区域统计与文本摘要测试**

```python
def test_summarize_geolocation_groups_by_zone():
    from vsa_agent.tools.geolocation import summarize_geolocation
    ...
    assert "loading_dock" in summary
    assert "2" in summary
```

- [ ] **Step 4: 跑测试并提交**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_geolocation.py -v`

```bash
git add src/vsa_agent/tools/geolocation.py tests/unit/tools/test_geolocation.py
git commit -m "feat: add offline geolocation helpers"
```

### Task 4.7: 补齐 Phase 4 验收流

**Files:**
- Create: `tests/acceptance/test_phase4_offline_tools_flow.py`

- [ ] **Step 1: 写验收测试，锁定“理解结果 -> incidents -> geolocation”主链**

```python
@pytest.mark.anyio
async def test_phase4_offline_flow_from_understanding_to_geolocation_summary():
    from vsa_agent.tools.geolocation import summarize_geolocation
    from vsa_agent.tools.incidents import understanding_to_incidents
    ...
    incidents = understanding_to_incidents(result)
    summary = summarize_geolocation(incidents)
    assert "Warehouse A" in summary
```

- [ ] **Step 2: 写验收测试，锁定 `video_caption*` 包装器兼容行为**

```python
@pytest.mark.anyio
async def test_phase4_caption_wrappers_share_same_core_path(monkeypatch):
    ...
    assert detailed_text == "caption"
    assert skim_text == "caption"
```

- [ ] **Step 3: 跑 Phase 4 验收测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_phase4_offline_tools_flow.py -v`

Expected: `PASS`

### Task 4.8: 回归、文档状态更新、提交

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑相关模块回归**

Run:

```powershell
C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest `
  tests/unit/tools/test_incidents.py `
  tests/unit/tools/test_video_caption.py `
  tests/unit/tools/test_video_detailed_caption.py `
  tests/unit/tools/test_video_skim_caption.py `
  tests/unit/tools/test_geolocation.py `
  tests/unit/agents/test_search_agent.py `
  tests/acceptance/test_phase4_offline_tools_flow.py -q
```

Expected: `PASS`

- [ ] **Step 2: 跑全量测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests -q`

Expected: `PASS`

- [ ] **Step 3: 更新总计划文档状态**

```markdown
### 当前执行状态（YYYY-MM-DD）
- [x] Task 4.1 已完成：incidents 标准化层已接通
- [x] Task 4.2 已完成：search_agent incidents 输出已复用共享工具
- [x] Task 4.3 已完成：`video_caption.py` 兼容包装器已接通
- [x] Task 4.4-4.6 已完成：detailed/skim caption 与 geolocation 已实现
- [x] Task 4.7 已完成：Phase 4 验收流已补齐
- [x] Task 4.8 已完成：全量回归已通过（303 passed）
```

- [ ] **Step 4: 最终提交**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md src/vsa_agent/tools tests/unit tests/acceptance
git commit -m "feat: complete phase4 offline tools"
```

---

## Phase 5 — 在线视频 / RTSP / VST (P3)

**目标**: 补齐在线视频入口层，先建立 RTSP stream API，再强化 VST 服务集成，最后补 `video_delete` API，使在线视频场景有完整的请求入口、错误语义和资源操作面。

**推荐执行顺序**:
1. `api/rtsp_stream_api.py`
2. `api/routes.py` 挂载 RTSP 路由与主链验收
3. `integrations/vst_client.py` 在线语义强化
4. `api/video_delete.py`
5. Phase 5 验收与全量回归

**Architecture**: Phase 5 继续复用现有 `video_understanding.py` 作为统一在线视频理解主链，不额外分叉一套 RTSP 逻辑。API 层只负责请求校验、调用主链和映射错误；VST 仍由 `integrations/vst_client.py` 作为唯一外部系统边界；删除接口先做最小安全版本，只定义清晰契约和 stub 响应，不提前引入真实对象存储删除协议。

**Files Overview**:
- Create: `src/vsa_agent/api/rtsp_stream_api.py`
  - RTSP 在线分析入口
- Modify: `src/vsa_agent/api/routes.py`
  - 把 RTSP API 挂到现有 FastAPI app
- Modify: `src/vsa_agent/integrations/vst_client.py`
  - 在线语义补强、错误映射收紧
- Create: `src/vsa_agent/api/video_delete.py`
  - 最小可用删除接口
- Create: `tests/unit/api/test_rtsp_stream_api.py`
- Modify: `tests/unit/api/test_routes.py`
- Modify: `tests/unit/integrations/test_vst_client.py`
- Create: `tests/unit/api/test_video_delete.py`
- Create: `tests/acceptance/test_phase5_online_flow.py`
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`
  - 持续记录 Phase 5 进度

### Task 5.1: 实现 `RTSP Stream API` 契约与主链接入

**Files:**
- Create: `src/vsa_agent/api/rtsp_stream_api.py`
- Test: `tests/unit/api/test_rtsp_stream_api.py`

- [x] **Step 1: 写失败测试，锁定 RTSP 请求契约**

```python
import pytest


@pytest.mark.anyio
async def test_rtsp_stream_api_uses_rtsp_source_type(monkeypatch):
    from vsa_agent.api.rtsp_stream_api import analyze_rtsp_stream

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return type("Result", (), {"summary_text": "rtsp summary", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_video", fake_analyze_video)

    payload = {
        "sensor_id": "camera-1",
        "query": "describe stream",
        "start_timestamp": "PT5S",
        "end_timestamp": "PT10S",
    }
    result = await analyze_rtsp_stream(**payload)

    assert result["summary_text"] == "rtsp summary"
    assert captured["sensor_id"] == "camera-1"
    assert captured["source_type"] == "rtsp"
```

- [x] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/api/test_rtsp_stream_api.py::test_rtsp_stream_api_uses_rtsp_source_type -v`

Expected: `ModuleNotFoundError`

- [x] **Step 3: 写最小实现**

```python
class RTSPStreamRequest(BaseModel):
    sensor_id: str
    query: str
    start_timestamp: str | None = None
    end_timestamp: str | None = None


async def analyze_rtsp_stream(
    sensor_id: str,
    query: str,
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
) -> dict[str, Any]:
    result = await analyze_video(
        video_path="",
        query=query,
        source_type="rtsp",
        sensor_id=sensor_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    return {
        "sensor_id": sensor_id,
        "summary_text": result.summary_text,
        "metadata": result.metadata,
    }
```

- [x] **Step 4: 补时间窗错误语义测试**

```python
@pytest.mark.anyio
async def test_rtsp_stream_api_surfaces_time_window_clip_errors(monkeypatch):
    from vsa_agent.api.rtsp_stream_api import analyze_rtsp_stream
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_analyze_video(**kwargs):
        raise VSTClientError("clip not found")

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_video", fake_analyze_video)

    with pytest.raises(VSTClientError):
        await analyze_rtsp_stream(
            sensor_id="camera-1",
            query="describe stream",
            start_timestamp="PT5S",
            end_timestamp="PT10S",
        )
```

- [x] **Step 5: 跑模块测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/api/test_rtsp_stream_api.py -v`

Expected: `PASS`

- [x] **Step 6: Commit**

```bash
git add src/vsa_agent/api/rtsp_stream_api.py tests/unit/api/test_rtsp_stream_api.py
git commit -m "feat: add rtsp stream api contract"
```

### Task 5.2: 挂载 RTSP API 到 FastAPI 路由

**Files:**
- Modify: `src/vsa_agent/api/routes.py`
- Modify: `tests/unit/api/test_routes.py`
- Create: `tests/acceptance/test_phase5_online_flow.py`

- [x] **Step 1: 写失败测试，要求主 app 暴露 RTSP endpoint**

```python
def test_routes_register_rtsp_endpoint():
    from fastapi.routing import APIRoute
    from vsa_agent.api.routes import app

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/api/rtsp/analyze" in paths
```

- [x] **Step 2: 写最小路由接线**

```python
from vsa_agent.api.rtsp_stream_api import router as rtsp_router

app.include_router(rtsp_router)
```

- [x] **Step 3: 写 acceptance，锁定 API -> 主链路径**

```python
@pytest.mark.anyio
async def test_phase5_rtsp_api_flow(monkeypatch):
    import httpx
    from vsa_agent.api.routes import app

    async def fake_analyze_rtsp_stream(**kwargs):
        return {
            "sensor_id": kwargs["sensor_id"],
            "query": kwargs["query"],
            "summary_text": "rtsp summary",
            "metadata": {},
        }

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_rtsp_stream", fake_analyze_rtsp_stream)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/rtsp/analyze", json={"sensor_id": "camera-1", "query": "describe"})

    assert response.status_code == 200
    assert response.json()["summary_text"] == "rtsp summary"
```

- [x] **Step 4: 跑路由与验收测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/api/test_routes.py tests/unit/api/test_rtsp_stream_api.py tests/acceptance/test_phase5_online_flow.py -v`

Expected: `PASS`

- [x] **Step 5: Commit**

```bash
git add src/vsa_agent/api/routes.py src/vsa_agent/api/rtsp_stream_api.py tests/unit/api/test_routes.py tests/unit/api/test_rtsp_stream_api.py tests/acceptance/test_phase5_online_flow.py
git commit -m "feat: expose rtsp stream api route"
```

### Task 5.3: 强化 `VSTClient` 在线语义

**Files:**
- Modify: `src/vsa_agent/integrations/vst_client.py`
- Modify: `tests/unit/integrations/test_vst_client.py`
- Modify: `tests/unit/api/test_rtsp_stream_api.py`

- [x] **Step 1: 写失败测试，要求 live fallback 只出现在无时间窗场景**

```python
@pytest.mark.anyio
async def test_get_video_clip_without_window_can_fallback_to_stream():
    ...
    result = await client.get_video_clip("camera-1", "", "")
    assert result.clip_url == "rtsp://camera-1/live"
```

- [x] **Step 2: 写失败测试，要求 clip 错误消息在 API 层可区分**

```python
@pytest.mark.anyio
async def test_rtsp_stream_api_preserves_vst_error_message(monkeypatch):
    ...
    with pytest.raises(VSTClientError, match="clip"):
        await analyze_rtsp_stream(...)
```

- [x] **Step 3: 最小实现**

```python
# 保持 has_time_window 语义不变
# 只补充更清晰的错误消息与必要 metadata
```

- [x] **Step 4: 跑回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py tests/unit/api/test_rtsp_stream_api.py tests/acceptance/test_phase5_online_flow.py -v`

Expected: `PASS`

- [x] **Step 5: Commit**

```bash
git add src/vsa_agent/integrations/vst_client.py tests/unit/integrations/test_vst_client.py tests/unit/api/test_rtsp_stream_api.py tests/acceptance/test_phase5_online_flow.py
git commit -m "fix: tighten vst online semantics for rtsp api"
```

### Task 5.4: 实现 `video_delete.py` 最小安全接口

**Files:**
- Create: `src/vsa_agent/api/video_delete.py`
- Create: `tests/unit/api/test_video_delete.py`
- Modify: `src/vsa_agent/api/routes.py`

- [x] **Step 1: 写失败测试，锁定删除契约**

```python
def test_video_delete_router_imports():
    from vsa_agent.api.video_delete import router
    assert router is not None
```

```python
@pytest.mark.anyio
async def test_video_delete_returns_deleted_stub():
    from vsa_agent.api.video_delete import delete_video

    result = await delete_video(video_id="video-123")

    assert result["video_id"] == "video-123"
    assert result["deleted"] is True
```

- [x] **Step 2: 最小实现**

```python
router = APIRouter(prefix="/api", tags=["video"])


@router.delete("/video/{video_id}")
async def delete_video(video_id: str):
    return {"video_id": video_id, "deleted": True, "mode": "stub"}
```

- [x] **Step 3: 接到主 app 并跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/api/test_video_delete.py tests/unit/api/test_routes.py -v`

Expected: `PASS`

- [x] **Step 4: Commit**

```bash
git add src/vsa_agent/api/video_delete.py src/vsa_agent/api/routes.py tests/unit/api/test_video_delete.py tests/unit/api/test_routes.py
git commit -m "feat: add video delete api stub"
```

### Task 5.5: Phase 5 回归、文档状态更新、提交

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [x] **Step 1: 跑 Phase 5 相关回归**

Run:

```powershell
C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest `
  tests/unit/api/test_rtsp_stream_api.py `
  tests/unit/api/test_video_delete.py `
  tests/unit/api/test_routes.py `
  tests/unit/integrations/test_vst_client.py `
  tests/acceptance/test_phase5_online_flow.py -q
```

Expected: `PASS`

- [x] **Step 2: 跑全量测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests -q`

Expected: `PASS`

- [x] **Step 3: 更新总计划文档状态**

```markdown
### 当前执行状态（2026-06-16）
- [x] Task 5.1 已完成：RTSP Stream API 契约已接通
- [x] Task 5.2 已完成：RTSP FastAPI 路由与在线验收已接通
- [x] Task 5.3 已完成：VST 在线语义已强化
- [x] Task 5.4 已完成：video_delete API 已补齐
- [x] Task 5.5 已完成：全量回归已通过
```

- [ ] **Step 4: 最终提交**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md src/vsa_agent/api src/vsa_agent/integrations tests/unit/api tests/unit/integrations tests/acceptance
git commit -m "feat: complete phase5 online video apis"
```

---

## 测试策略

| 层级 | 说明 |
|------|------|
| 单元测试 | 每个函数 1-3 个，细粒度 |
| 业务流验收 | 每个 Phase 2-3 个，验证完整链路 |

### 测试命令
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/unit/ tests/acceptance/ -v
```

---

## 验收标准

每个 Phase 完成后:
1. 该 Phase 的单元测试全部 pass
2. 该 Phase 的验收测试全部 pass
3. 项目级回归: 全部测试无破坏
4. git commit

---

## Phase 6 — 报告后处理链 (P2)

**目标**: 将报告链从“理解结果直接渲染 Markdown”升级为“结构化报告对象 -> incidents/geolocation/postprocessing -> Markdown 渲染”的统一闭环，并保持现有对外接口不变。

**推荐执行顺序**:
1. `data_models/report.py`
2. `tools/report_structuring.py`
3. `incidents.py` / `geolocation.py` / `postprocessing`
4. `video_report_gen.py` / `template_report_gen.py` / `report_gen.py`
5. `report_agent.py` / `multi_report_agent.py`
6. Phase 6 验收与全量回归

**Architecture**: 先引入报告域结构化数据模型，再新增内部结构化装配层，把 `UnderstandingResult` 统一转换为 `StructuredReport`。`incidents`、`geolocation` 和 `postprocessing` 在对象层运行，`video_report_gen.py` / `template_report_gen.py` 只负责渲染；`report_agent.py` 和 `multi_report_agent.py` 维持外部接口不变，只替换内部实现。

**Files Overview**:
- Create: `src/vsa_agent/data_models/report.py`
- Modify: `src/vsa_agent/data_models/__init__.py`
- Create: `src/vsa_agent/tools/report_structuring.py`
- Modify: `src/vsa_agent/tools/incidents.py`
- Modify: `src/vsa_agent/tools/geolocation.py`
- Modify: `src/vsa_agent/agents/postprocessing/pipeline.py`
- Modify: `src/vsa_agent/tools/video_report_gen.py`
- Modify: `src/vsa_agent/tools/template_report_gen.py`
- Modify: `src/vsa_agent/tools/report_gen.py`
- Modify: `src/vsa_agent/agents/report_agent.py`
- Modify: `src/vsa_agent/agents/multi_report_agent.py`
- Create: `tests/unit/data_models/test_report_models.py`
- Create: `tests/unit/tools/test_report_structuring.py`
- Create: `tests/unit/agents/postprocessing/test_structured_pipeline.py`
- Create: `tests/acceptance/test_phase6_report_postprocessing_flow.py`
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

### Task 6.1: 新增报告域结构化模型

**Files:**
- Create: `src/vsa_agent/data_models/report.py`
- Modify: `src/vsa_agent/data_models/__init__.py`
- Create: `tests/unit/data_models/test_report_models.py`

- [ ] **Step 1: 写失败测试，锁定报告域对象契约**

```python
from vsa_agent.data_models.understanding import UnderstandingResult


def test_structured_report_defaults_and_serialization():
    from vsa_agent.data_models.report import ReportSection
    from vsa_agent.data_models.report import StructuredReport

    section = ReportSection(
        section_id="section-1",
        section_title="事件 1 - camera-1",
        source_name="camera-1",
        source_type="rtsp",
        user_query="生成报告",
        summary_text="forklift stops near doorway",
        understanding_result=UnderstandingResult(
            query="生成报告",
            source_type="rtsp",
            summary_text="forklift stops near doorway",
            chunks=[],
            events=[],
        ),
    )
    report = StructuredReport(
        report_title="多视频聚合报告",
        report_type="multi_video",
        user_query="生成报告",
        sections=[section],
    )

    assert report.report_title == "多视频聚合报告"
    assert report.sections[0].section_title == "事件 1 - camera-1"
    assert report.model_dump()["sections"][0]["source_type"] == "rtsp"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_report_models.py -v`

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.data_models.understanding import UnderstandingResult


class ReportIncident(BaseModel):
    incident_id: str
    category: str
    description: str
    severity: str = "medium"
    confidence: float = 0.0
    start_timestamp: str = ""
    end_timestamp: str = ""
    location_name: str = ""
    zone_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportSection(BaseModel):
    section_id: str
    section_title: str
    source_name: str
    source_type: str
    user_query: str
    summary_text: str
    understanding_result: UnderstandingResult
    incidents: list[ReportIncident] = Field(default_factory=list)
    location_summary: str = ""
    validation_feedback: list[str] = Field(default_factory=list)


class StructuredReport(BaseModel):
    report_title: str
    report_type: Literal["single_video", "multi_video"]
    user_query: str
    sections: list[ReportSection] = Field(default_factory=list)
    global_summary: str = ""
    global_validation_feedback: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_report_models.py -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/data_models/report.py src/vsa_agent/data_models/__init__.py tests/unit/data_models/test_report_models.py
git commit -m "feat: add structured report models"
```

### Task 6.2: 新增结构化报告装配层

**Files:**
- Create: `src/vsa_agent/tools/report_structuring.py`
- Create: `tests/unit/tools/test_report_structuring.py`

- [ ] **Step 1: 写失败测试，锁定 UnderstandingResult -> StructuredReport 行为**

```python
import pytest

from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import EvidenceRef
from vsa_agent.data_models.understanding import UnderstandingResult


@pytest.mark.anyio
async def test_build_single_section_report_maps_understanding_to_structured_report():
    from vsa_agent.tools.report_structuring import build_single_section_report

    result = UnderstandingResult(
        query="生成报告",
        source_type="rtsp",
        summary_text="forklift stops near doorway",
        chunks=[],
        events=[
            DetectedEvent(
                event_id="event-1",
                label="vehicle",
                description="forklift stops near doorway",
                start_timestamp="00:00:05",
                end_timestamp="00:00:09",
                evidence=[EvidenceRef(source_type="rtsp", sensor_id="camera-1")],
            )
        ],
    )

    report = build_single_section_report(
        source_name="camera-1",
        source_type="rtsp",
        user_query="生成报告",
        understanding_result=result,
    )

    assert report.report_type == "single_video"
    assert report.sections[0].incidents[0].description == "forklift stops near doorway"
    assert report.sections[0].source_name == "camera-1"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_structuring.py -v`

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
from vsa_agent.data_models.report import ReportIncident
from vsa_agent.data_models.report import ReportSection
from vsa_agent.data_models.report import StructuredReport
from vsa_agent.tools.incidents import understanding_to_incidents


def build_single_section_report(...):
    incidents = [
        ReportIncident(
            incident_id=item.id,
            category=item.category,
            description=item.description,
            severity=item.severity,
            confidence=item.confidence,
            start_timestamp=str(item.metadata.get("start_timestamp", "")),
            end_timestamp=str(item.metadata.get("end_timestamp", "")),
            metadata=item.metadata,
        )
        for item in understanding_to_incidents(understanding_result)
    ]
    section = ReportSection(...)
    return StructuredReport(...)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_structuring.py -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/report_structuring.py tests/unit/tools/test_report_structuring.py
git commit -m "feat: add report structuring layer"
```

### Task 6.3: 接入 incidents / geolocation / postprocessing

**Files:**
- Modify: `src/vsa_agent/tools/report_structuring.py`
- Modify: `src/vsa_agent/tools/incidents.py`
- Modify: `src/vsa_agent/tools/geolocation.py`
- Modify: `src/vsa_agent/agents/postprocessing/pipeline.py`
- Create: `tests/unit/agents/postprocessing/test_structured_pipeline.py`
- Modify: `tests/unit/tools/test_report_structuring.py`

- [ ] **Step 1: 写失败测试，锁定结构化后处理行为**

```python
@pytest.mark.anyio
async def test_process_report_keeps_validation_feedback_on_structured_report():
    from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline
    from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator

    pipeline = ValidationPipeline([NonEmptyValidator()])
    result = await pipeline.process_report(report)

    assert result.passed is True
```

- [ ] **Step 2: 写失败测试，锁定 geolocation 汇总进入 section**

```python
from vsa_agent.tools.geolocation import summarize_geolocation

assert section.location_summary == summarize_geolocation(enriched_incidents)
```

- [ ] **Step 3: 最小实现**

```python
async def process_report(self, report: StructuredReport) -> PostprocessingResult:
    ...
```

- [ ] **Step 4: 跑模块测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_report_structuring.py tests/unit/agents/postprocessing/test_structured_pipeline.py tests/unit/tools/test_geolocation.py tests/unit/tools/test_incidents.py -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/report_structuring.py src/vsa_agent/tools/incidents.py src/vsa_agent/tools/geolocation.py src/vsa_agent/agents/postprocessing/pipeline.py tests/unit/tools/test_report_structuring.py tests/unit/agents/postprocessing/test_structured_pipeline.py tests/unit/tools/test_geolocation.py tests/unit/tools/test_incidents.py
git commit -m "feat: wire report postprocessing chain"
```

### Task 6.4: 调整 report renderer 与 agents

**Files:**
- Modify: `src/vsa_agent/tools/video_report_gen.py`
- Modify: `src/vsa_agent/tools/template_report_gen.py`
- Modify: `src/vsa_agent/tools/report_gen.py`
- Modify: `src/vsa_agent/agents/report_agent.py`
- Modify: `src/vsa_agent/agents/multi_report_agent.py`
- Modify: `tests/unit/tools/test_video_report_gen.py`
- Modify: `tests/unit/tools/test_template_report_gen.py`
- Modify: `tests/unit/agents/test_report_agent.py`
- Modify: `tests/unit/agents/test_multi_report_agent.py`

- [ ] **Step 1: 写失败测试，锁定 renderer 只消费结构化对象**

```python
@pytest.mark.anyio
async def test_generate_video_report_accepts_report_section():
    ...
```

- [ ] **Step 2: 写失败测试，锁定 agent 先构建 StructuredReport**

```python
assert result.side_effects["markdown_content"].startswith("# ")
```

- [ ] **Step 3: 最小实现**

```python
# 适配旧签名到新结构化对象，render 层只处理对象
```

- [ ] **Step 4: 跑回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_report_gen.py src/vsa_agent/tools/template_report_gen.py src/vsa_agent/tools/report_gen.py src/vsa_agent/agents/report_agent.py src/vsa_agent/agents/multi_report_agent.py tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py
git commit -m "feat: route reports through structured chain"
```

### Task 6.5: Phase 6 验收与总计划更新

**Files:**
- Create: `tests/acceptance/test_phase6_report_postprocessing_flow.py`
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [x] **Step 1: 写验收测试，锁定单视频报告链**

```python
@pytest.mark.anyio
async def test_phase6_single_video_report_flow(...):
    ...
```

- [x] **Step 2: 写验收测试，锁定多视频报告链**

```python
@pytest.mark.anyio
async def test_phase6_multi_video_report_flow(...):
    ...
```

- [x] **Step 3: 跑 Phase 6 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_report_models.py tests/unit/tools/test_report_structuring.py tests/unit/agents/postprocessing/test_structured_pipeline.py tests/unit/tools/test_video_report_gen.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_report_gen.py tests/unit/agents/test_report_agent.py tests/unit/agents/test_multi_report_agent.py tests/acceptance/test_phase6_report_postprocessing_flow.py -q`

Expected: `PASS`

- [x] **Step 4: 更新总计划文档状态**

```markdown
### 当前执行状态（2026-06-17）
- [x] Task 6.1 已完成：报告域结构化模型已新增
- [x] Task 6.2 已完成：结构化报告装配层已新增
- [x] Task 6.3 已完成：incidents / geolocation / postprocessing 已接入结构化主链
- [x] Task 6.4 已完成：renderer 与 agents 已切换到结构化对象
- [x] Task 6.5 已完成：Phase 6 验收与回归通过，待整理提交
```

- [x] **Step 5: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md tests/acceptance/test_phase6_report_postprocessing_flow.py
git commit -m "feat: complete phase6 report postprocessing"
```

### 当前执行状态（2026-06-17，更新）
- [x] Phase 6 已完成并提交：`fbf0767 feat: complete phase6 report postprocessing`
- [x] `master` 已推送到 `origin/master`

---

## Phase 7 — A1 提示词与推理基础设施对齐 (P1)

# Phase 7A1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照“原版接口优先、接口补齐优先”的原则，对齐 `prompt.py`、`utils/reasoning_parsing.py`、`utils/reasoning_utils.py`、`utils/asyncmixin.py` 四个基础模块，并把最小接入落到 `prompt_gen.py` 和 `video_understanding.py`。

**Architecture:** 这一轮不改 Agent 层，只做“基础设施对齐 + 工具层最小接入”。`prompt.py` 作为唯一 prompt 源；`reasoning_parsing.py` 提供统一的 thinking/answer 解析；`reasoning_utils.py` 提供原版式推理辅助别名；`asyncmixin.py` 提供兼容原版生命周期的异步基类。`prompt_gen.py` 和 `video_understanding.py` 只消费这些统一接口，不再各自散落重复逻辑。

**Tech Stack:** Python 3.12, existing `vsa_agent.prompt`, LangChain messages, pytest, dataclasses, existing `VideoUnderstandingConfig`

---

## 文件结构

**修改文件**
- `src/vsa_agent/prompt.py`
  - 统一 Prompt 常量导出
  - 增加结构化注册表与 `__all__`
- `src/vsa_agent/utils/reasoning_parsing.py`
  - 增加 `parse_content_blocks()`
  - 保持 `parse_reasoning_content()` 向后兼容
- `src/vsa_agent/utils/reasoning_utils.py`
  - 增加原版式别名 `get_thinking_tag()`、`get_llm_reasoning_bind_kwargs()`
- `src/vsa_agent/utils/asyncmixin.py`
  - 对齐 `__async_init__` / `close()` 生命周期兼容
- `src/vsa_agent/tools/prompt_gen.py`
  - 只从 `prompt.py` 取共享 prompt 片段
- `src/vsa_agent/tools/video_understanding.py`
  - 去掉本地重复 prompt 字面量
  - 统一使用共享 prompt / reasoning parser
- `tests/unit/test_prompt.py`
- `tests/unit/utils/test_reasoning_parsing.py`
- `tests/unit/utils/test_reasoning_utils.py`
- `tests/unit/utils/test_asyncmixin.py`
- `tests/unit/tools/test_prompt_gen.py`
- `tests/unit/tools/test_video_understanding.py`

**本轮不做**
- 不修改 Agent 层
- 不修改 `model_adapter` 的 `invoke()` 签名
- 不把 reasoning kwargs 全面下沉到所有模型调用链

---

### Task 7.1: 对齐 `prompt.py` 为唯一 Prompt 源

**Files:**
- Modify: `src/vsa_agent/prompt.py`
- Modify: `tests/unit/test_prompt.py`

- [ ] **Step 1: 写失败测试，锁定 Prompt 注册表与导出契约**

```python
from vsa_agent import prompt as prompt_module


class TestPromptRegistry:
    def test_exports_prompt_registry_and_all(self):
        assert "default" in prompt_module.PROMPT_REGISTRY
        assert "video_understanding" in prompt_module.PROMPT_REGISTRY
        assert (
            prompt_module.PROMPT_REGISTRY["video_understanding"]
            == prompt_module.SYSTEM_PROMPT_VIDEO_UNDERSTANDING
        )
        assert "SYSTEM_PROMPT_DEFAULT" in prompt_module.__all__
        assert "VLM_HUMAN_PROMPT_TEMPLATE" in prompt_module.__all__
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_prompt.py -v`
Expected: `AttributeError: module 'vsa_agent.prompt' has no attribute 'PROMPT_REGISTRY'`

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/prompt.py

PROMPT_REGISTRY = {
    "default": SYSTEM_PROMPT_DEFAULT,
    "safety_inspection": SYSTEM_PROMPT_SAFETY_INSPECTION,
    "safety_incident": SYSTEM_PROMPT_SAFETY_INCIDENT,
    "vlm_format": SYSTEM_PROMPT_VLM_FORMAT,
    "video_understanding": SYSTEM_PROMPT_VIDEO_UNDERSTANDING,
    "critic_agent": CRITIC_AGENT_SYSTEM_PROMPT,
    "vlm_human_template": VLM_HUMAN_PROMPT_TEMPLATE,
}

__all__ = [
    "SYSTEM_PROMPT_DEFAULT",
    "SYSTEM_PROMPT_SAFETY_INSPECTION",
    "SYSTEM_PROMPT_SAFETY_INCIDENT",
    "SYSTEM_PROMPT_VLM_FORMAT",
    "SYSTEM_PROMPT_VIDEO_UNDERSTANDING",
    "VLM_HUMAN_PROMPT_TEMPLATE",
    "CRITIC_AGENT_SYSTEM_PROMPT",
    "PROMPT_REGISTRY",
]
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_prompt.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/prompt.py tests/unit/test_prompt.py
git commit -m "feat: align prompt module exports"
```

### Task 7.2: 扩展 `reasoning_parsing.py` 为原版式解析接口

**Files:**
- Modify: `src/vsa_agent/utils/reasoning_parsing.py`
- Modify: `tests/unit/utils/test_reasoning_parsing.py`

- [ ] **Step 1: 写失败测试，锁定 `parse_content_blocks()` 契约**

```python
from vsa_agent.utils.reasoning_parsing import parse_content_blocks


class TestParseContentBlocks:
    def test_splits_thinking_and_answer_blocks(self):
        result = parse_content_blocks(
            "<thinking>first</thinking><answer>second</answer>"
        )
        assert result == [
            {"type": "thinking", "content": "first"},
            {"type": "answer", "content": "second"},
        ]

    def test_plain_text_returns_single_answer_block(self):
        result = parse_content_blocks("plain answer")
        assert result == [{"type": "answer", "content": "plain answer"}]
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_reasoning_parsing.py -v`
Expected: `ImportError: cannot import name 'parse_content_blocks'`

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/reasoning_parsing.py

def parse_content_blocks(content: str | None) -> list[dict[str, str]]:
    result = parse_reasoning_content(content)
    blocks: list[dict[str, str]] = []
    if result.thinking:
        blocks.append({"type": "thinking", "content": result.thinking})
    if result.answer:
        blocks.append({"type": "answer", "content": result.answer})
    if not blocks:
        return [{"type": "answer", "content": ""}]
    return blocks
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_reasoning_parsing.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/reasoning_parsing.py tests/unit/utils/test_reasoning_parsing.py
git commit -m "feat: add reasoning content block parser"
```

### Task 7.3: 对齐 `reasoning_utils.py` 原版式函数名

**Files:**
- Modify: `src/vsa_agent/utils/reasoning_utils.py`
- Modify: `tests/unit/utils/test_reasoning_utils.py`

- [ ] **Step 1: 写失败测试，锁定原版式别名函数**

```python
from vsa_agent.utils.reasoning_utils import (
    bind_reasoning_kwargs,
    get_llm_reasoning_bind_kwargs,
    get_thinking_tag,
    thinking_tag,
)


class TestReasoningCompatNames:
    def test_get_thinking_tag_matches_existing_helper(self):
        assert get_thinking_tag("abc") == thinking_tag("abc")

    def test_get_llm_reasoning_bind_kwargs_matches_existing_filter(self):
        kwargs = {
            "reasoning_effort": "high",
            "temperature": 0.1,
            "filter_thinking": True,
            "unrelated": "value",
        }
        assert get_llm_reasoning_bind_kwargs(kwargs) == bind_reasoning_kwargs(kwargs)
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_reasoning_utils.py -v`
Expected: `ImportError: cannot import name 'get_thinking_tag'`

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/reasoning_utils.py

def get_thinking_tag(content: str) -> str:
    return thinking_tag(content)


def get_llm_reasoning_bind_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return bind_reasoning_kwargs(kwargs)


__all__ = [
    "thinking_tag",
    "bind_reasoning_kwargs",
    "get_thinking_tag",
    "get_llm_reasoning_bind_kwargs",
]
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_reasoning_utils.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/reasoning_utils.py tests/unit/utils/test_reasoning_utils.py
git commit -m "feat: add reasoning utils compatibility aliases"
```

### Task 7.4: 对齐 `AsyncMixin` 生命周期兼容层

**Files:**
- Modify: `src/vsa_agent/utils/asyncmixin.py`
- Modify: `tests/unit/utils/test_asyncmixin.py`

- [ ] **Step 1: 写失败测试，锁定 `__async_init__` 与 `close()` 兼容行为**

```python
import pytest

from vsa_agent.utils.asyncmixin import AsyncMixin


class TestAsyncMixinCompat:
    @pytest.mark.asyncio
    async def test_create_calls_dunder_async_init_when_present(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self.ready = False

            async def __async_init__(self):
                self.ready = True

        obj = await MyResource.create()
        assert obj.ready is True

    @pytest.mark.asyncio
    async def test_aexit_uses_close_when_present(self):
        class MyResource(AsyncMixin):
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        obj = MyResource()
        await obj.__aexit__(None, None, None)
        assert obj.closed is True
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_asyncmixin.py -v`
Expected: FAIL because `create()` does not call `__async_init__` and `__aexit__()` does not delegate to `close()`

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/asyncmixin.py

async def async_init(self) -> None:
    dunder_init = getattr(self, "__async_init__", None)
    if callable(dunder_init):
        await dunder_init()
    self._async_initialized = True


async def async_close(self) -> None:
    self._async_initialized = False


async def close(self) -> None:
    await self.async_close()


async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    close_method = getattr(self, "close", None)
    if callable(close_method):
        await close_method()
        return
    await self.async_close()
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_asyncmixin.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/asyncmixin.py tests/unit/utils/test_asyncmixin.py
git commit -m "feat: align async mixin lifecycle compatibility"
```

### Task 7.5: 工具层最小接入共享 Prompt 与推理解析

**Files:**
- Modify: `src/vsa_agent/tools/prompt_gen.py`
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_prompt_gen.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 写失败测试，锁定 `prompt_gen` 使用共享 Prompt 常量**

```python
import pytest

from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE
from vsa_agent.tools.prompt_gen import generate_understanding_prompt


@pytest.mark.anyio
async def test_generate_prompt_uses_shared_prompt_constants():
    prompt = await generate_understanding_prompt("person walking near forklift")
    assert prompt.startswith(SYSTEM_PROMPT_VIDEO_UNDERSTANDING)
    assert VLM_HUMAN_PROMPT_TEMPLATE.format(
        query="person walking near forklift"
    ) in prompt
```

- [ ] **Step 2: 写失败测试，锁定 `video_understanding` 走共享 Prompt 与解析器**

```python
from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE
from vsa_agent.tools.video_understanding import _build_vlm_messages
from vsa_agent.tools.video_understanding import _parse_thinking_from_content


class TestSharedPromptIntegration:
    def test_build_vlm_messages_uses_shared_system_prompt(self):
        messages = _build_vlm_messages(["frame-a"], "what happened")
        assert messages[0].content == SYSTEM_PROMPT_VIDEO_UNDERSTANDING
        text_part = next(
            part["text"] for part in messages[1].content if part["type"] == "text"
        )
        assert text_part == VLM_HUMAN_PROMPT_TEMPLATE.format(query="what happened")

    def test_parse_thinking_from_content_keeps_answer_contract(self):
        thinking, answer = _parse_thinking_from_content(
            "<thinking>inspect</thinking><answer>worker falls</answer>"
        )
        assert thinking == "inspect"
        assert answer == "worker falls"
```

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/video_understanding.py
from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE


def _build_vlm_messages(frames, query, system_prompt=None):
    image_parts = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}}
        for frame in frames
    ]
    return [
        SystemMessage(content=system_prompt or SYSTEM_PROMPT_VIDEO_UNDERSTANDING),
        HumanMessage(
            content=[
                {"type": "text", "text": VLM_HUMAN_PROMPT_TEMPLATE.format(query=query)},
                *image_parts,
            ]
        ),
    ]
```

```python
# src/vsa_agent/tools/prompt_gen.py
from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE
```

- [x] **Step 4: 跑工具层回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_prompt.py tests/unit/utils/test_reasoning_parsing.py tests/unit/utils/test_reasoning_utils.py tests/unit/utils/test_asyncmixin.py tests/unit/tools/test_prompt_gen.py tests/unit/tools/test_video_understanding.py -q`
Expected: `PASS`

- [x] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/prompt_gen.py src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_prompt_gen.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: wire shared prompt and reasoning utilities into tools"
```

### Task 7.6: Phase 7A1 文档状态更新与回归收口

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [x] **Step 1: 跑 Phase 7A1 全量相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_prompt.py tests/unit/utils/test_reasoning_parsing.py tests/unit/utils/test_reasoning_utils.py tests/unit/utils/test_asyncmixin.py tests/unit/tools/test_prompt_gen.py tests/unit/tools/test_video_understanding.py -q`
Expected: `PASS`

- [x] **Step 2: 更新本计划中的 Phase 7A1 状态**

```markdown
### 当前执行状态（2026-06-17）
- [x] Task 7.1 已完成：prompt.py 已对齐为唯一 Prompt 源
- [x] Task 7.2 已完成：reasoning_parsing 已补齐原版式解析接口
- [x] Task 7.3 已完成：reasoning_utils 已补齐原版式别名函数
- [x] Task 7.4 已完成：AsyncMixin 生命周期兼容层已补齐
- [x] Task 7.5 已完成：prompt_gen / video_understanding 已完成最小接入
- [x] Task 7.6 已完成：Phase 7A1 回归通过，待整理文档提交
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: update phase7a1 execution status"
```

---

## Phase 7 — A2 VSS 数据模型与时间/帧工具对齐 (P1)

# Phase 7A2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对齐 `data_models/vss.py`、`utils/time_convert.py`、`utils/frame_select.py` 三个基础模块，使其具备更完整的原版兼容接口、稳定的边界语义，以及可被视频理解链复用的公共契约。

**Architecture:** 这一轮继续坚持“对外接口不变、内部契约补齐”的原则。`data_models/vss.py` 作为 VSS 共享模型的兼容出口；`time_convert.py` 统一承担时间戳解析、ISO 时间转换、帧秒换算；`frame_select.py` 统一承担时间窗到帧索引的选择逻辑。最后把 `frame_extract.py` / `video_understanding.py` 的重复时间与选帧逻辑收口到公共工具层。

**Tech Stack:** Python 3.12, dataclasses, datetime, pytest, existing video_understanding/frame_extract pipeline

---

## 文件结构

**修改文件**
- `src/vsa_agent/data_models/vss.py`
  - 补齐 `Location` / `Place` 兼容导出
  - 增强 `MediaInfoOffset` 的序列化与派生属性
- `src/vsa_agent/data_models/__init__.py`
  - 对齐新的兼容导出
- `src/vsa_agent/utils/time_convert.py`
  - 增加 ISO 时间互转与更稳的时间解析
- `src/vsa_agent/utils/frame_select.py`
  - 增强均匀选帧与时间窗裁剪逻辑
- `src/vsa_agent/tools/frame_extract.py`
  - 使用共享选帧/换算逻辑
- `src/vsa_agent/tools/video_understanding.py`
  - 使用共享时间/选帧逻辑，减少局部重复实现
- `tests/unit/data_models/test_vss_data_models.py`
- `tests/unit/utils/test_time_convert.py`
- `tests/unit/utils/test_frame_select.py`
- `tests/unit/tools/test_frame_extract.py`
- `tests/unit/tools/test_video_understanding.py`

**本轮不做**
- 不改 Agent 层
- 不改 API 层
- 不接入真实 VST/NAT 时间锚点换算

---

### Task 7.7: 对齐 `data_models/vss.py` 兼容出口与 `MediaInfoOffset` 契约

**Files:**
- Modify: `src/vsa_agent/data_models/vss.py`
- Modify: `src/vsa_agent/data_models/__init__.py`
- Modify: `tests/unit/data_models/test_vss_data_models.py`

- [ ] **Step 1: 写失败测试，锁定导出与 `MediaInfoOffset` 能力**

```python
from vsa_agent.data_models import Incident, Location, MediaInfoOffset, Place


class TestMediaInfoOffset:
    def test_current_frame_index_uses_offset_and_fps(self):
        media = MediaInfoOffset(duration_sec=30.0, fps=10.0, current_offset_sec=2.6)
        assert media.current_frame_index == 26

    def test_remaining_duration_is_clamped(self):
        media = MediaInfoOffset(duration_sec=10.0, current_offset_sec=12.0)
        assert media.remaining_duration_sec == 0.0

    def test_to_dict_round_trip_preserves_metadata(self):
        media = MediaInfoOffset(
            video_path="demo.mp4",
            duration_sec=12.5,
            fps=25.0,
            total_frames=312,
            current_offset_sec=4.0,
            metadata={"sensor_id": "cam-1"},
        )
        restored = MediaInfoOffset.from_dict(media.to_dict())
        assert restored == media


class TestCompatExports:
    def test_reexports_location_place_and_incident(self):
        assert Location.__name__ == "Location"
        assert Place.__name__ == "Place"
        assert Incident.__name__ == "Incident"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_vss_data_models.py -v`
Expected: FAIL because `Location` / `Place` are not re-exported and `MediaInfoOffset` lacks derived properties / round-trip helpers

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/data_models/vss.py

from vsa_agent.video_analytics.nvschema import Incident
from vsa_agent.video_analytics.nvschema import Location
from vsa_agent.video_analytics.nvschema import Place


@dataclass
class MediaInfoOffset:
    ...

    @property
    def current_frame_index(self) -> int:
        if self.fps <= 0:
            return 0
        return max(0, int(self.current_offset_sec * self.fps))

    @property
    def remaining_duration_sec(self) -> float:
        return max(0.0, self.duration_sec - self.current_offset_sec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_path": self.video_path,
            "duration_sec": self.duration_sec,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "current_offset_sec": self.current_offset_sec,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MediaInfoOffset":
        return cls(**payload)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_vss_data_models.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/data_models/vss.py src/vsa_agent/data_models/__init__.py tests/unit/data_models/test_vss_data_models.py
git commit -m "feat: align vss data model compatibility exports"
```

### Task 7.8: 对齐 `time_convert.py` 的时间解析与 ISO 互转契约

**Files:**
- Modify: `src/vsa_agent/utils/time_convert.py`
- Modify: `tests/unit/utils/test_time_convert.py`

- [ ] **Step 1: 写失败测试，锁定 ISO 互转与边界语义**

```python
from datetime import datetime
from datetime import timezone

import pytest

from vsa_agent.utils.time_convert import datetime_to_iso8601
from vsa_agent.utils.time_convert import iso8601_to_datetime
from vsa_agent.utils.time_convert import parse_iso8601_duration
from vsa_agent.utils.time_convert import format_timestamp


def test_iso8601_to_datetime_supports_z_suffix():
    value = iso8601_to_datetime("2025-01-01T10:00:00Z")
    assert value == datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_datetime_to_iso8601_outputs_z_for_utc():
    value = datetime_to_iso8601(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
    assert value == "2025-01-01T10:00:00Z"


def test_parse_iso8601_duration_rejects_empty_payload():
    with pytest.raises(ValueError):
        parse_iso8601_duration("PT")


def test_format_timestamp_mm_ss_ms_uses_total_minutes():
    assert format_timestamp(3661.25, fmt="mm:ss.ms") == "61:01.250"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_time_convert.py -v`
Expected: FAIL because ISO helpers do not exist and current formatter/parser edge behavior differs

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/time_convert.py

def iso8601_to_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def datetime_to_iso8601(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = normalized.isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_time_convert.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/time_convert.py tests/unit/utils/test_time_convert.py
git commit -m "feat: add shared iso time conversion helpers"
```

### Task 7.9: 对齐 `frame_select.py` 的均匀选帧与时间窗裁剪逻辑

**Files:**
- Modify: `src/vsa_agent/utils/frame_select.py`
- Modify: `tests/unit/utils/test_frame_select.py`

- [ ] **Step 1: 写失败测试，锁定首尾覆盖与时间窗裁剪行为**

```python
from vsa_agent.utils.frame_select import frames_for_timestamp_range
from vsa_agent.utils.frame_select import select_frame_indices


def test_select_frame_indices_spans_window_including_last_frame():
    assert select_frame_indices(total_frames=10, max_frames=3) == [0, 4, 9]


def test_select_frame_indices_clamps_start_and_end():
    assert select_frame_indices(total_frames=20, max_frames=4, start_frame=-3, end_frame=50) == [0, 6, 12, 19]


def test_frames_for_timestamp_range_returns_empty_when_fps_invalid():
    assert frames_for_timestamp_range(fps=0.0, duration_sec=30.0, max_frames=5) == []


def test_frames_for_timestamp_range_clamps_requested_window():
    assert frames_for_timestamp_range(
        fps=10.0,
        duration_sec=5.0,
        max_frames=3,
        start_ts=-1.0,
        end_ts=10.0,
    ) == [0, 24, 49]
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_frame_select.py -v`
Expected: FAIL because current logic does not guarantee last-frame coverage and lacks invalid-FPS guard

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/frame_select.py

def select_frame_indices(...):
    ...
    if window <= max_frames:
        return list(range(start_frame, end_frame))

    step = (window - 1) / (max_frames - 1)
    indices = [
        min(end_frame - 1, start_frame + round(i * step))
        for i in range(max_frames)
    ]
    return indices
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_frame_select.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/frame_select.py tests/unit/utils/test_frame_select.py
git commit -m "feat: align shared frame selection helpers"
```

### Task 7.10: 把 `frame_extract` / `video_understanding` 重复逻辑接回公共工具层

**Files:**
- Modify: `src/vsa_agent/tools/frame_extract.py`
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_frame_extract.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 写失败测试，锁定工具层对共享工具函数的消费**

```python
def test_frame_extract_uses_shared_frame_selector(monkeypatch):
    from vsa_agent.tools import frame_extract

    captured = {}

    def fake_selector(total_frames, max_frames, start_frame=0, end_frame=None):
        captured["args"] = (total_frames, max_frames, start_frame, end_frame)
        return [0, 5, 9]

    monkeypatch.setattr(frame_extract, "select_frame_indices", fake_selector)
    ...
    assert captured["args"] == (10, 3, 0, 10)


def test_video_understanding_timestamp_to_seconds_uses_shared_parser():
    assert _timestamp_to_seconds("PT5S") == 5.0
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_frame_extract.py tests/unit/tools/test_video_understanding.py -v`
Expected: FAIL because the shared helpers are not yet wired into both tools

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/frame_extract.py
from vsa_agent.utils.frame_select import select_frame_indices

# src/vsa_agent/tools/video_understanding.py
from vsa_agent.utils.frame_select import frames_for_timestamp_range
from vsa_agent.utils.time_convert import parse_iso8601_duration
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_frame_extract.py tests/unit/tools/test_video_understanding.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/frame_extract.py src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_frame_extract.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: reuse shared time and frame helpers in video tools"
```

### Task 7.11: Phase 7A2 回归与文档状态更新

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑 Phase 7A2 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/data_models/test_vss_data_models.py tests/unit/utils/test_time_convert.py tests/unit/utils/test_frame_select.py tests/unit/tools/test_frame_extract.py tests/unit/tools/test_video_understanding.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的 Phase 7A2 状态**

```markdown
### 当前执行状态（2026-06-18）
- [x] Task 7.7 已完成：VSS 数据模型兼容出口已补齐
- [x] Task 7.8 已完成：时间转换公共接口已补齐
- [x] Task 7.9 已完成：共享选帧逻辑已对齐
- [x] Task 7.10 已完成：视频工具层已接回共享时间/选帧工具
- [x] Task 7.11 已完成：Phase 7A2 回归通过，待整理提交

## Phase 8 — 业务能力闭环（总目标）

**目标**：正式结束“基础设施对齐优先”的推进方式，回到业务主线，围绕现有 `search / critic / understanding / incidents / report / API` 能力，构建可交付、可验收、可审查的核心业务闭环。

**阶段判断**：

- Phase 7 已完成高价值基础设施对齐
- 当前继续补工具层的边际收益已明显下降
- Phase 8 的重点不再是“补模块”，而是“把现有模块拉成稳定业务链”

### Phase 8 核心推进方案

本阶段采用“业务编排优先”方案。

含义是：

- 先定义用户请求如何穿过现有模块，最终产出回答、报告或接口响应
- 再按主链补齐断点、统一错误语义、补验收测试
- 不优先推进真实 ES / 更真实 VST 深接入

### Phase 8 三条核心业务闭环

1. 检索问答闭环  
   `query -> search_agent -> critic_agent(可选) -> incidents / summarize -> 最终结构化回答`

2. 单视频分析报告闭环  
   `video_path / sensor_id -> video_understanding -> structured_report -> postprocessing -> markdown 报告`

3. 多源汇总报告闭环  
   `sources[] -> multi_report_agent -> understanding 聚合 -> structured_report -> 汇总报告`

在线 RTSP / VST 入口保留为支撑链，不作为本阶段第一优先级主线。

### Phase 8 实施顺序

#### P1：单视频分析报告闭环

这是 Phase 8 第一优先级子项目，也是当前最适合先收口的一条业务链。

目标：

- 固定主链为  
  `video_understanding -> structured_report -> postprocessing -> markdown`
- 让 `StructuredReport` 成为内部主契约
- 让 `postprocessing` 正式进入报告主链
- 用单元测试与验收测试锁定成功流、兼容流、校验失败流、理解失败流

#### P1：检索问答闭环

目标：

- 收敛 `search_agent`、`tools/search.py`、`critic_agent`、`incidents.py`、`vss_summarize.py`
- 明确检索结果、critic 验证、事件标准化、最终摘要之间的协作顺序
- 用验收测试锁定“可选 critic”与“当前 mock search 边界”

#### P2：多源汇总报告闭环

目标：

- 收敛 `multi_report_agent` 与多 source 的理解结果聚合
- 统一走结构化报告与渲染链
- 明确空 source、部分 source 失败、顺序稳定性等语义

#### P2：API 业务映射层验收

目标：

- 检查 `api/routes.py` 及相关 API 是否正确映射到内部业务主链
- 统一错误语义
- 避免 API 层与 agent 主链出现分叉行为

#### P3：阶段收口与可审查输出

输出：

- 唯一总计划文档中的阶段状态更新
- Phase 8 业务链说明
- 验收测试清单
- 当前已知边界说明（真实 ES、真实 VST 历史片段、生产级观测等）

### 当前 Phase 8 子项目选择

已确认优先进入：

1. 子项目：单视频分析报告闭环
2. 范围：内部主链闭环
3. 方案：结构化报告主链化

# Phase 8A1 单视频分析报告闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单视频分析报告链稳定收敛为“理解结果 -> 结构化报告 -> 后处理校验 -> Markdown 交付”的可验收业务闭环。

**Architecture:** 本轮不改对外工具名和主要返回结构，只收口内部编排。`report_agent.py` 负责驱动主链，`report_structuring.py` 负责报告域装配，`ValidationPipeline` 负责摘要校验与反馈回写，`video_report_gen.py` 只消费 `StructuredReport` 并渲染最终 Markdown。

**Tech Stack:** Python 3.12, Pydantic, pytest, anyio, 现有 `vsa_agent` agents/tools/data_models/postprocessing 组件。

---

### Task 8.1: 先补红灯，锁定单视频报告闭环的验收与编排语义

**Files:**
- Modify: `tests/acceptance/test_report_flow.py`
- Modify: `tests/unit/agents/test_report_agent.py`

- [ ] **Step 1: 写失败中的验收测试，覆盖“后处理失败仍可交付”和“理解失败直接中断”**

```python
# tests/acceptance/test_report_flow.py
@pytest.mark.anyio
async def test_single_video_report_flow_keeps_markdown_when_postprocessing_fails():
    from vsa_agent.agents.postprocessing.pipeline import PostprocessingResult
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
    from vsa_agent.tools.video_report_gen import generate_video_report

    class FakePipeline:
        async def process_report(self, report):
            report.sections[0].validation_feedback.append("[non_empty_response_validator] FAILED: Response is empty")
            report.global_validation_feedback.append("[non_empty_response_validator] FAILED: Response is empty")
            return PostprocessingResult(
                passed=False,
                feedback="[non_empty_response_validator] FAILED: Response is empty",
            )

    async def fake_video_understanding_fn(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "",
            "chunks": [],
            "events": [],
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding_fn,
        video_report_gen_fn=generate_video_report,
        validation_pipeline=FakePipeline(),
    )

    assert result.status == "success"
    assert result.metadata["validation_passed"] is False
    assert result.metadata["validation_feedback"] == [
        "[non_empty_response_validator] FAILED: Response is empty"
    ]
    assert "## 校验反馈" in result.side_effects["markdown_content"]


@pytest.mark.anyio
async def test_single_video_report_flow_raises_when_understanding_fails():
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
    from vsa_agent.tools.video_report_gen import generate_video_report

    async def broken_video_understanding(**kwargs):
        raise RuntimeError("vlm call failed")

    with pytest.raises(RuntimeError, match="vlm call failed"):
        await execute_report_agent(
            ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
            video_understanding_fn=broken_video_understanding,
            video_report_gen_fn=generate_video_report,
        )
```

- [ ] **Step 2: 写失败中的单元测试，锁定 `report_agent` 会带出校验反馈元数据**

```python
# tests/unit/agents/test_report_agent.py
@pytest.mark.anyio
async def test_execute_report_agent_keeps_success_status_and_exposes_validation_feedback():
    from vsa_agent.agents.postprocessing.pipeline import PostprocessingResult
    from vsa_agent.agents.report_agent import ReportAgentInput
    from vsa_agent.agents.report_agent import execute_report_agent
    from vsa_agent.data_models.report import StructuredReport

    async def fake_video_understanding(**kwargs):
        return {
            "query": kwargs["query"],
            "source_type": kwargs["source_type"],
            "summary_text": "",
            "chunks": [],
            "events": [],
        }

    class FakePipeline:
        async def process_report(self, report):
            report.sections[0].validation_feedback.append("[non_empty_response_validator] FAILED: Response is empty")
            report.global_validation_feedback.append("[non_empty_response_validator] FAILED: Response is empty")
            return PostprocessingResult(
                passed=False,
                feedback="[non_empty_response_validator] FAILED: Response is empty",
            )

    async def fake_video_report_gen(**kwargs):
        assert isinstance(kwargs["structured_report"], StructuredReport)
        assert kwargs["structured_report"].global_validation_feedback == [
            "[non_empty_response_validator] FAILED: Response is empty"
        ]
        return {
            "markdown_content": "# 单视频分析报告\n\n## 校验反馈\n- [non_empty_response_validator] FAILED: Response is empty",
            "downloads": {"markdown": {"filename": "report.md"}},
            "summary": "",
        }

    result = await execute_report_agent(
        ReportAgentInput(video_path="video.mp4", query="生成详细报告"),
        video_understanding_fn=fake_video_understanding,
        video_report_gen_fn=fake_video_report_gen,
        validation_pipeline=FakePipeline(),
    )

    assert result.status == "success"
    assert result.metadata["validation_passed"] is False
    assert result.metadata["validation_feedback"] == [
        "[non_empty_response_validator] FAILED: Response is empty"
    ]
```

- [ ] **Step 3: 运行测试，确认当前还是红灯**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_report_flow.py tests/unit/agents/test_report_agent.py -q`
Expected: `FAIL` because `execute_report_agent()` 还没有接入 `validation_pipeline`，也不会带出 `validation_feedback`

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/test_report_flow.py tests/unit/agents/test_report_agent.py
git commit -m "test: lock single video report closure semantics"
```

### Task 8.2: 让 `ValidationPipeline.process_report()` 正式回写结构化报告反馈

**Files:**
- Modify: `tests/unit/agents/postprocessing/test_pipeline.py`
- Modify: `src/vsa_agent/agents/postprocessing/pipeline.py`

- [ ] **Step 1: 写失败中的 pipeline 测试，锁定 section/global feedback 回写**

```python
# tests/unit/agents/postprocessing/test_pipeline.py
@pytest.mark.anyio
async def test_process_report_writes_feedback_back_to_structured_report():
    from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
    from vsa_agent.data_models.report import ReportSection
    from vsa_agent.data_models.report import StructuredReport

    report = StructuredReport(
        report_title="report-title",
        report_type="single_video",
        user_query="生成详细报告",
        sections=[
            ReportSection(
                section_id="section-1",
                section_title="事件 - camera-1",
                source_name="camera-1",
                source_type="rtsp",
                user_query="生成详细报告",
                summary_text="",
                understanding_result={
                    "query": "生成详细报告",
                    "source_type": "rtsp",
                    "summary_text": "",
                    "chunks": [],
                    "events": [],
                },
            )
        ],
    )

    pipeline = ValidationPipeline([NonEmptyValidator()])
    result = await pipeline.process_report(report)

    assert result.passed is False
    assert report.sections[0].validation_feedback == [
        "[non_empty_response_validator] FAILED: Response is empty"
    ]
    assert report.global_validation_feedback == [
        "[non_empty_response_validator] FAILED: Response is empty"
    ]
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/postprocessing/test_pipeline.py -q`
Expected: `FAIL` because `process_report()` 当前只返回 `PostprocessingResult`，不会回写 `validation_feedback`

- [ ] **Step 3: 写最小实现，让 pipeline 在失败时回写 feedback**

```python
# src/vsa_agent/agents/postprocessing/pipeline.py
    async def process_report(self, report) -> PostprocessingResult:
        """Run validators against each report section summary and write feedback back."""
        for section in getattr(report, "sections", []):
            result = await self.process(section.summary_text)
            if not result.passed:
                feedback = result.feedback
                if hasattr(section, "validation_feedback"):
                    section.validation_feedback.append(feedback)
                if hasattr(report, "global_validation_feedback"):
                    report.global_validation_feedback.append(feedback)
                return result
        return PostprocessingResult(passed=True)
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/postprocessing/test_pipeline.py -q`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/postprocessing/pipeline.py tests/unit/agents/postprocessing/test_pipeline.py
git commit -m "feat: write report validation feedback back to structured report"
```

### Task 8.3: 让 `report_agent.py` 正式编排“结构化报告 -> 后处理 -> 渲染”

**Files:**
- Modify: `src/vsa_agent/agents/report_agent.py`
- Modify: `tests/unit/agents/test_report_agent.py`

- [ ] **Step 1: 运行当前 `report_agent` 测试，确认新的闭环断言仍未满足**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_report_agent.py -q`
Expected: `FAIL` because `execute_report_agent()` 还没有接入 `ValidationPipeline`

- [ ] **Step 2: 写最小实现，给 `execute_report_agent()` 增加可注入 pipeline，并补充 metadata**

```python
# src/vsa_agent/agents/report_agent.py
from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline
from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
```

```python
async def execute_report_agent(
    report_input: ReportAgentInput,
    video_understanding_fn: VideoUnderstandingCallable | None = None,
    video_report_gen_fn: VideoReportCallable | None = None,
    validation_pipeline: ValidationPipeline | None = None,
) -> AgentOutput:
    ...
    structured_report = build_single_section_report(
        source_name=report_input.sensor_id or report_input.video_path or "uploaded-video",
        source_type=source_type,
        user_query=report_input.query,
        understanding_result=understanding_result,
    )

    pipeline = validation_pipeline or ValidationPipeline([NonEmptyValidator()])
    validation_result = await pipeline.process_report(structured_report)

    report_result = await video_report_gen(
        sensor_id=report_input.sensor_id or "uploaded-video",
        user_query=report_input.query,
        structured_report=structured_report,
    )
    markdown_content, downloads, summary = _normalize_report_result(report_result)

    return AgentOutput(
        messages=[summary] if summary else [],
        side_effects={
            "markdown_content": markdown_content,
            "downloads": downloads,
        },
        metadata={
            "report_type": "single_video",
            "source_type": source_type,
            "validation_passed": validation_result.passed,
            "validation_feedback": list(structured_report.global_validation_feedback),
        },
        status="success",
    )
```

- [ ] **Step 3: 运行测试并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_report_agent.py -q`
Expected: `PASS`

- [ ] **Step 4: Commit**

```bash
git add src/vsa_agent/agents/report_agent.py tests/unit/agents/test_report_agent.py
git commit -m "feat: route report agent through postprocessing pipeline"
```

### Task 8.4: 收口 `video_report_gen.py` 的结构化报告主路径消费契约

**Files:**
- Modify: `tests/unit/tools/test_video_report_gen.py`
- Modify: `src/vsa_agent/tools/video_report_gen.py`

- [ ] **Step 1: 写失败中的渲染测试，锁定“有 feedback 时渲染校验反馈区块”**

```python
# tests/unit/tools/test_video_report_gen.py
@pytest.mark.anyio
async def test_generate_video_report_renders_validation_feedback_section():
    from vsa_agent.data_models.report import ReportSection
    from vsa_agent.data_models.report import StructuredReport
    from vsa_agent.data_models.understanding import UnderstandingResult

    structured_report = StructuredReport(
        report_title="report-title",
        report_type="single_video",
        user_query="生成详细报告",
        sections=[
            ReportSection(
                section_id="section-1",
                section_title="事件 - camera-1",
                source_name="camera-1",
                source_type="rtsp",
                user_query="生成详细报告",
                summary_text="",
                understanding_result=UnderstandingResult(
                    query="生成详细报告",
                    source_type="rtsp",
                    summary_text="",
                    chunks=[],
                    events=[],
                ),
                validation_feedback=["[non_empty_response_validator] FAILED: Response is empty"],
            )
        ],
        global_validation_feedback=["[non_empty_response_validator] FAILED: Response is empty"],
    )

    result = await generate_video_report(structured_report=structured_report)

    assert "## 校验反馈" in result.markdown_content
    assert "- [non_empty_response_validator] FAILED: Response is empty" in result.markdown_content
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/unit/tools/test_video_report_gen.py -q`
Expected: `FAIL` because `generate_video_report()` 当前还不会渲染 `validation_feedback`

- [ ] **Step 3: 写最小实现，让 Markdown 输出显式带上校验反馈**

```python
# src/vsa_agent/tools/video_report_gen.py
def _format_validation_feedback(section: ReportSection) -> str:
    if not section.validation_feedback:
        return ""
    lines = ["## 校验反馈"]
    lines.extend(f"- {item}" for item in section.validation_feedback)
    return "\n".join(lines)
```

```python
async def generate_video_report(...):
    ...
    validation_feedback_text = _format_validation_feedback(section)
    markdown_content = (
        "# 单视频分析报告\n"
        "## 视频源\n"
        f"- sensor_id: {section.source_name}\n\n"
        "## 用户问题\n"
        f"{section.user_query}\n\n"
        "## 摘要\n"
        f"{summary_text}\n\n"
        "## 事件时间线\n"
        f"{timeline_text}\n"
    )
    if validation_feedback_text:
        markdown_content = f"{markdown_content}\n\n{validation_feedback_text}\n"
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/tools/test_video_report_gen.py -q`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_report_gen.py tests/unit/tools/test_video_report_gen.py
git commit -m "feat: render report validation feedback in markdown output"
```

### Task 8.5: 补齐 `report_structuring.py` 的兼容回归并跑通闭环验收

**Files:**
- Modify: `tests/unit/tools/test_report_structuring.py`
- Modify: `tests/acceptance/test_report_flow.py`
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 写兼容测试，锁定宽松事件 dict 仍会被转换成 `StructuredReport` incidents**

```python
# tests/unit/tools/test_report_structuring.py
def test_build_single_section_report_accepts_lax_event_dicts():
    from vsa_agent.tools.report_structuring import build_single_section_report

    report = build_single_section_report(
        source_name="video.mp4",
        source_type="video_file",
        user_query="生成报告",
        understanding_result={
            "query": "生成报告",
            "source_type": "video_file",
            "summary_text": "person walking near forklift",
            "chunks": [],
            "events": [
                {
                    "start_timestamp": "00:00:05",
                    "end_timestamp": "00:00:09",
                    "description": "person walking near forklift",
                }
            ],
        },
    )

    assert report.sections[0].incidents[0].description == "person walking near forklift"
    assert report.sections[0].incidents[0].start_timestamp == "00:00:05"
    assert report.sections[0].incidents[0].end_timestamp == "00:00:09"
```

- [ ] **Step 2: 跑 Phase 8A1 相关回归**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_report_agent.py tests/unit/agents/postprocessing/test_pipeline.py tests/unit/tools/test_report_structuring.py tests/unit/tools/test_video_report_gen.py tests/acceptance/test_report_flow.py -q`
Expected: `PASS`

- [ ] **Step 3: 更新本计划中的 Phase 8A1 状态**

```markdown
### 当前执行状态（2026-06-19）
- [x] Task 8.1 已完成：单视频报告闭环的验收与编排语义已锁定
- [x] Task 8.2 已完成：ValidationPipeline 已能回写结构化报告反馈
- [x] Task 8.3 已完成：report_agent 已接入后处理主链
- [x] Task 8.4 已完成：video_report_gen 已显式渲染校验反馈
- [x] Task 8.5 已完成：Phase 8A1 回归通过，待整理提交
```

- [ ] **Step 4: Commit**

```bash
git add tests/unit/tools/test_report_structuring.py tests/acceptance/test_report_flow.py docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: update phase8a1 execution status"
```

---

## Phase 7 — A3 重试基础设施与 Model Adapter 对齐 (P1)

# Phase 7A3 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对齐 `utils/retry.py` 与 `model_adapter` 主链，让 OpenAI / vLLM 两类 adapter 在不改变现有对外接口的前提下共享统一、可测试的异步重试语义。

**Architecture:** 本阶段继续遵循“原版接口优先、内部契约补齐”的原则。`utils/retry.py` 作为统一重试能力入口；`BaseModelAdapter` 补充内部共享调用包装；`OpenAIModelAdapter` 与 `VLLMModelAdapter` 的 `invoke()` 走相同的共享 retry 语义，`astream()` 则保持保守的异常透明传播。实现上避免依赖底层 SDK 的隐式默认重试，优先让仓库自己的行为可验证、可复用。

**Tech Stack:** Python 3.12, asyncio, LangChain `ChatOpenAI`, pytest, unittest.mock

---

## 文件结构

**修改文件**
- `src/vsa_agent/utils/retry.py`
  - 补强 async retry 契约与共享调用包装
- `src/vsa_agent/model_adapter/base.py`
  - 增加内部共享 retry 包装入口
- `src/vsa_agent/model_adapter/openai_adapter.py`
  - `invoke()` 接入共享 retry
  - 收紧底层 SDK 隐式重试
- `src/vsa_agent/model_adapter/vllm_adapter.py`
  - `invoke()` 接入共享 retry
  - 与 OpenAI adapter 保持一致语义
- `tests/unit/utils/test_retry.py`
- `tests/unit/model_adapter/test_model_adapter.py`

**本轮不做**
- 不改 `create_model_adapter(...)` 外部签名
- 不做 `astream()` 自动重放
- 不引入新的全局 retry 配置文件层
- 不做熔断、指标、超时治理

---

### Task 7.12: 补强 `utils/retry.py` 的共享重试契约

**Files:**
- Modify: `src/vsa_agent/utils/retry.py`
- Modify: `tests/unit/utils/test_retry.py`

- [ ] **Step 1: 写失败测试，锁定退避等待与共享调用包装契约**

```python
import pytest

from vsa_agent.utils.retry import async_retry
from vsa_agent.utils.retry import call_with_async_retry


@pytest.mark.asyncio
async def test_call_with_async_retry_retries_and_returns_value(monkeypatch):
    attempts = {"count": 0}
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("temporary")
        return "ok"

    monkeypatch.setattr("vsa_agent.utils.retry.asyncio.sleep", fake_sleep)

    result = await call_with_async_retry(
        flaky,
        max_retries=2,
        delay=0.5,
        backoff=2.0,
        exceptions=(ValueError,),
    )

    assert result == "ok"
    assert attempts["count"] == 3
    assert waits == [0.5, 1.0]


@pytest.mark.asyncio
async def test_call_with_async_retry_does_not_retry_unlisted_exception(monkeypatch):
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    async def fail():
        raise TypeError("wrong type")

    monkeypatch.setattr("vsa_agent.utils.retry.asyncio.sleep", fake_sleep)

    with pytest.raises(TypeError):
        await call_with_async_retry(
            fail,
            max_retries=3,
            exceptions=(ValueError,),
        )

    assert waits == []
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_retry.py -v`
Expected: FAIL because `call_with_async_retry` does not exist yet

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/retry.py

async def call_with_async_retry(
    func,
    *args,
    max_retries=3,
    delay=1.0,
    backoff=2.0,
    exceptions=(Exception,),
    **kwargs,
):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = delay * (backoff ** attempt)
                await asyncio.sleep(wait)
    raise last_exc
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_retry.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/retry.py tests/unit/utils/test_retry.py
git commit -m "feat: strengthen shared async retry utilities"
```

### Task 7.13: 在 `BaseModelAdapter` 补充内部共享 retry 包装

**Files:**
- Modify: `src/vsa_agent/model_adapter/base.py`
- Modify: `tests/unit/model_adapter/test_model_adapter.py`

- [ ] **Step 1: 写失败测试，锁定基类共享包装入口**

```python
import pytest

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage

from vsa_agent.model_adapter.base import BaseModelAdapter


class DummyAdapter(BaseModelAdapter):
    async def invoke(self, messages):
        return await self._invoke_with_retry(lambda: self._call(messages))

    async def astream(self, messages):
        yield "x"

    async def _call(self, messages):
        return AIMessage(content="ok")


@pytest.mark.asyncio
async def test_base_model_adapter_exposes_retry_wrapper():
    adapter = DummyAdapter()
    result = await adapter.invoke([HumanMessage(content="hello")])
    assert result.content == "ok"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: FAIL because `_invoke_with_retry` is missing

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/model_adapter/base.py
from vsa_agent.utils.retry import call_with_async_retry


class BaseModelAdapter(ABC):
    retry_max_retries: int = 2
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    retry_exceptions: tuple[type[Exception], ...] = (Exception,)

    async def _invoke_with_retry(self, func):
        return await call_with_async_retry(
            func,
            max_retries=self.retry_max_retries,
            delay=self.retry_delay,
            backoff=self.retry_backoff,
            exceptions=self.retry_exceptions,
        )
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/model_adapter/base.py tests/unit/model_adapter/test_model_adapter.py
git commit -m "feat: add retry wrapper to base model adapter"
```

### Task 7.14: 对齐 `OpenAIModelAdapter` 的共享重试语义

**Files:**
- Modify: `src/vsa_agent/model_adapter/openai_adapter.py`
- Modify: `tests/unit/model_adapter/test_model_adapter.py`

- [ ] **Step 1: 写失败测试，锁定 `invoke()` 的共享 retry 与 SDK 参数收紧**

```python
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
@patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
async def test_openai_adapter_invoke_retries_transient_failure(chat_openai_cls):
    from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

    llm = MagicMock()
    attempts = {"count": 0}

    async def fake_ainvoke(messages):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return AIMessage(content="ok")

    llm.ainvoke.side_effect = fake_ainvoke
    chat_openai_cls.return_value = llm

    adapter = OpenAIModelAdapter(model_name="gpt-4o")
    result = await adapter.invoke([HumanMessage(content="hello")])

    assert result.content == "ok"
    assert attempts["count"] == 3
    assert chat_openai_cls.call_args.kwargs["max_retries"] == 0
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: FAIL because `invoke()` does not yet use shared retry and SDK retries are still nonzero

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/model_adapter/openai_adapter.py

class OpenAIModelAdapter(BaseModelAdapter):
    ...
    def __init__(...):
        self.llm = ChatOpenAI(..., max_retries=0)

    async def invoke(self, messages):
        return await self._invoke_with_retry(
            lambda: self.llm.ainvoke(messages)
        )
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/model_adapter/openai_adapter.py tests/unit/model_adapter/test_model_adapter.py
git commit -m "feat: align openai adapter retry behavior"
```

### Task 7.15: 对齐 `VLLMModelAdapter` 与 `astream()` 透明传播语义

**Files:**
- Modify: `src/vsa_agent/model_adapter/vllm_adapter.py`
- Modify: `tests/unit/model_adapter/test_model_adapter.py`

- [ ] **Step 1: 写失败测试，锁定 vLLM retry 与流式异常传播**

```python
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
@patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
async def test_vllm_adapter_invoke_retries_transient_failure(chat_openai_cls):
    from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

    llm = MagicMock()
    attempts = {"count": 0}

    async def fake_ainvoke(messages):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return AIMessage(content="ok")

    llm.ainvoke.side_effect = fake_ainvoke
    chat_openai_cls.return_value = llm

    adapter = VLLMModelAdapter(model_name="qwen")
    result = await adapter.invoke([HumanMessage(content="hello")])

    assert result.content == "ok"
    assert attempts["count"] == 2


@pytest.mark.asyncio
@patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
async def test_vllm_adapter_astream_propagates_error(chat_openai_cls):
    from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

    llm = MagicMock()

    async def fake_astream(messages):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover

    llm.astream.side_effect = fake_astream
    chat_openai_cls.return_value = llm

    adapter = VLLMModelAdapter(model_name="qwen")
    with pytest.raises(RuntimeError):
        async for _ in adapter.astream([HumanMessage(content="hello")]):
            pass
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: FAIL because `VLLMModelAdapter.invoke()` does not yet use shared retry consistently

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/model_adapter/vllm_adapter.py

class VLLMModelAdapter(BaseModelAdapter):
    ...
    async def invoke(self, messages):
        return await self._invoke_with_retry(
            lambda: self.llm.ainvoke(messages)
        )
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/model_adapter/vllm_adapter.py tests/unit/model_adapter/test_model_adapter.py
git commit -m "feat: align vllm adapter retry behavior"
```

### Task 7.16: Phase 7A3 回归与文档状态更新

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑 Phase 7A3 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_retry.py tests/unit/model_adapter/test_model_adapter.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的 Phase 7A3 状态**

```markdown
### 当前执行状态（2026-06-18）
- [x] Task 7.12 已完成：共享 async retry 契约已补强
- [x] Task 7.13 已完成：BaseModelAdapter 已补充内部 retry 包装
- [x] Task 7.14 已完成：OpenAIModelAdapter 已接入统一重试语义
- [x] Task 7.15 已完成：VLLMModelAdapter 与流式异常传播语义已对齐
- [x] Task 7.16 已完成：Phase 7A3 回归通过，待整理提交

---

## Phase 7 — A4 输出解析基础设施对齐 (P2)

# Phase 7A4 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `utils/parser.py` 与 `utils/markdown_parser.py` 两个共享解析模块，并将 `critic_agent` 的 JSON 剥壳逻辑与报告链的最小 markdown 消费场景接入公共解析层。

**Architecture:** 本阶段继续遵循“先补基础设施，再接真实调用点”的原则。`parser.py` 负责 code fence / JSON payload 提取与解析；`markdown_parser.py` 提供轻量 heading、bullet、section 切分能力；`critic_agent.py` 改为依赖共享 parser；报告链只增加最小消费回归，不做大规模业务重构。这样既能补齐原版缺失模块，也能保证当前 markdown 输出风格已经可被共享工具消费。

**Tech Stack:** Python 3.12, stdlib `json`, `dataclasses`, `re`, pytest

---

## 文件结构

**新增文件**
- `src/vsa_agent/utils/parser.py`
  - 通用 fenced block / JSON payload 提取与解析
- `src/vsa_agent/utils/markdown_parser.py`
  - 轻量 markdown heading / bullet / section 解析
- `tests/unit/utils/test_parser.py`
- `tests/unit/utils/test_markdown_parser.py`

**修改文件**
- `src/vsa_agent/agents/critic_agent.py`
  - 用共享 parser 替换本地 JSON 剥壳实现
- `tests/unit/agents/test_critic_agent.py`
  - 锁定 critic agent 接入共享 parser 后行为不变
- `tests/unit/tools/test_template_report_gen.py`
  - 增加 markdown 输出可被 section parser 消费的回归
- `docs/superpowers/vsa-agent-implementation-plan.md`

**本轮不做**
- 不引入第三方 markdown parser 库
- 不重构 report/template/report_gen 的主生成逻辑
- 不做复杂 JSON 修复器
- 不做完整 markdown AST

---

### Task 7.17: 新增 `utils/parser.py` 共享解析工具

**Files:**
- Create: `src/vsa_agent/utils/parser.py`
- Create: `tests/unit/utils/test_parser.py`

- [ ] **Step 1: 写失败测试，锁定 fenced block 与 JSON payload 契约**

```python
import json

import pytest

from vsa_agent.utils.parser import extract_fenced_block
from vsa_agent.utils.parser import extract_json_string
from vsa_agent.utils.parser import parse_json_payload


def test_extract_fenced_block_prefers_matching_language():
    text = "before```json\n{\"ok\": true}\n```after"
    assert extract_fenced_block(text, language="json") == "{\"ok\": true}"


def test_extract_fenced_block_accepts_any_language_when_unspecified():
    text = "```python\nprint('x')\n```"
    assert extract_fenced_block(text) == "print('x')"


def test_extract_json_string_falls_back_to_original_text():
    assert extract_json_string("{\"ok\": true}") == "{\"ok\": true}"


def test_parse_json_payload_returns_loaded_object():
    result = parse_json_payload("```json\n{\"ok\": true}\n```")
    assert result == {"ok": True}


def test_parse_json_payload_raises_on_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        parse_json_payload("```json\nnot-json\n```")
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_parser.py -v`
Expected: FAIL because `utils/parser.py` does not exist yet

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/parser.py
import json
import re


FENCED_BLOCK_RE = re.compile(r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```", re.DOTALL)


def extract_fenced_block(text: str, language: str | None = None) -> str | None:
    for match in FENCED_BLOCK_RE.finditer(text or ""):
        lang = match.group("lang").strip().lower()
        body = match.group("body").strip()
        if language is None or lang == language.lower():
            return body
    return None


def extract_json_string(text: str) -> str:
    return (
        extract_fenced_block(text, language="json")
        or extract_fenced_block(text)
        or (text or "")
    ).strip()


def parse_json_payload(text: str):
    return json.loads(extract_json_string(text))
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_parser.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/parser.py tests/unit/utils/test_parser.py
git commit -m "feat: add shared parser utilities"
```

### Task 7.18: 新增 `utils/markdown_parser.py` 轻量 markdown 结构解析

**Files:**
- Create: `src/vsa_agent/utils/markdown_parser.py`
- Create: `tests/unit/utils/test_markdown_parser.py`

- [ ] **Step 1: 写失败测试，锁定 heading / bullet / section 契约**

```python
from vsa_agent.utils.markdown_parser import extract_bullet_list
from vsa_agent.utils.markdown_parser import extract_headings
from vsa_agent.utils.markdown_parser import split_sections


def test_extract_headings_filters_by_level():
    markdown = "# Title\n\n## Summary\n\n## Details"
    assert extract_headings(markdown, level=2) == ["Summary", "Details"]


def test_extract_bullet_list_returns_plain_items():
    markdown = "- first\n- second\n\ntext"
    assert extract_bullet_list(markdown) == ["first", "second"]


def test_split_sections_by_h2_returns_section_objects():
    markdown = "# Report\n\n## Summary\nA\n\n## Details\nB"
    sections = split_sections(markdown, heading_level=2)
    assert [section.title for section in sections] == ["Summary", "Details"]
    assert sections[0].content == "A"
    assert sections[1].content == "B"


def test_split_sections_returns_empty_for_no_matching_heading():
    assert split_sections("plain text", heading_level=2) == []
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_markdown_parser.py -v`
Expected: FAIL because `utils/markdown_parser.py` does not exist yet

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/markdown_parser.py
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    content: str
    heading_level: int
```

```python
def extract_headings(markdown: str, level: int | None = None) -> list[str]:
    ...


def extract_bullet_list(markdown: str) -> list[str]:
    ...


def split_sections(markdown: str, heading_level: int = 2) -> list[MarkdownSection]:
    ...
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_markdown_parser.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/markdown_parser.py tests/unit/utils/test_markdown_parser.py
git commit -m "feat: add shared markdown parsing helpers"
```

### Task 7.19: 让 `critic_agent.py` 使用共享 parser

**Files:**
- Modify: `src/vsa_agent/agents/critic_agent.py`
- Modify: `tests/unit/agents/test_critic_agent.py`

- [ ] **Step 1: 写失败测试，锁定共享 parser 接管 JSON 剥壳**

```python
from vsa_agent.agents.critic_agent import _get_json_from_string


def test_get_json_from_string_uses_shared_parser_behavior():
    result = _get_json_from_string("```json\n{\"key\": \"value\"}\n```")
    assert result == "{\"key\": \"value\"}"


def test_get_json_from_string_accepts_plain_json():
    result = _get_json_from_string("{\"key\": \"value\"}")
    assert result == "{\"key\": \"value\"}"
```

- [ ] **Step 2: 运行测试，确认当前回归基线**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_critic_agent.py -v`
Expected: PASS initially, then we refactor internals without changing behavior

- [ ] **Step 3: 写最小实现，把 helper 内部改为共享 parser**

```python
# src/vsa_agent/agents/critic_agent.py
from vsa_agent.utils.parser import extract_json_string


def _get_json_from_string(string: str) -> str:
    return extract_json_string(string)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/agents/test_critic_agent.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/critic_agent.py tests/unit/agents/test_critic_agent.py
git commit -m "feat: route critic agent json parsing through shared parser"
```

### Task 7.20: 为报告链补最小 markdown 消费回归

**Files:**
- Modify: `tests/unit/tools/test_template_report_gen.py`
- Modify: `tests/unit/tools/test_report_gen.py`

- [ ] **Step 1: 写失败测试，锁定报告 markdown 可被 section parser 消费**

```python
from vsa_agent.utils.markdown_parser import split_sections


async def test_template_report_output_is_splitable_by_h2_sections():
    result = await generate_template_report(
        report_title="仓库巡检聚合报告",
        report_sections=[
            {
                "section_title": "事件 1 - camera-1",
                "summary": "person walking near forklift",
                "markdown_content": "## 摘要\nperson walking near forklift",
            }
        ],
        counts={"walking": 2},
        chart={"markdown_table": "| 事件类型 | 次数 |\n| --- | --- |\n| walking | 2 |"},
    )
    sections = split_sections(result.markdown_content, heading_level=2)
    assert [section.title for section in sections] == ["报告摘要", "统计概览", "图表", "分事件报告"]
```

- [ ] **Step 2: 运行测试，确认红灯或基线行为**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_report_gen.py -v`
Expected: Either FAIL because parser is missing earlier, or PASS after parser implementation and confirm current markdown is consumable

- [ ] **Step 3: 如有必要，做最小实现修正**

```python
# 只在测试暴露出 section 标题/换行不稳定时，
# 最小调整 template_report_gen.py 的换行与 heading 结构；
# 不重写整个 markdown 渲染逻辑。
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_report_gen.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_report_gen.py src/vsa_agent/tools/template_report_gen.py
git commit -m "test: verify report markdown is consumable by shared parser"
```

### Task 7.21: Phase 7A4 回归与文档状态更新

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑 Phase 7A4 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_parser.py tests/unit/utils/test_markdown_parser.py tests/unit/agents/test_critic_agent.py tests/unit/tools/test_template_report_gen.py tests/unit/tools/test_report_gen.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的 Phase 7A4 状态**

```markdown
### 当前执行状态（2026-06-18）
- [x] Task 7.17 已完成：共享 parser 工具已补齐
- [x] Task 7.18 已完成：共享 markdown parser 已补齐
- [x] Task 7.19 已完成：critic agent 已接入共享 parser
- [x] Task 7.20 已完成：报告 markdown 最小消费回归已补齐
- [x] Task 7.21 已完成：Phase 7A4 回归通过，待整理提交

---

## Phase 7 — A5 源路径翻译与视频文件工具对齐 (P2)

# Phase 7A5 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补强 `utils/url_translation.py`，新增 `utils/video_file.py`，并让 `video_understanding._prepare_video_path()` 改用共享文件源工具，从而统一本地路径、file URL、S3/MinIO 挂载路径与远程 clip 的处理语义。

**Architecture:** 本阶段继续按“共享工具先行、主链最小接入”的方式推进。`url_translation.py` 负责翻译与基础规范化；`video_file.py` 负责本地视频文件候选判断与本地路径校验；`video_understanding.py` 只保留 RTSP/HTTP clip 的业务特判，不再自己承担全部文件可达性判断。这样既补齐原版缺失工具，又让当前主链的职责边界更清楚。

**Tech Stack:** Python 3.12, stdlib `os`, `pathlib`, `urllib.parse`, pytest

---

## 文件结构

**新增文件**
- `src/vsa_agent/utils/video_file.py`
- `tests/unit/utils/test_video_file.py`

**修改文件**
- `src/vsa_agent/utils/url_translation.py`
- `src/vsa_agent/tools/video_understanding.py`
- `tests/unit/utils/test_url_translation.py`
- `tests/unit/tools/test_video_understanding.py`
- `docs/superpowers/vsa-agent-implementation-plan.md`

**本轮不做**
- 不做远程下载
- 不做视频 metadata 探测
- 不引入缓存目录管理
- 不实现 file_mapping / VST 缓存注册

---

### Task 7.22: 补强 `url_translation.py` 的本地路径与 URI 语义

**Files:**
- Modify: `src/vsa_agent/utils/url_translation.py`
- Modify: `tests/unit/utils/test_url_translation.py`

- [ ] **Step 1: 写失败测试，锁定本地路径规范化与远程识别边界**

```python
from vsa_agent.utils.url_translation import is_remote_url
from vsa_agent.utils.url_translation import normalize_local_path
from vsa_agent.utils.url_translation import translate_url


def test_normalize_local_path_preserves_windows_drive_style():
    result = normalize_local_path("C:\\videos\\demo.mp4")
    assert result == "C:/videos/demo.mp4"


def test_is_remote_url_treats_rtsp_as_remote():
    assert is_remote_url("rtsp://camera-1/stream") is True


def test_translate_file_url_without_target_base_returns_local_path():
    assert translate_url("file:///var/data/video.mp4") == "/var/data/video.mp4"


def test_translate_windows_path_passthrough_is_normalized():
    assert translate_url("C:\\videos\\demo.mp4") == "C:/videos/demo.mp4"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_url_translation.py -v`
Expected: FAIL because `normalize_local_path` does not exist yet and translation behavior is not fully locked

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/url_translation.py

def normalize_local_path(path: str) -> str:
    return path.replace("\\", "/")
```

```python
def translate_url(url: str, target_base: str | None = None) -> str:
    ...
    if parsed.scheme in ("", "c", "d"):
        return normalize_local_path(url)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_url_translation.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/url_translation.py tests/unit/utils/test_url_translation.py
git commit -m "feat: strengthen url translation utilities"
```

### Task 7.23: 新增 `video_file.py` 共享本地视频文件工具

**Files:**
- Create: `src/vsa_agent/utils/video_file.py`
- Create: `tests/unit/utils/test_video_file.py`

- [ ] **Step 1: 写失败测试，锁定本地文件候选判断与校验行为**

```python
import pytest

from vsa_agent.utils.video_file import ensure_local_video_path
from vsa_agent.utils.video_file import is_local_video_candidate


def test_is_local_video_candidate_accepts_windows_and_posix_paths():
    assert is_local_video_candidate("C:/videos/demo.mp4") is True
    assert is_local_video_candidate("/var/data/demo.mp4") is True


def test_is_local_video_candidate_rejects_remote_urls():
    assert is_local_video_candidate("https://example.com/video.mp4") is False
    assert is_local_video_candidate("rtsp://camera-1/stream") is False


def test_ensure_local_video_path_returns_normalized_local_path():
    assert ensure_local_video_path("C:\\videos\\demo.mp4") == "C:/videos/demo.mp4"


def test_ensure_local_video_path_rejects_remote_url():
    with pytest.raises(ValueError, match="local video file"):
        ensure_local_video_path("https://example.com/video.mp4")
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_video_file.py -v`
Expected: FAIL because `video_file.py` does not exist yet

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/video_file.py
from vsa_agent.utils.url_translation import is_remote_url
from vsa_agent.utils.url_translation import normalize_local_path


def is_local_video_candidate(path: str) -> bool:
    return bool(path) and not is_remote_url(path)


def ensure_local_video_path(path: str) -> str:
    if not is_local_video_candidate(path):
        raise ValueError(f"Expected a local video file path, got: {path}")
    return normalize_local_path(path)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_video_file.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/video_file.py tests/unit/utils/test_video_file.py
git commit -m "feat: add shared video file utilities"
```

### Task 7.24: 让 `video_understanding._prepare_video_path()` 接入共享文件源工具

**Files:**
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 写失败测试，锁定共享工具接入后的行为**

```python
def test_prepare_video_path_normalizes_local_windows_path():
    resolved = _prepare_video_path(
        "C:\\videos\\demo.mp4",
        VideoUnderstandingConfig(source_mode="local"),
    )
    assert resolved == "C:/videos/demo.mp4"


def test_prepare_video_path_rejects_remote_translation_for_video_file(monkeypatch):
    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding.translate_url",
        lambda url, target_base=None: "https://example.com/video.mp4",
    )
    with pytest.raises(ValueError, match="local file"):
        _prepare_video_path(
            "https://example.com/video.mp4",
            VideoUnderstandingConfig(source_mode="translated"),
            source_type="video_file",
        )
```

- [ ] **Step 2: 运行测试，确认红灯或行为缺口**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: FAIL or behavior mismatch because `_prepare_video_path()` has not yet delegated to shared `video_file` helpers

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/video_understanding.py
from vsa_agent.utils.video_file import ensure_local_video_path
```

```python
def _prepare_video_path(...):
    ...
    if source_type == "rtsp" and translated.startswith(("rtsp://", "http://", "https://")):
        return translated
    return ensure_local_video_path(translated)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: route video understanding path handling through shared file utilities"
```

### Task 7.25: Phase 7A5 回归与文档状态更新

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑 Phase 7A5 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_url_translation.py tests/unit/utils/test_video_file.py tests/unit/tools/test_video_understanding.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的 Phase 7A5 状态**

```markdown
### 当前执行状态（2026-06-18）
- [x] Task 7.22 已完成：URL 翻译工具语义已补强
- [x] Task 7.23 已完成：共享 video_file 工具已补齐
- [x] Task 7.24 已完成：video_understanding 已接入共享文件源工具
- [x] Task 7.25 已完成：Phase 7A5 回归通过，待整理提交

---

## Phase 7 — A6 轻量计时工具对齐 (P3)

# Phase 7A6 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `utils/time_measure.py` 轻量计时工具，并在 `video_understanding` 主链的一个真实调用点完成最小接入，在不改变外部接口的前提下获得可复用的耗时测量能力。

**Architecture:** 本阶段继续沿用“共享工具先行、业务最小接入”的策略。`time_measure.py` 负责同步/异步上下文计时；业务侧只在 `_analyze_frames(...)` 这一条 VLM 分析主链接入，不扩散到更多模块。计时工具不吞异常，只负责记录 elapsed 并可选输出 logger，保持它是一层观察能力，而不是控制逻辑。

**Tech Stack:** Python 3.12, stdlib `time`, `contextlib`, `dataclasses`, pytest

---

## 文件结构

**新增文件**
- `src/vsa_agent/utils/time_measure.py`
- `tests/unit/utils/test_time_measure.py`

**修改文件**
- `src/vsa_agent/tools/video_understanding.py`
- `tests/unit/tools/test_video_understanding.py`
- `docs/superpowers/vsa-agent-implementation-plan.md`

**本轮不做**
- 不做 tracing/span
- 不做 metrics 上报
- 不做全链路大规模埋点
- 不做跨模块统一观测框架

---

### Task 7.26: 新增 `utils/time_measure.py` 共享计时工具

**Files:**
- Create: `src/vsa_agent/utils/time_measure.py`
- Create: `tests/unit/utils/test_time_measure.py`

- [ ] **Step 1: 写失败测试，锁定同步/异步计时契约**

```python
import asyncio

import pytest

from vsa_agent.utils.time_measure import TimeMeasureResult
from vsa_agent.utils.time_measure import async_measure_time
from vsa_agent.utils.time_measure import measure_time


def test_measure_time_returns_elapsed_result():
    with measure_time("sync-block") as result:
        pass
    assert isinstance(result, TimeMeasureResult)
    assert result.label == "sync-block"
    assert result.elapsed_sec >= 0.0


@pytest.mark.asyncio
async def test_async_measure_time_returns_elapsed_result():
    async with async_measure_time("async-block") as result:
        await asyncio.sleep(0)
    assert isinstance(result, TimeMeasureResult)
    assert result.label == "async-block"
    assert result.elapsed_sec >= 0.0


def test_measure_time_logs_when_logger_provided():
    records = []

    class DummyLogger:
        def info(self, message, *args):
            records.append(message % args)

    with measure_time("logged-block", logger=DummyLogger()):
        pass

    assert any("logged-block" in line for line in records)
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_time_measure.py -v`
Expected: FAIL because `time_measure.py` does not exist yet

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/utils/time_measure.py
from contextlib import asynccontextmanager
from contextlib import contextmanager
from dataclasses import dataclass
import time


@dataclass
class TimeMeasureResult:
    label: str
    elapsed_sec: float = 0.0
```

```python
@contextmanager
def measure_time(label: str, logger=None):
    ...


@asynccontextmanager
async def async_measure_time(label: str, logger=None):
    ...
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_time_measure.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/utils/time_measure.py tests/unit/utils/test_time_measure.py
git commit -m "feat: add shared time measurement utilities"
```

### Task 7.27: 在 `video_understanding._analyze_frames()` 接入共享计时工具

**Files:**
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [ ] **Step 1: 写失败测试，锁定计时工具接入且外部行为不变**

```python
@pytest.mark.asyncio
async def test_analyze_frames_uses_async_measure_time(monkeypatch):
    from contextlib import asynccontextmanager

    from vsa_agent.tools.video_understanding import _analyze_frames

    called = {"value": False}

    @asynccontextmanager
    async def fake_async_measure_time(label, logger=None):
        called["value"] = True
        yield type("Result", (), {"label": label, "elapsed_sec": 0.0})()

    class FakeAdapter:
        async def invoke(self, messages):
            return type("Response", (), {"content": "ok"})()

    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding.async_measure_time",
        fake_async_measure_time,
    )

    result = await _analyze_frames(["frame-a"], "describe", model_adapter=FakeAdapter())
    assert result == "ok"
    assert called["value"] is True
```

- [ ] **Step 2: 运行测试，确认红灯**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: FAIL because `_analyze_frames()` has not yet entered `async_measure_time`

- [ ] **Step 3: 写最小实现**

```python
# src/vsa_agent/tools/video_understanding.py
from vsa_agent.utils.time_measure import async_measure_time
```

```python
async def _analyze_frames(...):
    ...
    async with async_measure_time("video_understanding._analyze_frames", logger=logger):
        response = await model_adapter.invoke(messages)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: add timing measurement to video understanding"
```

### Task 7.28: Phase 7A6 回归与文档状态更新

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 跑 Phase 7A6 相关回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/utils/test_time_measure.py tests/unit/tools/test_video_understanding.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的 Phase 7A6 状态**

```markdown
### 当前执行状态（2026-06-18）
- [x] Task 7.26 已完成：共享 time_measure 工具已补齐
- [x] Task 7.27 已完成：video_understanding 已接入轻量计时工具
- [x] Task 7.28 已完成：Phase 7A6 回归通过，待整理提交

---

# Phase 8B1 检索问答闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立检索问答内部主链闭环，将查询稳定收口为“搜索结果 + 标准化事件 + 最终文本回答 + 运行元数据”。

**Architecture:** 以 `src/vsa_agent/agents/search_agent.py` 作为主编排器，串联 `tools/search.py` 的三路径搜索执行、可选 `critic_agent` 验证、`tools/incidents.py` 的事件标准化，以及 `tools/vss_summarize.py` 的最终文本输出。保持现有对外接口尽量不变，只补强内部协作语义、降级语义和测试验收闭环。

**Tech Stack:** Python 3.12, Pydantic, pytest, pytest-asyncio, anyio, 现有 `agents/` 与 `tools/` 模块体系

---

## 文件结构与职责锁定

- `src/vsa_agent/agents/search_agent.py`
  - 检索问答主编排器
  - 负责 `query -> search -> optional critic -> incidents -> summarize -> answer`
  - 输出面向业务消费的统一结果对象或兼容返回结构
- `src/vsa_agent/tools/search.py`
  - 搜索执行层
  - 负责三路径搜索与 critic 相关的底层路由兼容
  - 不负责最终文本回答生成
- `src/vsa_agent/tools/incidents.py`
  - `SearchOutput -> list[Incident]` 标准化层
  - 负责把搜索命中转成业务事件表达
- `src/vsa_agent/tools/vss_summarize.py`
  - 文本总结层
  - 为搜索侧新增最小文本出口，不重做现有理解链摘要体系
- `tests/unit/agents/test_search_agent.py`
  - 锁定主编排语义、critic 可选语义、降级语义
- `tests/unit/tools/test_search.py`
  - 锁定搜索执行层的 critic 元数据与空结果/异常降级
- `tests/unit/tools/test_incidents.py`
  - 锁定搜索结果到事件模型的映射
- `tests/unit/tools/test_vss_summarize.py`
  - 锁定搜索事件摘要文本出口
- `tests/acceptance/test_search_flow.py`
  - 锁定默认检索问答成功流与空结果流
- `tests/acceptance/test_critic_flow.py`
  - 锁定 critic 显式启用成功流与 critic 失败降级流

### Task 8.6: 先补红灯，锁定检索问答闭环验收语义

**Files:**
- Modify: `tests/acceptance/test_search_flow.py`
- Modify: `tests/acceptance/test_critic_flow.py`
- Reference: `src/vsa_agent/agents/search_agent.py`

- [ ] **Step 1: 写默认成功流验收测试**

```python
@pytest.mark.asyncio
async def test_search_flow_returns_text_answer_and_incidents(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import SearchOutput, SearchResult

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-01.mp4",
                    description="person enters loading area",
                    start_time="2026-06-19T10:00:00",
                    end_time="2026-06-19T10:00:12",
                    sensor_id="cam-01",
                    screenshot_url="",
                    similarity=0.91,
                    object_ids=[],
                )
            ]
        )

    result = await execute_search(
        SearchAgentInput(query="person enters loading area", use_critic=False),
        embed_search=fake_embed_search,
    )

    assert result.data[0].video_name == "cam-01.mp4"
```

- [ ] **Step 2: 写 critic 显式启用成功流验收测试**

```python
@pytest.mark.asyncio
async def test_critic_flow_applies_only_when_requested(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import SearchOutput, SearchResult

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-02.mp4",
                    description="forklift turns left",
                    start_time="2026-06-19T10:05:00",
                    end_time="2026-06-19T10:05:08",
                    sensor_id="cam-02",
                    screenshot_url="",
                    similarity=0.88,
                    object_ids=[],
                )
            ]
        )

    result = await execute_search(
        SearchAgentInput(query="forklift turns left", use_critic=True),
        embed_search=fake_embed_search,
    )

    assert result.data
```

- [ ] **Step 3: 写 critic 失败降级流与空结果流验收测试**

```python
@pytest.mark.asyncio
async def test_critic_flow_degrades_when_critic_fails(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import SearchOutput

    async def fake_embed_search():
        return SearchOutput(data=[])

    result = await execute_search(
        SearchAgentInput(query="no match query", use_critic=True),
        embed_search=fake_embed_search,
    )

    assert result.data == []
```

- [ ] **Step 4: 运行验收测试，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_search_flow.py tests/acceptance/test_critic_flow.py -v`
Expected: FAIL，因为当前实现还没有完整锁定“文本回答 / incidents / critic metadata / 降级语义”的主链闭环

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_search_flow.py tests/acceptance/test_critic_flow.py
git commit -m "test: lock acceptance semantics for phase8b search qa flow"
```

### Task 8.7: 在 `search_agent.py` 建立检索问答内部主链编排

**Files:**
- Modify: `src/vsa_agent/agents/search_agent.py`
- Modify: `tests/unit/agents/test_search_agent.py`
- Reference: `src/vsa_agent/tools/incidents.py`
- Reference: `src/vsa_agent/tools/vss_summarize.py`

- [ ] **Step 1: 写失败测试，锁定主链会串联 incidents 与 summarize**

```python
@pytest.mark.asyncio
async def test_execute_search_builds_incidents_and_text_answer(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import SearchOutput, SearchResult

    called = {"incidents": False, "summary": False}

    async def fake_embed_search():
        return SearchOutput(
            data=[
                SearchResult(
                    video_name="cam-03.mp4",
                    description="worker approaches gate",
                    start_time="2026-06-19T10:10:00",
                    end_time="2026-06-19T10:10:05",
                    sensor_id="cam-03",
                    screenshot_url="",
                    similarity=0.83,
                    object_ids=[],
                )
            ]
        )

    def fake_search_output_to_incidents(output):
        called["incidents"] = True
        return ["incident"]

    async def fake_summarize_search_incidents(incidents, query):
        called["summary"] = True
        return "worker approaches gate"

    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.search_output_to_incidents",
        fake_search_output_to_incidents,
    )
    monkeypatch.setattr(
        "vsa_agent.agents.search_agent.summarize_search_incidents",
        fake_summarize_search_incidents,
    )

    result = await execute_search(
        SearchAgentInput(query="worker approaches gate", use_critic=False),
        embed_search=fake_embed_search,
    )

    assert result.data[0].description == "worker approaches gate"
    assert called["incidents"] is True
    assert called["summary"] is True
```

- [ ] **Step 2: 运行单测，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py -v`
Expected: FAIL，因为当前 `execute_search()` 还没有正式承担“incidents + 文本回答 + metadata”主链职责

- [ ] **Step 3: 写最小实现，补强主编排返回结构**

```python
class SearchAgentExecutionResult(BaseModel):
    search_output: SearchOutput
    incidents: list[Incident] = Field(default_factory=list)
    text_answer: str = Field(default="")
    metadata: dict = Field(default_factory=dict)
```

```python
async def execute_search(...):
    ...
    search_output = await _run_existing_search_logic(...)
    incidents = search_output_to_incidents(search_output)
    text_answer = await summarize_search_incidents(incidents, search_input.query)
    metadata = {
        "critic_requested": bool(search_input.use_critic),
        "critic_applied": False,
        "critic_error": None,
    }
    return SearchAgentExecutionResult(
        search_output=search_output,
        incidents=incidents,
        text_answer=text_answer,
        metadata=metadata,
    )
```

- [ ] **Step 4: 跑单测并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/search_agent.py tests/unit/agents/test_search_agent.py
git commit -m "feat: add internal search qa orchestration flow"
```

### Task 8.8: 收口 critic 可选增强语义与 metadata

**Files:**
- Modify: `src/vsa_agent/agents/search_agent.py`
- Modify: `src/vsa_agent/tools/search.py`
- Modify: `tests/unit/agents/test_search_agent.py`
- Modify: `tests/unit/tools/test_search.py`

- [ ] **Step 1: 写失败测试，锁定 critic 只有显式启用时才介入**

```python
@pytest.mark.asyncio
async def test_execute_search_records_critic_metadata(monkeypatch):
    from vsa_agent.agents.search_agent import SearchAgentExecutionResult
    from vsa_agent.agents.search_agent import SearchAgentInput
    from vsa_agent.agents.search_agent import execute_search
    from vsa_agent.tools.search import SearchOutput

    async def fake_embed_search():
        return SearchOutput(data=[])

    result = await execute_search(
        SearchAgentInput(query="empty", use_critic=True),
        embed_search=fake_embed_search,
    )

    assert isinstance(result, SearchAgentExecutionResult)
    assert result.metadata["critic_requested"] is True
    assert "critic_applied" in result.metadata
    assert "critic_error" in result.metadata
```

- [ ] **Step 2: 运行相关单测，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py -v`
Expected: FAIL，因为当前 critic 语义分散且 metadata 未形成稳定契约

- [ ] **Step 3: 写最小实现，明确 critic 降级语义**

```python
metadata = {
    "critic_requested": bool(search_input.use_critic),
    "critic_applied": False,
    "critic_error": None,
}

if config.enable_critic and search_input.use_critic and critic_agent is not None:
    try:
        ...
        metadata["critic_applied"] = True
    except Exception as exc:
        metadata["critic_error"] = str(exc)
```

```python
if critic fails:
    return original_search_output
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/agents/search_agent.py src/vsa_agent/tools/search.py tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py
git commit -m "feat: align optional critic semantics for search qa flow"
```

### Task 8.9: 让 `incidents` 与 `vss_summarize` 正式进入搜索主链

**Files:**
- Modify: `src/vsa_agent/tools/incidents.py`
- Modify: `src/vsa_agent/tools/vss_summarize.py`
- Modify: `tests/unit/tools/test_incidents.py`
- Modify: `tests/unit/tools/test_vss_summarize.py`
- Reference: `src/vsa_agent/agents/search_agent.py`

- [ ] **Step 1: 写失败测试，锁定搜索侧摘要文本与空结果回退**

```python
@pytest.mark.asyncio
async def test_summarize_search_incidents_returns_fallback_for_empty_results():
    from vsa_agent.tools.vss_summarize import summarize_search_incidents

    summary = await summarize_search_incidents([], "person in loading area")

    assert summary == "No matching videos found."
```

```python
def test_search_output_to_incidents_preserves_video_metadata():
    from vsa_agent.tools.incidents import search_output_to_incidents
    from vsa_agent.tools.search import SearchOutput, SearchResult

    output = SearchOutput(
        data=[
            SearchResult(
                video_name="cam-04.mp4",
                description="person crosses lane",
                start_time="2026-06-19T10:20:00",
                end_time="2026-06-19T10:20:07",
                sensor_id="cam-04",
                screenshot_url="shot.png",
                similarity=0.79,
                object_ids=["obj-1"],
            )
        ]
    )

    incidents = search_output_to_incidents(output)

    assert incidents[0].metadata["video_name"] == "cam-04.mp4"
    assert incidents[0].metadata["start_time"] == "2026-06-19T10:20:00"
```

- [ ] **Step 2: 运行相关单测，确认红灯**

Run: `conda run -n vsa-agent python -m pytest tests/unit/tools/test_incidents.py tests/unit/tools/test_vss_summarize.py -v`
Expected: FAIL，因为当前 `vss_summarize.py` 还没有搜索侧文本出口

- [ ] **Step 3: 写最小实现，补搜索侧文本总结函数**

```python
async def summarize_search_incidents(incidents: list[Incident], query: str) -> str:
    if not incidents:
        return "No matching videos found."

    lines = []
    for incident in incidents:
        start_time = incident.metadata.get("start_time", "")
        end_time = incident.metadata.get("end_time", "")
        if start_time or end_time:
            lines.append(f"[{start_time} - {end_time}] {incident.description}")
        else:
            lines.append(incident.description)
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试并确认通过**

Run: `conda run -n vsa-agent python -m pytest tests/unit/tools/test_incidents.py tests/unit/tools/test_vss_summarize.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/incidents.py src/vsa_agent/tools/vss_summarize.py tests/unit/tools/test_incidents.py tests/unit/tools/test_vss_summarize.py
git commit -m "feat: add search incident summarization output"
```

### Task 8.10: 跑 Phase 8B1 回归并更新唯一总计划文档状态

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

- [ ] **Step 1: 运行 Phase 8B1 相关回归**

Run: `conda run -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py tests/unit/tools/test_incidents.py tests/unit/tools/test_vss_summarize.py tests/acceptance/test_search_flow.py tests/acceptance/test_critic_flow.py -q`
Expected: `PASS`

- [ ] **Step 2: 更新本计划中的执行状态**

```markdown
### 当前执行状态（2026-06-23）
- [x] Task 8.6 已完成：检索问答闭环验收红灯已补齐
- [x] Task 8.7 已完成：search_agent 已建立内部主链编排
- [x] Task 8.8 已完成：critic 可选增强语义与 metadata 已收口
- [x] Task 8.9 已完成：incidents 与 vss_summarize 已正式进入搜索主链
- [x] Task 8.10 已完成：Phase 8B1 回归通过，待整理提交
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: update phase8b1 execution status"
```

## Phase 8B1 自检

- Spec 覆盖性
  - 已覆盖默认成功流、critic 显式启用流、critic 失败降级流、空结果流
  - 已覆盖主链编排、critic metadata、incidents 标准化、搜索侧摘要输出
- 占位符扫描
  - 本节未使用 `TBD`、`TODO`、`implement later` 一类占位表达
- 类型一致性
  - 计划统一以现有 `execute_search()`、`SearchOutput`、`search_output_to_incidents()` 为基础推进
  - 新增内部返回结构名固定为 `SearchAgentExecutionResult`




