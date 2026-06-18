# Phase 7A6 轻量计时工具对齐设计

> 范围：`utils/time_measure.py`，以及 `video_understanding.py` / `lvs_video_understanding.py` 的最小计时接入
> 日期：2026-06-18
> 目标：补齐原版中缺失的 `time_measure.py`，提供轻量、稳定、可复用的耗时测量工具，并在一个真实业务调用点上完成最小接入。

## 一、背景

到 Phase 7A5 为止，Phase 7 已经补齐了多组共享基础设施：

1. A1：prompt / reasoning / async 生命周期
2. A2：VSS 数据模型 / 时间转换 / 选帧
3. A3：retry / model adapter
4. A4：parser / markdown_parser
5. A5：url_translation / video_file / 文件源处理

继续往下，最适合补的一段是 `time_measure.py`。

原因不是它业务权重高，而是：

- 原版工具清单里明确存在它
- 当前仓库里已经有若干“自然值得测时”的业务节点
- 现在的项目还没有统一的轻量计时工具层
- 这件事适合在还没进入更重 observability 之前先做成稳定小模块

## 二、现状问题

### 1. 项目里有计时需求，但没有统一工具

当前仓库很多地方已经有天然的“耗时观察点”，比如：

- `video_understanding.py` 的帧提取 / VLM 分析
- `lvs_video_understanding.py` 的 chunk 分析编排
- 后续报告链、Agent 链都可能需要轻量耗时日志

但这些地方当前更多依赖零散 logger，而不是统一计时工具。

### 2. 现在不适合直接引入大观测系统

虽然“计时”往前走可以演化成：

- tracing
- metrics
- span tree
- request correlation

但当前阶段没有必要。Phase 7A6 要做的是一个“轻量而稳定”的基础设施，不是观测平台。

### 3. 如果只补文件不接真实调用点，价值会偏虚

单独新增 `time_measure.py` 当然可以，但如果完全不接入主链，那它的价值不够扎实，也难以验证设计是否贴仓库风格。

因此 A6 需要至少接一个真实点，但这个接入应当足够小，不改变返回接口，不扩散到太多业务文件。

## 三、设计目标

Phase 7A6 的目标如下：

1. 新增共享 `utils/time_measure.py`
2. 提供同步与异步都可用的轻量计时上下文
3. 可选择记录 logger，但不强依赖 logging
4. 在一个真实主链点接入，不改变业务返回接口
5. 测试优先，锁定耗时值与上下文使用语义

## 四、候选方案

### 方案 A：最小计时工具层 + 一个真实接点（推荐）

做法：

- 新增 `time_measure.py`
- 提供同步 / 异步 context manager
- 只接一个主链点，例如 `video_understanding.py`

优点：

- 范围稳定
- 能真正落地
- 不会引入复杂观测设计

缺点：

- 这一轮带来的可见变化偏小

### 方案 B：做成统一 observability 层

做法：

- 计时 + tracing + structured logs 一起设计

优点：

- 长期更完整

缺点：

- 明显超出当前阶段重量

### 方案 C：只补工具，不接业务

优点：

- 最保守

缺点：

- 价值偏虚
- 不利于验证实际适配性

## 五、最终选择

本阶段采用 **方案 A：最小计时工具层 + 一个真实接点**。

理由：

- 既补齐原版缺失模块
- 又不会把项目拉进更大观测系统设计
- 有一个真实接点，能验证工具是否真的顺手

## 六、模块设计

### 1. `utils/time_measure.py`

建议提供以下能力：

1. `TimeMeasureResult`
   - 轻量结果对象
   - 至少包含：
     - `label: str`
     - `elapsed_sec: float`

2. `measure_time(label: str, logger=None)`
   - 同步上下文管理器
   - `with` 结束后可读取结果对象

3. `async_measure_time(label: str, logger=None)`
   - 异步上下文管理器
   - `async with` 结束后可读取结果对象

logger 行为：

- 若提供 logger，则在退出时记录耗时
- 若未提供，则只返回结果对象，不强制输出日志

### 2. 真实接入点

推荐第一接点：

- `src/vsa_agent/tools/video_understanding.py`

适合接的位置：

- `_analyze_frames(...)` 的 VLM 调用外层
- 或 `analyze_video(...)` 的主路径判断 / segment 调用外层

本阶段建议只选 **一个**，避免把 A6 扩得太宽。

推荐优先接 `_analyze_frames(...)`，因为：

- 它是单点、稳定、调用频繁
- 不影响外部返回值
- 与“模型调用耗时”这个语义天然匹配

如需第二接点，可选：

- `lvs_video_understanding.py` 的 chunk 迭代分析

但不是 A6 必需项。

## 七、错误处理策略

`time_measure.py` 的原则：

- 计时工具不吞业务异常
- 即使上下文内部抛错，也应记录 elapsed
- 然后继续把异常向上抛出

这点很重要：计时工具是观察层，不是控制层。

## 八、测试策略

### 1. `tests/unit/utils/test_time_measure.py`

覆盖：

- 同步上下文返回耗时结果
- 异步上下文返回耗时结果
- 即使上下文内部抛错，结果对象仍被写入
- logger 被调用时包含 label 与 elapsed

### 2. `tests/unit/tools/test_video_understanding.py`

补最小回归：

- 验证 `_analyze_frames(...)` 在计时工具接入后仍保持原接口行为
- 如通过 monkeypatch 接入计时上下文，可验证它确实被调用

## 九、非目标

本阶段不做：

- tracing/span 系统
- 指标上报系统
- 全局 request id 传播
- 多层嵌套性能分析树
- 大规模业务点全面埋点

## 十、验收标准

1. 新增 `utils/time_measure.py`
2. 新增 `tests/unit/utils/test_time_measure.py`
3. 至少一个真实调用点接入共享计时工具
4. 外部接口不变
5. A6 相关测试全部通过
6. 唯一总计划文档同步记录 A6 状态

