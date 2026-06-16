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

### 未实现模块 (Gap)

| 模块 | NVIDIA 文件 | 说明 | 优先级 |
|------|------------|------|--------|
| agents/multi_report_agent.py | multi_report_agent.py | 多事件报告 Agent | P2 |
| agents/postprocessing/ | postprocessing/ | 后处理管道 | P2 |
| tools/report_gen.py | report_gen.py | 报告生成工具 | P2 |
| tools/template_report_gen.py | template_report_gen.py | 模板报告生成 | P2 |
| tools/chart_generator.py | chart_generator.py | 图表生成 | P2 |
| tools/fov_counts_with_chart.py | fov_counts_with_chart.py | FOV 计数+图表 | P2 |
| tools/incidents.py | incidents.py | 事件管理 | P2 |
| tools/geolocation.py | geolocation.py | 地理位置 | P2 |
| tools/multi_incident_formatter.py | multi_incident_formatter.py | 多事件格式化 | P2 |
| tools/video_caption.py | video_caption.py | 视频字幕 | P2 |
| tools/video_detailed_caption.py | video_detailed_caption.py | 详细视频字幕 | P2 |
| tools/video_skim_caption.py | video_skim_caption.py | 视频快速字幕 | P2 |
| tools/video_frame_timestamp.py | video_frame_timestamp.py | 视频帧时间戳 | P2 |
| tools/lvs_video_understanding.py | lvs_video_understanding.py | 长视频理解 | P1 |
| tools/vss_summarize.py | vss_summarize.py | VSS 汇总 | P1 |
| tools/prompt_gen.py | prompt_gen.py | VLM prompt 生成 | P1 |
| embed/embed.py | embed.py | EmbedClient ABC | P1 |
| embed/cosmos_embed.py | cosmos_embed.py | Cosmos 嵌入客户端 | P1 |
| embed/rtvi_cv_embed.py | rtvi_cv_embed.py | RTVI CV 嵌入客户端 | P1 |
| data_models/vss.py | vss.py | MediaInfoOffset/Incident | P1 |
| utils/frame_select.py | frame_select.py | 帧选择 | P1 |
| utils/time_convert.py | time_convert.py | 时间转换 | P1 |
| utils/time_measure.py | time_measure.py | 时间测量 | P3 |
| utils/url_translation.py | url_translation.py | URL 翻译 | P1 |
| utils/reasoning_parsing.py | reasoning_parsing.py | 推理内容解析 | P1 |
| utils/reasoning_utils.py | reasoning_utils.py | 推理工具 | P1 |
| utils/markdown_parser.py | markdown_parser.py | Markdown 解析 | P3 |
| utils/parser.py | parser.py | 通用解析 | P3 |
| utils/video_file.py | video_file.py | 视频文件工具 | P3 |
| utils/asyncmixin.py | asyncmixin.py | 异步初始化 | P1 |
| api/rtsp_stream_api.py | rtsp_stream_api.py | RTSP 流管理 | P3 |
| api/video_delete.py | video_delete.py | 视频删除 | P3 |
| evaluators/ | evaluators/ | 评估框架 | P3 |
| prompt.py | prompt.py | 独立 prompt 常量 | P1 |

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
- [ ] 实现 embed/rtvi_cv_embed.py (OpenAI 替代 RTVI CV)

### Task 0.4: 补齐 utils/ 工具函数
- [ ] 实现 utils/frame_select.py
- [ ] 实现 utils/time_convert.py
- [ ] 实现 utils/url_translation.py
- [ ] 实现 utils/reasoning_parsing.py
- [ ] 实现 utils/reasoning_utils.py
- [ ] 实现 utils/asyncmixin.py

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

**目标**: RTSP stream API, VST 服务集成, video_delete API

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
