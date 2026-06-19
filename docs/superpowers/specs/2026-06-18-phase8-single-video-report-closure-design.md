# Phase 8 单视频分析报告闭环设计

> 范围：`agents/report_agent.py`、`tools/report_structuring.py`、`tools/video_report_gen.py`、`agents/postprocessing/pipeline.py`，以及相关数据模型与验收测试
> 日期：2026-06-18
> 目标：将单视频分析报告链正式收敛为“理解结果 -> 结构化报告 -> 后处理校验 -> Markdown 交付”的稳定业务闭环。

## 一、背景

到 Phase 7 结束时，项目已经补齐了较完整的基础设施层：

1. prompt / reasoning / async 生命周期
2. VSS 数据模型 / 时间转换 / 选帧
3. retry / model adapter
4. parser / markdown parser
5. URL / 视频文件 / 轻量计时

这意味着当前阶段继续补基础工具的边际收益已经下降。下一阶段更应该回到业务主线，验证现有模块是否已经能够稳定协作，形成真正可交付的能力闭环。

在当前代码中，单视频报告链已经具备初步形态：

- `video_understanding.py` 可以输出 `UnderstandingResult`
- `report_structuring.py` 已经能把理解结果转换成 `StructuredReport`
- `video_report_gen.py` 已经能渲染 Markdown
- `postprocessing/pipeline.py` 已经存在，但还没有真正成为报告主链的一部分

所以 Phase 8 的第一项子项目，不是从零造一条新链，而是把已有结构正式“主链化”，并用测试把它锁住。

## 二、现状问题

### 1. 结构已经出现，但还没有被主链契约锁住

当前 `report_agent.py` 已经调用：

- `normalize_understanding_result(...)`
- `build_single_section_report(...)`
- `generate_video_report(...)`

这说明“结构化报告对象”已经出现。但它当前更像内部便利对象，还没有成为单视频报告主链的明确中心契约。

### 2. 后处理能力仍然处于链外

`ValidationPipeline` 和 validators 已存在，但它们还没有稳定进入单视频报告主链。  
这会带来两个问题：

- 校验能力无法通过业务验收流证明自己真正生效
- 后续多视频报告、API 映射层会各自重新决定“要不要校验”“怎么带反馈”

### 3. 渲染层仍然承担了一部分宽松兼容责任

`video_report_gen.py` 当前既支持 `structured_report`，也兼容 `report_section`、`understanding_result` 等多种输入。  
这种兼容本身不是问题，但如果主链不明确，就容易让渲染层继续承担业务修补职责。

### 4. 现有测试能证明“能跑”，但还不能证明“闭环”

当前验收和单测已经覆盖了：

- `report_agent` 能生成 Markdown
- `structured_report` 已被传递
- 宽松事件 dict 可以兼容

但还缺少以下闭环层面的保证：

- `postprocessing` 是否正式进入主链
- 后处理失败时的业务语义是什么
- 理解失败和校验失败是否被明确区分

## 三、业务位置

Phase 8 这一子项目位于“视频理解”和“最终交付报告”之间，是最核心的单视频交付链。

目标业务流如下：

1. 用户提供 `video_path` 或 `sensor_id`
2. `report_agent` 调用 `analyze_video(...)`
3. 得到 `UnderstandingResult`
4. 进入 `report_structuring.py`，组装为 `StructuredReport`
5. 通过 `ValidationPipeline.process_report(...)` 做摘要级校验
6. 将校验反馈回写到结构化报告对象
7. `video_report_gen.py` 消费 `StructuredReport`
8. 输出 Markdown 报告与下载元数据

这条链是后续以下能力的共同基础：

- 多视频汇总报告
- API 报告输出
- 后续更严格的审校与验收

## 四、设计目标

本子项目的设计目标如下：

1. 将单视频报告主链正式定义为：
   `video_understanding -> structured_report -> postprocessing -> markdown`
2. 将 `StructuredReport` 提升为内部主契约
3. 让 `postprocessing` 正式进入主链，而不是保留为旁路工具
4. 保持现有对外接口尽量不变
5. 用单元测试和验收测试锁定主链行为、失败语义和兼容语义

非目标：

- 本轮不处理前端展示
- 不扩到多视频报告链
- 不纳入 API 入口层
- 不推进真实 ES / 更真实 VST 深接入

## 五、候选方案

### 方案 A：最小收口

做法：

- 保持现有 `report_agent -> report_structuring -> video_report_gen`
- 仅增加验收测试
- 不把 `postprocessing` 正式纳入主链

优点：

- 改动小
- 能快速形成一轮回归

缺点：

- 不能解决主链契约不清问题
- 后处理依旧是链外能力
- 后续继续扩展时仍会返工

### 方案 B：结构化报告主链化（本轮采用）

做法：

- 明确 `StructuredReport` 为单视频报告内部唯一主契约
- 固定主链顺序为：
  `analyze_video -> normalize -> build_single_section_report -> process_report -> generate_video_report`
- `report_agent` 只做编排
- `video_report_gen` 只做渲染
- `postprocessing` 负责校验与反馈回写

优点：

- 模块边界最清晰
- 最符合按业务流理解系统的目标
- 后续扩展到多视频报告与 API 最顺滑

缺点：

- 需要补齐内部装配和测试
- 需要重新定义主链验收重点

### 方案 C：后处理优先接入

做法：

- 先让 `ValidationPipeline` 插进现有链
- 暂不强调 `StructuredReport` 主契约

优点：

- 见效快

缺点：

- 会把重点偏移到“文本校验”
- 不能真正稳定报告域边界

## 六、最终方案

本轮采用方案 B：结构化报告主链化。

核心判断：

- 当前项目已经具备报告域对象雏形
- 当前真正缺的是“统一的主链语义”，不是某个单独工具文件
- 只要把 `StructuredReport` 立住，`incidents`、`geolocation`、`postprocessing` 就能自然成为主链成员

## 七、模块职责设计

### 1. `agents/report_agent.py`

角色：编排器

职责：

- 校验最小输入
- 解析 `source_type`
- 调用视频理解
- 调用结构化装配
- 调用后处理
- 调用 Markdown 渲染
- 组装 `AgentOutput`

约束：

- 不承担事件归一化细节
- 不承担 Markdown 拼装细节
- 不承担 validators 规则实现

### 2. `tools/video_understanding.py`

角色：理解层

职责：

- 读取视频输入
- 调用模型或相关逻辑
- 输出 `UnderstandingResult`

约束：

- 不感知报告域对象
- 不感知 Markdown
- 不承担报告后处理

### 3. `tools/report_structuring.py`

角色：报告域装配层

职责：

- 宽松输入标准化
- `UnderstandingResult` -> `StructuredReport`
- 统一接入 `incidents` 与 `geolocation`

这是本轮最核心的业务转换层。

### 4. `agents/postprocessing/pipeline.py`

角色：报告校验层

职责：

- 对 `StructuredReport.sections[*].summary_text` 做校验
- 汇总 `PostprocessingResult`
- 将失败反馈回写到结构化报告对象

本轮只做轻量校验，不做自动修复和自动重写。

### 5. `tools/video_report_gen.py`

角色：渲染层

职责：

- 消费 `StructuredReport`
- 生成最终 Markdown
- 生成下载元数据

约束：

- 不承担业务归一化
- 兼容入口可以保留，但主路径必须以 `structured_report` 为准

## 八、数据流设计

主数据流固定为：

```text
ReportAgentInput
  -> analyze_video(...)
  -> UnderstandingResult
  -> normalize_understanding_result(...)
  -> build_single_section_report(...)
  -> StructuredReport
  -> ValidationPipeline.process_report(...)
  -> 回写 validation_feedback / global_validation_feedback
  -> generate_video_report(structured_report=...)
  -> VideoReportGenOutput
  -> AgentOutput
```

其中最重要的约束有三个：

1. `StructuredReport` 是主链中间契约
2. `postprocessing` 位于渲染之前
3. `generate_video_report(...)` 的主路径消费对象是结构化报告，而不是原始理解结果

## 九、错误语义

### 1. 输入错误

示例：

- `video_path` 和 `sensor_id` 都未提供

策略：

- 在 `report_agent` 起点直接抛 `ValueError`
- 不进入后续链路

### 2. 理解阶段错误

示例：

- 视频读取失败
- 模型调用失败
- `analyze_video(...)` 执行失败

策略：

- 不吞异常
- 直接向上抛出
- 不生成伪报告

### 3. 结构化阶段错误

示例：

- 理解结果结构非法
- `StructuredReport.sections` 为空

策略：

- 在 `report_structuring.py` 与 `video_report_gen.py` 内部尽早报错
- 不静默渲染错误 Markdown
- 对当前已承诺兼容的“宽松事件 dict”保持支持

### 4. 后处理校验失败

示例：

- 摘要为空
- 某项 validator 未通过

策略：

- 不直接中断整条主链
- 将反馈回写到：
  - `ReportSection.validation_feedback`
  - `StructuredReport.global_validation_feedback`
- 最终仍允许生成 Markdown

这里要明确区分两类情况：

- 业务执行失败：中断主链
- 校验未通过：保留交付物，并显式带反馈

## 十、测试与验收设计

### 1. 单元测试

重点文件：

- `tests/unit/agents/test_report_agent.py`
- `tests/unit/tools/test_report_structuring.py`
- `tests/unit/tools/test_video_report_gen.py`
- `tests/unit/agents/postprocessing/test_pipeline.py`

覆盖重点：

- `report_agent`
  - 正常串起整条链
  - 缺输入时报错
  - 理解阶段异常向上抛
  - 后处理失败时仍返回报告且反馈可见

- `report_structuring`
  - `UnderstandingResult -> StructuredReport`
  - incidents 映射正确
  - geolocation summary 被挂入 section
  - 宽松 event dict 兼容

- `video_report_gen`
  - 主路径优先消费 `structured_report`
  - section 为空时报错
  - Markdown 中包含摘要、时间线、来源、用户问题

- `ValidationPipeline`
  - 校验通过
  - 首个失败即返回
  - `process_report()` 能按 section 工作

### 2. 组件级测试

重点锁模块协作：

- `report_agent` 会调用 `build_single_section_report(...)`
- `report_agent` 会调用 `ValidationPipeline.process_report(...)`
- `report_agent` 会将带 feedback 的 `structured_report` 传给 `generate_video_report(...)`

### 3. 验收测试

重点文件：

- `tests/acceptance/test_report_flow.py`

建议锁定四类场景：

1. 标准成功流
2. 宽松理解结果兼容流
3. 后处理失败但仍可交付流
4. 理解阶段失败流

## 十一、完成标准

满足以下条件，即可认为本子项目完成：

1. 单视频报告主链固定为：
   `understanding -> structured_report -> postprocessing -> markdown`
2. `StructuredReport` 成为内部主路径唯一主契约
3. `postprocessing` 正式进入主链
4. 验收测试可以证明：
   - 正常流可交付
   - 宽松输入可兼容
   - 校验失败可反馈
   - 理解错误会中断
5. 保持现有对外工具名、主要入参与返回外形不变

## 十二、实施顺序建议

建议按以下顺序进入实现：

1. 先补验收测试，锁定闭环语义
2. 再补 `report_agent` 主链编排
3. 再补 `StructuredReport` 回写反馈逻辑
4. 最后收口 `video_report_gen` 的主路径消费契约

这能最大程度保证我们是在“用测试拉业务闭环”，而不是先改结构再找测试兜底。
