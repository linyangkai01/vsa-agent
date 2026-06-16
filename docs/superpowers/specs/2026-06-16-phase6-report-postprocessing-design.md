# Phase 6 报告后处理链设计

> 范围：`report_agent.py`、`multi_report_agent.py`、`report_gen.py`、`template_report_gen.py`、`video_report_gen.py`、`incidents.py`、`geolocation.py`、`agents/postprocessing/`
> 日期：2026-06-16
> 目标：在现有报告生成链路之上，补齐“结构化报告对象 -> 后处理 -> Markdown 渲染”的统一业务闭环

## 总体说明

Phase 6 的核心目标不是新增一条独立业务线，而是把 Phase 3 和 Phase 4 已经具备的能力真正接起来。

当前项目已经具备这些基础：
- `video_understanding.py` / `lvs_video_understanding.py` 能产出结构化 `UnderstandingResult`
- `incidents.py` 能把 `UnderstandingResult` 或 `SearchOutput` 归一化为 `Incident`
- `geolocation.py` 能为 `Incident` 补默认位置并生成区域摘要
- `postprocessing/pipeline.py` 和 validators 能对文本输出执行基础校验
- `video_report_gen.py` / `report_gen.py` / `template_report_gen.py` 能生成单视频和多视频 Markdown 报告

但目前报告链还存在一个明显断层：
- `report_agent` 和 `multi_report_agent` 在理解结果之后，几乎直接进入 Markdown 渲染
- `incidents`、`geolocation`、`postprocessing` 还没有作为正式报告链的一部分参与
- 缺少一个稳定的“结构化报告对象”作为报告域内的统一中间契约

Phase 6 要解决的就是这个断层：先建立统一的结构化报告对象，再在对象层完成事件归一化、地理信息补全、后处理校验，最后由渲染层生成 Markdown。

## 业务流位置

Phase 6 位于“视频理解”和“最终报告交付”之间，处在报告生成主链的中段。

完整业务流将变为：

1. `report_agent` / `multi_report_agent` 调用 `analyze_video(...)`
2. 获得 `UnderstandingResult`
3. 将 `UnderstandingResult` 转换为统一的结构化报告对象
4. 在结构化对象层执行：
   - `incidents` 归一化
   - `geolocation` 补全与摘要
   - `postprocessing` 校验
5. 将后处理后的结构化报告对象交给 Markdown 渲染层
6. 输出最终 Markdown 报告和必要元数据

这个位置很关键，因为它决定后面无论是：
- 单视频报告
- 多视频聚合报告
- 带图表报告
- 带地理信息报告
- 带审核/校验反馈报告

都可以共享同一套报告域对象，而不是每条链路自己拼 Markdown。

## 设计目标

Phase 6 设计目标如下：

1. 在不破坏现有公开工具接口的前提下，引入内部统一报告对象
2. 让 `incidents`、`geolocation`、`postprocessing` 真正进入报告主链
3. 保持 `report_agent_tool`、`multi_report_agent_tool`、`generate_video_report` 等对外能力可用
4. 单视频和多视频报告复用同一套后处理流程
5. 让 Markdown 渲染只负责展示，不承担业务归一化和校验逻辑

非目标：

- 本阶段不做新的前端展示层
- 不引入新的外部在线依赖
- 不重做 chart 统计逻辑
- 不把搜索链纳入同一轮实施

## 两种可选方案

### 方案 A：继续以 Markdown 为中心扩展

做法：
- 继续沿用现有 `video_report_gen.py` / `template_report_gen.py`
- 在生成 Markdown 前后插入 `incidents`、`geolocation`、`validators`
- 不引入新的结构化报告对象

优点：
- 改动小
- 落地快

缺点：
- 业务逻辑会继续散落在 agent、tool、renderer 之间
- 后处理逻辑越来越依赖文本格式
- 后面加多种报告模板时容易重复实现

### 方案 B：引入结构化报告对象，再统一后处理（推荐）

做法：
- 新增报告域数据模型，例如单节报告对象、聚合报告对象、后处理结果对象
- `report_agent` / `multi_report_agent` 先产出结构化报告对象
- `incidents`、`geolocation`、`postprocessing` 在对象层运行
- `video_report_gen.py` / `template_report_gen.py` 只做 Markdown 渲染

优点：
- 模块边界清晰
- 后处理逻辑可测试、可复用
- 单视频和多视频主链能自然统一
- 后面扩展搜索报告、审核报告会更顺

缺点：
- 需要新增一层内部模型和装配逻辑

### 方案 C：结构化对象和 Markdown 双层都校验

做法：
- 先引入结构化对象层
- 对结构化对象执行业务校验
- 渲染完成后再对 Markdown 做一轮文本校验

优点：
- 最完整

缺点：
- 本阶段实现面偏大
- 容易把重点从“统一报告域对象”分散到“双层校验”

## 最终选择

本阶段采用方案 B。

原因：
- 它最符合你已经确定的方向：“先处理结构化报告对象，再生成 Markdown”
- 也最符合现有项目的演进顺序：Phase 2 已有结构化理解结果，Phase 4 已有 incidents / geolocation，Phase 6 正好把它们装进同一个报告域

## 模块职责设计

### 1. 报告域数据模型

建议新增一个专门的报告域模型文件，例如：
- `src/vsa_agent/data_models/report.py`

负责定义内部统一报告对象。

建议包含这些对象：

```python
class ReportEvidence(BaseModel):
    source_name: str
    source_type: str
    sensor_id: str | None = None
    video_path: str | None = None


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

职责边界：
- 这是报告域内的唯一主契约
- agent 层和 renderer 层之间只传这个对象
- 不在这个对象里存 Markdown 文本

### 2. incidents 归一化层

`incidents.py` 在 Phase 6 中不再只作为“独立工具函数”，而是成为报告装配流程的一部分。

职责：
- 把 `UnderstandingResult.events` 转换为 `Incident`
- 再映射为报告域里的 `ReportIncident`
- 保留原始 metadata，方便最终渲染和后续扩展

建议策略：
- 保留现有 `understanding_to_incidents(...)`
- 新增一个内部适配函数，例如：

```python
def incidents_to_report_items(
    incidents: list[Incident],
) -> list[ReportIncident]:
    ...
```

这样可以避免把报告域逻辑硬塞回 `video_analytics.nvschema.Incident`。

### 3. geolocation 补全层

`geolocation.py` 在 Phase 6 中承担两件事：

1. 补全每个事件的 location / zone
2. 为每个报告 section 生成 location summary

职责：
- 对 `Incident` 或 `ReportIncident` 做 location enrich
- 输出分 section 的区域摘要文本

建议：
- 保留现有 `enrich_incidents_with_location(...)`
- 保留现有 `summarize_geolocation(...)`
- 新增内部装配函数，把 enrich 结果同步回 `ReportSection.incidents`

默认策略：
- 继续只做默认填充，不接真实 GIS 或地图服务
- location 信息优先来自已有 incident 字段，缺失时再用默认值

### 4. postprocessing 层

当前 `ValidationPipeline` 只接收纯字符串：

```python
async def process(self, output: str) -> PostprocessingResult
```

Phase 6 建议分两层：

- 第一层：结构化报告对象的业务校验
- 第二层：保留现有 Markdown 文本校验能力

但本阶段只正式实现第一层作为主链，第二层先保留兼容。

建议做法：

1. 保留现有 `process(output: str)` 兼容接口
2. 新增面向结构化报告对象的接口，例如：

```python
async def process_report(report: StructuredReport) -> PostprocessingResult
```

3. 新增面向报告对象的 validators，例如：
- `SectionNonEmptyValidator`
- `IncidentPresenceValidator`
- `LocationSummaryValidator`

本阶段推荐最小集合：
- section 至少有 summary 或 incidents
- 多 section 报告不能没有 section
- location summary 与 incidents 数量保持一致语义

### 5. Markdown 渲染层

`video_report_gen.py` 和 `template_report_gen.py` 在 Phase 6 中要收缩职责：

- 不再直接消费“裸的 UnderstandingResult dict”
- 改为消费 `ReportSection` 或 `StructuredReport`
- 只负责把已有结构化内容渲染成 Markdown

建议边界：

`video_report_gen.py`
- 输入一个 `ReportSection`
- 输出单 section Markdown 块

`template_report_gen.py`
- 输入一个 `StructuredReport`
- 输出完整聚合 Markdown

`report_gen.py`
- 负责结构化报告总装与 renderer 调度
- 不再自己隐式承担业务归一化

## 数据流设计

### 单视频报告链

```text
ReportAgentInput
  -> analyze_video(...)
  -> UnderstandingResult
  -> build_structured_single_report(...)
  -> incidents normalize
  -> geolocation enrich
  -> postprocessing process_report
  -> render single report markdown
  -> AgentOutput
```

### 多视频报告链

```text
MultiReportAgentInput
  -> analyze_video(...) x N
  -> UnderstandingResult x N
  -> build_structured_multi_report(...)
  -> incidents normalize per section
  -> geolocation enrich per section
  -> postprocessing process_report
  -> render aggregated markdown
  -> AgentOutput
```

## 接口设计

### 结构化报告装配接口

建议新增一个内部装配模块，例如：
- `src/vsa_agent/tools/report_structuring.py`

建议接口：

```python
def build_single_section_report(
    *,
    source_name: str,
    source_type: str,
    user_query: str,
    understanding_result: UnderstandingResult,
) -> StructuredReport:
    ...


def build_multi_section_report(
    *,
    report_title: str,
    user_query: str,
    sections: list[tuple[str, str, UnderstandingResult]],
) -> StructuredReport:
    ...
```

职责：
- 统一构造 `StructuredReport`
- 把 `UnderstandingResult` 接到报告域对象
- 调用 incidents / geolocation / postprocessing

### Agent 层接口

对外接口保持不变：

```python
async def execute_report_agent(...) -> AgentOutput
async def execute_multi_report_agent(...) -> AgentOutput
```

内部变化：
- 不再直接把 `understanding_result` 塞给 Markdown 生成器
- 改为先构建 `StructuredReport`

### 渲染层接口

建议目标接口：

```python
async def generate_video_report(
    report_section: ReportSection,
) -> VideoReportGenOutput


async def generate_template_report(
    structured_report: StructuredReport,
    counts: dict[str, int] | None = None,
    chart: dict[str, Any] | None = None,
) -> TemplateReportGenOutput
```

为控制改动范围，本阶段也可以保留兼容签名，在内部先适配到新对象：

```python
if legacy arguments provided:
    convert to ReportSection / StructuredReport
```

## 错误处理

Phase 6 错误处理原则：

1. 结构化对象缺少关键字段时，优先在装配阶段失败
2. 单个 section 的 geolocation 补全失败，不应静默吞掉；要明确反馈到 `validation_feedback`
3. validator 失败不一定中断报告生成，但必须进入结构化报告对象和最终 metadata
4. Markdown renderer 不做业务修复，只消费已经处理好的对象

建议：
- `process_report(...)` 返回 `passed + feedback`
- 如果 `passed=False`，仍可生成报告，但在 `AgentOutput.metadata` 和报告对象中带出反馈

## 测试策略

### 单元测试

新增或补强这些测试：

1. `tests/unit/data_models/test_report_models.py`
   - 结构化报告对象构造
   - 默认值
   - 序列化

2. `tests/unit/tools/test_report_structuring.py`
   - `UnderstandingResult -> StructuredReport`
   - incidents 映射
   - geolocation summary 写入

3. `tests/unit/agents/postprocessing/test_pipeline.py`
   - `process_report(...)` 正常路径
   - validator 失败路径

4. `tests/unit/tools/test_video_report_gen.py`
   - `ReportSection -> markdown`

5. `tests/unit/tools/test_template_report_gen.py`
   - `StructuredReport -> aggregated markdown`

6. `tests/unit/agents/test_report_agent.py`
   - 单视频报告 agent 复用结构化报告装配

7. `tests/unit/agents/test_multi_report_agent.py`
   - 多视频报告 agent 复用统一结构化报告装配

### 验收测试

新增一条 Phase 6 验收链：

- `tests/acceptance/test_phase6_report_postprocessing_flow.py`

覆盖：
- 单视频报告：理解结果 -> incidents -> geolocation -> validation -> markdown
- 多视频报告：多 section 聚合后处理 -> markdown

## 实现顺序

建议顺序：

1. 新增报告域数据模型
2. 新增结构化报告装配模块
3. 让 `incidents` 和 `geolocation` 接入装配流程
4. 扩展 `ValidationPipeline` 支持结构化报告对象
5. 调整 `video_report_gen.py` / `template_report_gen.py` 改为消费结构化对象
6. 调整 `report_agent.py` / `multi_report_agent.py` 接到新主链
7. 补 Phase 6 验收测试

## 验收标准

Phase 6 完成标准：

- 单视频报告主链内部经过 `StructuredReport`
- 多视频报告主链内部经过 `StructuredReport`
- `incidents` 与 `geolocation` 成为报告正式主链的一部分
- `postprocessing` 可对结构化报告对象运行
- Markdown 渲染层不再承担业务归一化职责
- 不破坏现有 `report_agent_tool` / `multi_report_agent_tool` 的外部调用方式
- 单元测试和验收测试全部通过
