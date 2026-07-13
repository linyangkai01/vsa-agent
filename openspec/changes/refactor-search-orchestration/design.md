## Context

`search.py` 的核心异步生成器同时负责查询分解、三路径选择、结果类型转换、置信度处理、融合、Critic 迭代和进度消息。`embed_search.py` 与 `attribute_search.py` 也各自包含结果适配与宽泛异常降级。当前行为依赖许多局部分支，尤其是空结果、低置信度和 Critic 失败继续执行路径。

## Goals / Non-Goals

**Goals:**

- 为搜索路由、执行、归一化、融合和 Critic 建立独立可测试边界。
- 统一重复的结果转换和异常降级规则。
- 保持异步进度消息和最终 `SearchOutput` 行为。

**Non-Goals:**

- 不改变公开搜索模型、API、工具注册名称或 Elasticsearch schema。
- 不调整排序公式、阈值默认值、top_k 或 Critic 产品语义。
- 不在本 change 中更换检索后端。

## Decisions

1. 以当前 `execute_core_search` 为 facade，将属性-only、向量-only、融合和 Critic 阶段拆成明确函数；facade 只协调阶段和输出进度消息。
2. 引入单一结果归一化边界，将 `SearchOutput`、带 `.data` 对象和受支持列表转为 `list[SearchResult]`。不支持类型显式失败或按现有降级契约记录。
3. 去重、置信度回退、融合排序和最终裁剪使用纯函数，分别锁定现有顺序和分数语义。
4. 宽泛异常仅保留在外部依赖边界，并通过统一日志上下文记录阶段；纯转换错误不静默吞掉。
5. 公共 import 路径和工具注册保留，内部 helper 可放入独立 pipeline 模块以降低 facade 体积。

## Risks / Trade-offs

- [风险] 统一归一化可能改变宽松输入兼容。 -> 用 characterization tests 覆盖当前接受的每种结果形状。
- [风险] 拆分异步生成器可能改变消息顺序。 -> 断言完整消息类型和最终输出序列。
- [风险] 修正异常吞噬会改变降级。 -> 本 change 只统一已有降级，新的严格行为另行提案。

## Migration Plan

1. 为各搜索路径、结果形状和 Critic 状态补充 characterization tests。
2. 提取纯归一化、融合和裁剪 helper。
3. 提取外部搜索与 Critic 阶段，保留 facade 输出顺序。
4. 分别运行工具、代理、API 搜索测试和全量测试；失败时按阶段回滚。

## Open Questions

无。
